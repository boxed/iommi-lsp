"""Round-trip + reflector tests for the iommi graph.

Reflector runs against the real iommi (it's a dev dep), so this also
catches breakage when iommi changes its Refinable surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iommi_lsp.analyzers.iommi.graph import (
    GRAPH_FILENAME,
    IommiClass,
    IommiGraph,
    Refinable,
    from_json,
    load_graph,
    save_graph,
    to_json,
)


def test_round_trip_minimal_graph(tmp_path: Path):
    g = IommiGraph(
        iommi_version="7.25.1",
        classes={
            "x.Y": IommiClass(
                qualname="x.Y",
                bases=["x.Base"],
                refinables={
                    "columns": Refinable(
                        name="columns", kind="members",
                        member_class="x.Col", refinable_type="RefinableMembers",
                    ),
                    "attrs": Refinable(
                        name="attrs", kind="html_attrs",
                        refinable_type="SpecialEvaluatedRefinable",
                        sub_specials={"class": {"value_type": "bool"}},
                    ),
                },
            ),
        },
    )
    f = tmp_path / GRAPH_FILENAME
    save_graph(g, f)
    g2 = load_graph(f)
    assert g2 is not None
    assert g2.iommi_version == "7.25.1"
    assert g2.has("x.Y")
    cols = g2.get("x.Y").refinables["columns"]
    assert cols.kind == "members"
    assert cols.member_class == "x.Col"
    attrs = g2.get("x.Y").refinables["attrs"]
    assert attrs.kind == "html_attrs"
    assert attrs.sub_specials == {"class": {"value_type": "bool"}}


def test_load_missing_graph_returns_none(tmp_path: Path):
    assert load_graph(tmp_path / "nope.json") is None


def test_load_corrupt_graph_returns_none(tmp_path: Path):
    f = tmp_path / "broken.json"
    f.write_text("{not json")
    assert load_graph(f) is None


def test_lookup_simple_returns_unique_match(tmp_path: Path):
    g = IommiGraph(classes={
        "iommi.table.Table": IommiClass(qualname="iommi.table.Table", bases=[]),
        "iommi.form.Form": IommiClass(qualname="iommi.form.Form", bases=[]),
    })
    assert g.lookup_simple("Table").qualname == "iommi.table.Table"
    assert g.lookup_simple("Nope") is None


# ---------------------------------------------------------------------------
# Reflector tests against real iommi (skipped if iommi isn't installed)
# ---------------------------------------------------------------------------


iommi = pytest.importorskip("iommi")


def test_reflector_classifies_table_correctly():
    from iommi_lsp.analyzers.iommi.reflect import build

    g = build()
    assert g.has("iommi.table.Table")
    table = g.get("iommi.table.Table")

    # columns: Dict[str, Column] = RefinableMembers()
    cols = table.refinables["columns"]
    assert cols.kind == "members"
    assert cols.member_class == "iommi.table.Column"

    # attrs: special with two sub-specials
    attrs = table.refinables["attrs"]
    assert attrs.kind == "html_attrs"
    assert "class" in attrs.sub_specials
    assert "style" in attrs.sub_specials

    # bulk: Optional[Form] = EvaluatedRefinable() — annotation wins over Namespace default
    bulk = table.refinables["bulk"]
    assert bulk.kind == "class_ref"
    assert bulk.target == "iommi.form.Form"


def test_reflector_transitively_includes_targets():
    from iommi_lsp.analyzers.iommi.reflect import build

    g = build()
    # Transitively reachable from Table.bulk -> Form, Table.columns -> Column, etc.
    for q in (
        "iommi.table.Column",
        "iommi.form.Form",
        "iommi.action.Action",
    ):
        assert g.has(q), f"missing {q} from transitive walk"


def test_reflector_records_iommi_version():
    from iommi_lsp.analyzers.iommi.reflect import build

    g = build()
    assert g.iommi_version is not None
    # Loose check — the format is "X.Y.Z" but we don't pin to one version.
    assert g.iommi_version[0].isdigit()
