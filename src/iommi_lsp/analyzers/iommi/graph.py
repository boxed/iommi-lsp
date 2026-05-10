"""Schema + load/save for the iommi reflection graph.

The graph is generated once per project by ``iommi-lsp graph build`` (which
imports iommi from the user's venv) and dumped to ``.iommi-lsp-graph.json``
in the workspace root. The LSP loads it at startup and uses it to validate
``Class(kw__chain=...)`` calls against iommi's refinable hierarchy.

Six refinable kinds capture iommi's surface:

* ``members`` — open dict of typed values (e.g. ``Dict[str, Column]``).
  ``member_class`` points at the per-entry type, when known.
* ``html_attrs`` — the ``attrs`` special. Has two sub-specials:
  ``class`` (``str → bool``) and ``style`` (``str → str``).
* ``class_ref`` — chain steps into another refinable class. Annotation
  wins over runtime default (``bulk: Optional[Form]`` resolves to ``Form``
  even when the default is a ``Namespace``).
* ``namespace`` — structured with a small set of known sub-keys.
* ``open_namespace`` — empty Namespace default; any keys allowed.
* ``evaluated_scalar`` / ``scalar`` — leaf; chain ends here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


GRAPH_FILENAME = ".iommi-lsp-graph.json"
SCHEMA_VERSION = 1


RefinableKind = Literal[
    "members",
    "html_attrs",
    "class_ref",
    "namespace",
    "open_namespace",
    "evaluated_scalar",
    "scalar",
]


@dataclass
class Refinable:
    """One refinable on an iommi class."""

    name: str
    kind: RefinableKind
    refinable_type: str = ""           # the Refinable subclass name (debug)
    member_class: str | None = None    # for kind="members"
    target: str | None = None          # for kind="class_ref"
    known_keys: list[str] = field(default_factory=list)  # for kind="namespace"
    sub_specials: dict[str, dict] = field(default_factory=dict)  # for kind="html_attrs"


@dataclass
class IommiClass:
    qualname: str
    bases: list[str]
    refinables: dict[str, Refinable] = field(default_factory=dict)


@dataclass
class IommiGraph:
    classes: dict[str, IommiClass] = field(default_factory=dict)
    iommi_version: str | None = None
    schema_version: int = SCHEMA_VERSION

    def get(self, qualname: str) -> IommiClass | None:
        return self.classes.get(qualname)

    def has(self, qualname: str) -> bool:
        return qualname in self.classes

    def by_simple_name(self, simple: str) -> list[IommiClass]:
        return [c for q, c in self.classes.items() if q.rsplit(".", 1)[-1] == simple]

    def lookup_simple(self, simple: str) -> IommiClass | None:
        candidates = self.by_simple_name(simple)
        return candidates[0] if len(candidates) == 1 else None


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_json(graph: IommiGraph) -> str:
    payload = {
        "schema_version": graph.schema_version,
        "iommi_version": graph.iommi_version,
        "classes": {
            q: {
                "qualname": c.qualname,
                "bases": list(c.bases),
                "refinables": {n: _refinable_to_dict(r) for n, r in c.refinables.items()},
            }
            for q, c in graph.classes.items()
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def from_json(text: str) -> IommiGraph:
    data: Any = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("graph json: expected top-level object")
    classes: dict[str, IommiClass] = {}
    for q, raw in (data.get("classes") or {}).items():
        refinables: dict[str, Refinable] = {}
        for n, rraw in (raw.get("refinables") or {}).items():
            refinables[n] = _refinable_from_dict(rraw)
        classes[q] = IommiClass(
            qualname=raw.get("qualname", q),
            bases=list(raw.get("bases") or []),
            refinables=refinables,
        )
    return IommiGraph(
        classes=classes,
        iommi_version=data.get("iommi_version"),
        schema_version=int(data.get("schema_version") or SCHEMA_VERSION),
    )


def _refinable_to_dict(r: Refinable) -> dict:
    out: dict[str, Any] = {"kind": r.kind, "refinable_type": r.refinable_type}
    if r.member_class is not None:
        out["member_class"] = r.member_class
    if r.target is not None:
        out["target"] = r.target
    if r.known_keys:
        out["known_keys"] = list(r.known_keys)
    if r.sub_specials:
        out["sub_specials"] = dict(r.sub_specials)
    return out


def _refinable_from_dict(d: dict) -> Refinable:
    return Refinable(
        name=d.get("name", ""),
        kind=d.get("kind", "scalar"),
        refinable_type=d.get("refinable_type", ""),
        member_class=d.get("member_class"),
        target=d.get("target"),
        known_keys=list(d.get("known_keys") or []),
        sub_specials=dict(d.get("sub_specials") or {}),
    )


def load_graph(path: Path) -> IommiGraph | None:
    if not path.exists():
        return None
    try:
        return from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def save_graph(graph: IommiGraph, path: Path) -> None:
    path.write_text(to_json(graph), encoding="utf-8")
