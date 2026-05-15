"""Pure-function walker for ``kw__chain`` segments against the iommi graph.

Given a starting class and the segments of a flattened kwarg name (split
on ``__``), walks the refinable graph and returns either ``OK`` or a
``Problem`` describing the first segment that didn't validate. Bias is
toward false negatives — unknown classes, missing edges, anything we
can't be sure about → ``OK``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .graph import IommiClass, IommiGraph, Refinable


# Heuristic: any chain segment named ``attrs`` reached from an iommi class
# behaves like ``html_attrs`` (Tag-style HTML attribute namespace). This
# catches the cases the static reflector misses — `attrs` declared on
# Tag/Part mixins that don't end up in the graph, or `attrs` showing up
# as a key inside a Namespace default like ``cell = Namespace(attrs=…)``.
_ATTRS_NAME = "attrs"


def _synthetic_html_attrs() -> Refinable:
    return Refinable(
        name=_ATTRS_NAME,
        kind="html_attrs",
        sub_specials={
            "class": {"value_type": "bool"},
            "style": {"value_type": "str"},
        },
    )


WalkOutcome = Literal["ok", "unknown_refinable", "trailing_segments_after_leaf"]


@dataclass(frozen=True)
class Problem:
    outcome: WalkOutcome
    bad_segment: str
    segment_index: int    # 0-based position in the chain
    on_class: str         # qualname of the class we were validating against
    available: tuple[str, ...] = ()  # known refinables on `on_class` (for hints)


@dataclass(frozen=True)
class Ok:
    pass


OK = Ok()
WalkResult = Ok | Problem


def split_chain(kwarg_name: str) -> list[str]:
    return kwarg_name.split("__")


def walk(
    graph: IommiGraph,
    start_class: str,
    chain: list[str],
) -> WalkResult:
    """Walk ``chain`` starting at *start_class*. Returns OK or first Problem."""
    if not chain:
        return OK

    cls = graph.get(start_class)
    if cls is None:
        # Unknown root class → can't validate; pass.
        return OK

    return _walk_from(graph, cls, chain, 0)


def _walk_from(
    graph: IommiGraph,
    cls: IommiClass,
    chain: list[str],
    i: int,
) -> WalkResult:
    if i >= len(chain):
        return OK

    segment = chain[i]
    refinable = _resolve_refinable(graph, cls, segment)
    if refinable is None:
        if segment == _ATTRS_NAME:
            # Static reflection missed it — `attrs` on a Tag/Part-style
            # mixin we don't have in the graph, etc. Treat as html_attrs.
            return _step(
                graph, _synthetic_html_attrs(), chain, i + 1, parent_class=cls
            )
        return Problem(
            outcome="unknown_refinable",
            bad_segment=segment,
            segment_index=i,
            on_class=cls.qualname,
            available=tuple(sorted(_all_refinables(graph, cls))),
        )

    return _step(graph, refinable, chain, i + 1, parent_class=cls)


def _step(
    graph: IommiGraph,
    refinable: Refinable,
    chain: list[str],
    j: int,
    *,
    parent_class: IommiClass,
) -> WalkResult:
    """We just consumed a refinable; *j* is the index of the next segment."""
    remaining = chain[j:]
    if refinable.kind == "scalar" or refinable.kind == "evaluated_scalar":
        if remaining:
            return Problem(
                outcome="trailing_segments_after_leaf",
                bad_segment=remaining[0],
                segment_index=j,
                on_class=parent_class.qualname,
            )
        return OK

    if refinable.kind == "open_namespace":
        # Anything goes after this point.
        return OK

    if refinable.kind == "namespace":
        if not remaining:
            return OK
        next_seg = remaining[0]
        if refinable.known_keys and next_seg not in refinable.known_keys:
            return Problem(
                outcome="unknown_refinable",
                bad_segment=next_seg,
                segment_index=j,
                on_class=parent_class.qualname,
                available=tuple(refinable.known_keys),
            )
        if next_seg == _ATTRS_NAME:
            # Recurse into html_attrs validation rather than allowing
            # everything past the namespace boundary.
            return _step(
                graph, _synthetic_html_attrs(), chain, j + 1, parent_class=parent_class
            )
        # No granular type info beyond known_keys; allow the rest.
        return OK

    if refinable.kind == "html_attrs":
        return _step_html_attrs(refinable, chain, j, parent_class=parent_class)

    if refinable.kind == "members":
        if not remaining:
            return OK
        # First segment after a `members` refinable is the user-supplied
        # member name — accept anything. Step into member_class for the rest.
        if len(remaining) == 1:
            return OK
        if refinable.member_class is None:
            # Members but we don't know the value type — treat as open.
            return OK
        target = graph.get(refinable.member_class)
        if target is None:
            return OK
        return _walk_from(graph, target, chain, j + 1)

    if refinable.kind == "class_ref":
        if not remaining:
            return OK
        if refinable.target is None:
            return OK
        target = graph.get(refinable.target)
        if target is None:
            return OK
        return _walk_from(graph, target, chain, j)

    if refinable.kind == "traditional_class":
        return _step_traditional(
            graph, refinable, chain, j, parent_class=parent_class
        )

    return OK


def _step_traditional(
    graph: IommiGraph,
    refinable: Refinable,
    chain: list[str],
    j: int,
    *,
    parent_class: IommiClass,
) -> WalkResult:
    """Validate the chain past a ``traditional_class`` refinable.

    The next segment must be one of the target class's ``init_members``
    (public ``self.X = …`` assignments in its ``__init__`` chain). Most
    such names are leaves — except ``attrs``, which is the iommi HTML
    attribute namespace and recurses through ``class``/``style``/etc.
    If the graph doesn't know the target class or its members, bias
    toward OK so we don't flag valid code as broken.
    """
    remaining = chain[j:]
    if not remaining:
        return OK
    if refinable.target is None:
        return OK
    target = graph.get(refinable.target)
    if target is None or not target.init_members:
        return OK
    head = remaining[0]
    if head not in target.init_members:
        return Problem(
            outcome="unknown_refinable",
            bad_segment=head,
            segment_index=j,
            on_class=target.qualname,
            available=tuple(target.init_members),
        )
    if head == _ATTRS_NAME:
        return _step_html_attrs(
            _synthetic_html_attrs(), chain, j + 1, parent_class=target
        )
    if len(remaining) > 1:
        return Problem(
            outcome="trailing_segments_after_leaf",
            bad_segment=remaining[1],
            segment_index=j + 1,
            on_class=target.qualname,
        )
    return OK


def _step_html_attrs(
    refinable: Refinable, chain: list[str], j: int, *, parent_class: IommiClass
) -> WalkResult:
    """Walk through ``attrs__...``. Direct attribute, ``class``, or ``style``."""
    remaining = chain[j:]
    if not remaining:
        return OK
    head = remaining[0]
    sub = refinable.sub_specials.get(head)
    if sub is None:
        # Direct HTML attribute; any name OK; chain ends here.
        # `attrs__data_foo="bar"` is fine; `attrs__data_foo__bar=...` is not
        # (you can't nest into a scalar HTML attribute value).
        if len(remaining) > 1:
            return Problem(
                outcome="trailing_segments_after_leaf",
                bad_segment=remaining[1],
                segment_index=j + 1,
                on_class=parent_class.qualname,
            )
        return OK
    # `class` / `style`: dict[str, value]. Next segment is any class/style key.
    # Anything past that is invalid (the value is a leaf bool/str).
    if len(remaining) <= 2:
        return OK
    return Problem(
        outcome="trailing_segments_after_leaf",
        bad_segment=remaining[2],
        segment_index=j + 2,
        on_class=parent_class.qualname,
    )


# ---------------------------------------------------------------------------
# Refinable resolution that walks bases too
# ---------------------------------------------------------------------------


def _resolve_refinable(graph: IommiGraph, cls: IommiClass, name: str) -> Refinable | None:
    if name in cls.refinables:
        return cls.refinables[name]
    for base in cls.bases:
        bcls = graph.get(base)
        if bcls is None:
            continue
        if name in bcls.refinables:
            return bcls.refinables[name]
    return None


def _all_refinables(graph: IommiGraph, cls: IommiClass) -> set[str]:
    names = set(cls.refinables)
    for base in cls.bases:
        bcls = graph.get(base)
        if bcls is not None:
            names.update(bcls.refinables)
    return names
