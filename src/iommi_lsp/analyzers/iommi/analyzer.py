"""IommiAnalyzer — adds diagnostics for invalid ``Class(kw__chain=...)``.

Loads the workspace's ``.iommi-lsp-graph.json`` (produced by
``iommi-lsp graph build``) and validates each call whose callee is a
known iommi class. The first dead-end segment in a flattened kwarg
chain becomes a ``unknown-iommi-refinable`` diagnostic at that
segment's source range.

The analyzer never *removes* diagnostics — it only adds — so it composes
cleanly with the Django filter on the same proxy.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from ... import log
from ..base import Diagnostic
from .graph import GRAPH_FILENAME, IommiGraph, load_graph
from .walker import Problem, _all_refinables, walk


_log = log.get("iommi.analyzer")


_IOMMI_DIAG_CODE = "iommi-unknown-refinable"
_IOMMI_DIAG_SOURCE = "iommi-lsp"


@dataclass
class _ParsedFile:
    tree: ast.Module
    source: str


class IommiAnalyzer:
    name = "iommi"

    def __init__(
        self,
        workspace_root: Path,
        graph: IommiGraph | None = None,
        text_provider: Callable[[str], str | None] | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.graph: IommiGraph = graph or IommiGraph()
        self._text_provider = text_provider
        self._cache: dict[str, _ParsedFile] = {}

    # -- Analyzer protocol ----------------------------------------------------

    async def index(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        loaded = load_graph(workspace_root / GRAPH_FILENAME)
        if loaded is None:
            _log.info(
                "no iommi graph at %s; iommi analyzer is inert",
                workspace_root / GRAPH_FILENAME,
            )
            self.graph = IommiGraph()
        else:
            self.graph = loaded
            _log.info(
                "loaded iommi graph: %d classes (iommi %s)",
                len(self.graph.classes), self.graph.iommi_version,
            )
        self._cache.clear()

    async def on_file_changed(self, uri: str) -> None:
        self._cache.pop(uri, None)

    def is_false_positive(self, uri: str, diagnostic: Diagnostic) -> bool:
        return False  # we only add, never subtract

    def additional_diagnostics(self, uri: str) -> list[Diagnostic]:
        if not self.graph.classes:
            return []
        path = _uri_to_path(uri)
        if path is None:
            return []
        parsed = self._parse(uri, path)
        if parsed is None:
            return []
        return list(self._scan(parsed))

    # -- internals ------------------------------------------------------------

    def _parse(self, uri: str, path: Path) -> _ParsedFile | None:
        source = self._source_for(uri, path)
        if source is None:
            return None
        cached = self._cache.get(uri)
        if cached is not None and cached.source == source:
            return cached
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as e:
            _log.debug("could not parse %s: %s", path, e)
            return None
        parsed = _ParsedFile(tree=tree, source=source)
        self._cache[uri] = parsed
        return parsed

    def _source_for(self, uri: str, path: Path) -> str | None:
        if self._text_provider is not None:
            text = self._text_provider(uri)
            if text is not None:
                return text
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            _log.debug("could not read %s: %s", path, e)
            return None

    def _scan(self, parsed: _ParsedFile):
        imports = _collect_imports(parsed.tree)
        for node in ast.walk(parsed.tree):
            if not isinstance(node, ast.Call):
                continue
            cls_qualname = _resolve_callee(node.func, imports)
            if cls_qualname is None:
                continue
            cls = self.graph.get(cls_qualname)
            if cls is None:
                # Try simple-name lookup — useful when the user imports
                # a class via re-export (`from iommi import Table`) but
                # we recorded it under its source module.
                simple = cls_qualname.rsplit(".", 1)[-1]
                cls = self.graph.lookup_simple(simple)
                if cls is None:
                    continue

            for kw in node.keywords:
                if kw.arg is None:
                    continue   # **kwargs splat — skip
                chain = kw.arg.split("__")
                result = walk(self.graph, cls.qualname, chain)
                if isinstance(result, Problem):
                    diag = _problem_to_diagnostic(parsed.source, kw, chain, result)
                    if diag is not None:
                        yield diag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uri_to_path(uri: str) -> Path | None:
    if not uri.startswith("file://"):
        return None
    parsed = urlparse(uri)
    return Path(unquote(parsed.path))


def _collect_imports(tree: ast.Module) -> dict[str, str]:
    """Map local name → fully-qualified import. Same idea as the Django index."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                out[alias.asname or head] = alias.name if alias.asname else head
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                out[local] = f"{node.module}.{alias.name}"
    return out


def _resolve_callee(func: ast.AST, imports: dict[str, str]) -> str | None:
    """Resolve ``Class``, ``mod.Class``, ``a.b.Class`` to a qualname via imports."""
    if isinstance(func, ast.Name):
        return imports.get(func.id, func.id)
    if isinstance(func, ast.Attribute):
        flat = _flatten_attribute(func)
        if flat is None:
            return None
        head, _, tail = flat.partition(".")
        if head in imports:
            return f"{imports[head]}.{tail}" if tail else imports[head]
        return flat
    return None


def _flatten_attribute(node: ast.AST) -> str | None:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _problem_to_diagnostic(
    source: str, kw: ast.keyword, chain: list[str], problem: Problem
) -> Diagnostic | None:
    """Pin the diagnostic to the specific bad segment within the kwarg name."""
    if kw.arg is None or kw.value is None:
        return None
    # ast on a keyword: `foo__bar=value`. The keyword name doesn't have
    # its own range in `ast` (Python doesn't track it precisely), so we
    # locate it by searching the source line.
    arg_name = kw.arg
    line0 = (kw.value.lineno - 1) if kw.value.lineno else 0
    line_text = source.splitlines()[line0] if line0 < len(source.splitlines()) else ""
    # Find the kwarg name on this line. Defensive against multi-line expressions.
    name_col = line_text.find(arg_name)
    if name_col == -1:
        # Multi-line expression: best-effort fall back to the value's range.
        col_start = (kw.value.col_offset or 0)
        col_end = col_start + 1
        return _make_diagnostic(
            line0,
            col_start,
            col_end,
            f"unknown iommi refinable {problem.bad_segment!r} on {problem.on_class}",
            problem,
        )

    # Compute the offset of the bad segment within `arg_name`.
    sep = "__"
    seg_offset = 0
    for i, seg in enumerate(chain):
        if i == problem.segment_index:
            break
        seg_offset += len(seg) + len(sep)

    col_start = name_col + seg_offset
    col_end = col_start + len(problem.bad_segment)

    return _make_diagnostic(
        line0,
        col_start,
        col_end,
        _format_message(problem),
        problem,
    )


def _format_message(problem: Problem) -> str:
    if problem.outcome == "unknown_refinable":
        msg = (
            f"unknown iommi refinable {problem.bad_segment!r} on "
            f"{problem.on_class}"
        )
        if problem.available:
            hint = ", ".join(problem.available[:8])
            if len(problem.available) > 8:
                hint += ", …"
            msg += f"  (available: {hint})"
        return msg
    if problem.outcome == "trailing_segments_after_leaf":
        return (
            f"refinable chain extends past a leaf at {problem.bad_segment!r}; "
            "the previous segment maps to a scalar/HTML attribute"
        )
    return f"invalid iommi refinable chain at {problem.bad_segment!r}"


def _make_diagnostic(
    line: int, col_start: int, col_end: int, message: str, problem: Problem
) -> Diagnostic:
    return {
        "code": _IOMMI_DIAG_CODE,
        "message": message,
        "range": {
            "start": {"line": line, "character": col_start},
            "end": {"line": line, "character": col_end},
        },
        "severity": 2,   # warning — bias toward false negatives
        "source": _IOMMI_DIAG_SOURCE,
        "data": {
            "outcome": problem.outcome,
            "on_class": problem.on_class,
            "available": list(problem.available),
        },
    }
