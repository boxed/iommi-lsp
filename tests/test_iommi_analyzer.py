"""Integration tests for IommiAnalyzer over a workspace + graph fixture."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from iommi_lsp.analyzers.iommi import IommiAnalyzer
from iommi_lsp.analyzers.iommi.graph import (
    GRAPH_FILENAME,
    IommiClass,
    IommiGraph,
    Refinable,
    save_graph,
)


def _r(name, kind, **kw):
    return Refinable(name=name, kind=kind, **kw)


def _make_fixture_graph() -> IommiGraph:
    column = IommiClass(
        qualname="iommi.table.Column",
        bases=["iommi.part.Part"],
        refinables={
            "extra": _r("extra", "open_namespace"),
            "after": _r("after", "evaluated_scalar"),
            "cell": _r("cell", "namespace", known_keys=["attrs", "contents"]),
        },
    )
    part = IommiClass(
        qualname="iommi.part.Part",
        bases=[],
        refinables={
            "attrs": _r(
                "attrs", "html_attrs",
                sub_specials={"class": {"value_type": "bool"}, "style": {"value_type": "str"}},
            ),
        },
    )
    table = IommiClass(
        qualname="iommi.table.Table",
        bases=["iommi.part.Part"],
        refinables={
            "columns": _r("columns", "members", member_class="iommi.table.Column"),
            "page_size": _r("page_size", "evaluated_scalar"),
            "attrs": _r(
                "attrs", "html_attrs",
                sub_specials={"class": {"value_type": "bool"}, "style": {"value_type": "str"}},
            ),
        },
    )
    return IommiGraph(
        iommi_version="0.0-test",
        classes={c.qualname: c for c in [table, column, part]},
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    save_graph(_make_fixture_graph(), tmp_path / GRAPH_FILENAME)
    return tmp_path


def _write_usage(workspace: Path, src: str) -> Path:
    f = workspace / "usage.py"
    f.write_text(textwrap.dedent(src).lstrip())
    return f


def _diagnose(workspace: Path, source: str) -> list[dict]:
    f = _write_usage(workspace, source)
    a = IommiAnalyzer(workspace_root=workspace)
    asyncio.run(a.index(workspace))
    return a.additional_diagnostics(f.as_uri())


def test_no_graph_means_no_diagnostics(tmp_path: Path):
    f = tmp_path / "usage.py"
    f.write_text("from iommi import Table\nTable(bogus=1)\n")
    a = IommiAnalyzer(workspace_root=tmp_path)
    asyncio.run(a.index(tmp_path))
    assert a.additional_diagnostics(f.as_uri()) == []


def test_valid_call_produces_no_diagnostics(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(columns__name__after="x", page_size=10)
    """)
    assert diags == []


def test_unknown_top_level_kwarg(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(bogus_thing=1)
    """)
    assert len(diags) == 1
    d = diags[0]
    assert d["code"] == "iommi-unknown-refinable"
    assert d["source"] == "iommi-lsp"
    assert "bogus_thing" in d["message"]
    # Range pinned to the kwarg name.
    src = (workspace / "usage.py").read_text()
    line = src.splitlines()[d["range"]["start"]["line"]]
    col = d["range"]["start"]["character"]
    assert line[col:col + len("bogus_thing")] == "bogus_thing"


def test_unknown_member_refinable_pins_to_bad_segment(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(columns__name__bogus_thing=1)
    """)
    assert len(diags) == 1
    d = diags[0]
    src = (workspace / "usage.py").read_text()
    line = src.splitlines()[d["range"]["start"]["line"]]
    col = d["range"]["start"]["character"]
    assert line[col:col + len("bogus_thing")] == "bogus_thing"
    # Segment offset within the kwarg, not the full name's start.
    assert "columns" not in line[col:col + 10]


def test_chain_past_scalar(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(page_size__bogus=1)
    """)
    assert len(diags) == 1
    assert diags[0]["data"]["outcome"] == "trailing_segments_after_leaf"


def test_html_attrs_direct_attribute_ok(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(attrs__data_thing="hi")
    """)
    assert diags == []


def test_html_attrs_class_subspecial_ok(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(attrs__class__bold=True)
    """)
    assert diags == []


def test_html_attrs_chain_past_class_value_flagged(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(attrs__class__bold__nope=True)
    """)
    assert len(diags) == 1
    assert diags[0]["data"]["outcome"] == "trailing_segments_after_leaf"


def test_attrs_directly_on_column_passes_via_heuristic(workspace: Path):
    """`attrs` is the universal iommi escape hatch — any segment named
    ``attrs`` reached from an iommi class behaves like html_attrs even
    when the static reflector missed it (custom Tag mixins, etc.)."""
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(columns__name__attrs__class__bold=True)
    """)
    assert diags == []


def test_attrs_inside_cell_namespace_recurses_into_html_attrs(workspace: Path):
    """The "right" path the user originally pointed at: cell.attrs.class.x"""
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(columns__name__cell__attrs__class__bold=True)
    """)
    assert diags == []


def test_attrs_inside_cell_chain_past_class_value_fails(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table

        t = Table(columns__name__cell__attrs__class__bold__deeper=True)
    """)
    assert len(diags) == 1
    assert diags[0]["data"]["outcome"] == "trailing_segments_after_leaf"


def test_unknown_class_silently_passes(workspace: Path):
    diags = _diagnose(workspace, """
        class NotIommi:
            def __init__(self, **kw): pass

        x = NotIommi(bogus_thing=1)
    """)
    assert diags == []


def test_kwargs_splat_is_skipped(workspace: Path):
    diags = _diagnose(workspace, """
        from iommi import Table
        opts = {"bogus": 1}
        t = Table(**opts)
    """)
    assert diags == []


def test_module_qualified_class_resolves(workspace: Path):
    diags = _diagnose(workspace, """
        import iommi
        t = iommi.Table(bogus_thing=1)
    """)
    assert len(diags) == 1
    assert "bogus_thing" in diags[0]["message"]


def test_caches_parsed_file(workspace: Path):
    f = _write_usage(workspace, "from iommi import Table\nTable(bogus=1)\n")
    a = IommiAnalyzer(workspace_root=workspace)
    asyncio.run(a.index(workspace))
    uri = f.as_uri()
    a.additional_diagnostics(uri)
    assert uri in a._cache
    asyncio.run(a.on_file_changed(uri))
    assert uri not in a._cache
