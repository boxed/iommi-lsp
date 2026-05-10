"""Pure-function tests for the chain walker."""

from __future__ import annotations

import pytest

from iommi_lsp.analyzers.iommi.graph import IommiClass, IommiGraph, Refinable
from iommi_lsp.analyzers.iommi.walker import OK, Problem, walk


def _r(name: str, kind: str, **kw) -> Refinable:
    return Refinable(name=name, kind=kind, **kw)


@pytest.fixture
def graph() -> IommiGraph:
    """Hand-built minimal graph with one of each refinable kind."""
    column = IommiClass(
        qualname="x.Column",
        bases=["x.Part"],
        refinables={
            "extra": _r("extra", "open_namespace"),
            "cell": _r("cell", "namespace", known_keys=["attrs", "contents"]),
            "after": _r("after", "evaluated_scalar"),
        },
    )
    part = IommiClass(
        qualname="x.Part",
        bases=[],
        refinables={
            "attrs": _r(
                "attrs", "html_attrs",
                sub_specials={"class": {"value_type": "bool"}, "style": {"value_type": "str"}},
            ),
        },
    )
    table = IommiClass(
        qualname="x.Table",
        bases=["x.Part"],
        refinables={
            "columns": _r("columns", "members", member_class="x.Column"),
            "parts": _r("parts", "members"),
            "page_size": _r("page_size", "evaluated_scalar"),
            "bulk": _r("bulk", "class_ref", target="x.Form"),
            "extra": _r("extra", "open_namespace"),
            "attrs": _r(
                "attrs", "html_attrs",
                sub_specials={"class": {"value_type": "bool"}, "style": {"value_type": "str"}},
            ),
        },
    )
    form = IommiClass(
        qualname="x.Form",
        bases=[],
        refinables={
            "fields": _r("fields", "members"),
            "title": _r("title", "evaluated_scalar"),
        },
    )
    return IommiGraph(classes={c.qualname: c for c in [table, column, part, form]})


def test_known_top_level_refinable_passes(graph):
    assert walk(graph, "x.Table", ["page_size"]) is OK


def test_unknown_top_level_refinable_fails(graph):
    res = walk(graph, "x.Table", ["bogus_thing"])
    assert isinstance(res, Problem)
    assert res.outcome == "unknown_refinable"
    assert res.bad_segment == "bogus_thing"
    assert res.segment_index == 0
    assert res.on_class == "x.Table"


def test_chain_through_members_validates_member_class(graph):
    # columns -> any name -> step into Column refinables
    assert walk(graph, "x.Table", ["columns", "name", "after"]) is OK


def test_unknown_refinable_on_member_class(graph):
    res = walk(graph, "x.Table", ["columns", "name", "bogus"])
    assert isinstance(res, Problem)
    assert res.bad_segment == "bogus"
    assert res.on_class == "x.Column"


def test_chain_through_open_namespace_accepts_anything(graph):
    assert walk(graph, "x.Table", ["extra", "anything", "deep", "key"]) is OK


def test_namespace_known_keys_validate(graph):
    assert walk(graph, "x.Table", ["columns", "name", "cell", "attrs", "anything"]) is OK


def test_namespace_unknown_key_fails(graph):
    res = walk(graph, "x.Table", ["columns", "name", "cell", "bogus"])
    assert isinstance(res, Problem)
    assert res.bad_segment == "bogus"
    assert res.outcome == "unknown_refinable"


def test_class_ref_steps_into_target(graph):
    # bulk -> Form. fields is on Form. Should validate.
    assert walk(graph, "x.Table", ["bulk", "fields", "name"]) is OK


def test_class_ref_unknown_refinable_on_target(graph):
    res = walk(graph, "x.Table", ["bulk", "bogus_form_thing"])
    assert isinstance(res, Problem)
    assert res.on_class == "x.Form"
    assert res.bad_segment == "bogus_form_thing"


def test_html_attrs_direct_attribute_ok(graph):
    assert walk(graph, "x.Table", ["attrs", "data_thing"]) is OK


def test_html_attrs_class_subspecial(graph):
    assert walk(graph, "x.Table", ["attrs", "class", "bold"]) is OK


def test_html_attrs_style_subspecial(graph):
    assert walk(graph, "x.Table", ["attrs", "style", "color"]) is OK


def test_html_attrs_chain_past_class_value_fails(graph):
    res = walk(graph, "x.Table", ["attrs", "class", "bold", "extra"])
    assert isinstance(res, Problem)
    assert res.outcome == "trailing_segments_after_leaf"
    assert res.bad_segment == "extra"


def test_html_attrs_chain_past_direct_attribute_fails(graph):
    res = walk(graph, "x.Table", ["attrs", "data_thing", "deeper"])
    assert isinstance(res, Problem)
    assert res.outcome == "trailing_segments_after_leaf"


def test_chain_past_scalar_fails(graph):
    res = walk(graph, "x.Table", ["page_size", "bogus"])
    assert isinstance(res, Problem)
    assert res.outcome == "trailing_segments_after_leaf"
    assert res.bad_segment == "bogus"


def test_inherited_refinable_via_base_class(graph):
    # `attrs` is on Part; Column inherits Part. Validating Column.attrs OK.
    assert walk(graph, "x.Column", ["attrs", "data_x"]) is OK


def test_unknown_root_class_silently_passes(graph):
    # Not in graph -> walker bias toward false negatives.
    assert walk(graph, "x.Unknown", ["bogus", "more"]) is OK


def test_members_with_no_member_class_accepts_anything(graph):
    # `parts` is members with no member_class -> open after the user key.
    assert walk(graph, "x.Table", ["parts", "anything", "deeper"]) is OK


# ---------------------------------------------------------------------------
# `attrs` heuristic: any segment named ``attrs`` reached from an iommi
# class behaves like html_attrs, even when the static reflector missed it.
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_no_part_attrs() -> IommiGraph:
    """Like `graph` but Column doesn't inherit `attrs` (Part is missing)."""
    column = IommiClass(
        qualname="x.Column",
        bases=[],   # no base classes in graph at all
        refinables={
            "extra": _r("extra", "open_namespace"),
            "cell": _r("cell", "namespace", known_keys=["attrs", "contents", "link"]),
        },
    )
    table = IommiClass(
        qualname="x.Table",
        bases=[],
        refinables={
            "columns": _r("columns", "members", member_class="x.Column"),
        },
    )
    return IommiGraph(classes={c.qualname: c for c in [table, column]})


def test_attrs_on_class_without_declared_refinable_is_treated_as_html_attrs(graph_no_part_attrs):
    # Column has no `attrs` refinable in this graph at all. The walker
    # should still accept `columns__name__attrs__class__bold` because
    # `attrs` is the universal iommi escape hatch.
    assert walk(graph_no_part_attrs, "x.Table", ["columns", "name", "attrs", "class", "bold"]) is OK


def test_attrs_inside_namespace_recurses_into_html_attrs(graph_no_part_attrs):
    # cell is a namespace with known_keys [attrs, contents, link]. Stepping
    # through `cell__attrs__class__bold` should validate via html_attrs.
    assert walk(graph_no_part_attrs, "x.Table", ["columns", "name", "cell", "attrs", "class", "bold"]) is OK


def test_attrs_inside_namespace_chain_past_class_value_fails(graph_no_part_attrs):
    res = walk(graph_no_part_attrs, "x.Table", [
        "columns", "name", "cell", "attrs", "class", "bold", "deeper"
    ])
    assert isinstance(res, Problem)
    assert res.outcome == "trailing_segments_after_leaf"


def test_attrs_inside_namespace_direct_attribute_ok(graph_no_part_attrs):
    # cell.attrs.data_thing="hi" -> direct HTML attribute, not class/style.
    assert walk(graph_no_part_attrs, "x.Table", ["columns", "name", "cell", "attrs", "data_thing"]) is OK


def test_non_attrs_namespace_keys_still_pass_through_freely(graph_no_part_attrs):
    # cell.contents is a known key but not "attrs" -> existing permissive
    # behavior (no further validation).
    assert walk(graph_no_part_attrs, "x.Table", ["columns", "name", "cell", "contents", "anything"]) is OK
