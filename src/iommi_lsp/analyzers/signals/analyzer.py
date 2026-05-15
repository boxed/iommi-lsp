"""Signal-receiver awareness — autocomplete Django models at ``sender=`` kwargs.

Two call shapes:

* ``@receiver(post_save, sender=‸)`` — decorator or plain function call;
* ``signal.connect(handler, sender=‸)`` / ``.disconnect(...)``.

When the cursor sits on the value of a recognised ``sender=`` kwarg, we
contribute model-class completion items. The result is *non-exclusive*
— ty's regular name completion still flows through, so non-model
classes the user might want as senders aren't suppressed.

Also offers known signal-name suggestions for ``signal=`` kwargs on
``connect`` / ``disconnect``: ``post_save``, ``pre_save`` etc. — the
common ``django.db.models.signals.*``.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from ... import log
from ..base import CompletionResult, Diagnostic

if TYPE_CHECKING:
    from ..django.index import DjangoIndex


_log = log.get("signals.analyzer")


# Known builtin Django signals — surface as completion at ``signal=`` /
# the first positional arg of ``@receiver``.
KNOWN_SIGNALS: tuple[str, ...] = (
    "pre_init", "post_init",
    "pre_save", "post_save",
    "pre_delete", "post_delete",
    "m2m_changed",
    "class_prepared",
    "pre_migrate", "post_migrate",
    "request_started", "request_finished",
    "got_request_exception",
    "setting_changed",
    "template_rendered",
)


class SignalsAnalyzer:
    """Implements the :class:`Analyzer` Protocol for ``sender=`` kwargs."""

    name = "signals"

    def __init__(
        self,
        workspace_root: Path,
        text_provider: Callable[[str], str | None] | None = None,
        django_index_provider: "Callable[[], DjangoIndex] | None" = None,
    ) -> None:
        self.workspace_root = workspace_root
        self._text_provider = text_provider
        self._django_index_provider = django_index_provider

    async def index(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    async def on_file_changed(self, uri: str) -> None:
        return None

    def is_false_positive(self, uri: str, diagnostic: Diagnostic) -> bool:
        return False

    def additional_diagnostics(self, uri: str) -> list[Diagnostic]:
        return []

    def completions(self, uri: str, position: dict) -> CompletionResult:
        empty = CompletionResult()
        path = _uri_to_path(uri)
        if path is None:
            return empty
        source = self._source_for(uri, path)
        if source is None:
            return empty
        try:
            return _scan_completions(source, position, self._index())
        except Exception:
            _log.exception("signals completion scanner crashed; emitting nothing")
            return empty

    def _index(self) -> "DjangoIndex | None":
        if self._django_index_provider is None:
            return None
        try:
            return self._django_index_provider()
        except Exception:
            return None

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


# ---------------------------------------------------------------------------
# Completion scan.
# ---------------------------------------------------------------------------


_MARKER = "__iommi_lsp_signals_marker__"


def _scan_completions(
    source: str, position: dict, index: "DjangoIndex | None",
) -> CompletionResult:
    empty = CompletionResult()
    line = int(position.get("line", 0))
    character = int(position.get("character", 0))
    offset = _offset_from_lsp_position(source, line, character)
    if offset > len(source):
        return empty

    # Build up the partial identifier at the cursor (what the user has typed).
    partial_start = offset
    while partial_start > 0 and (
        source[partial_start - 1].isalnum() or source[partial_start - 1] == "_"
    ):
        partial_start -= 1
    partial = source[partial_start:offset]

    # Cheap precondition — signals completion only fires inside a call.
    # The marker either becomes a positional arg (preceded by ``(`` or
    # ``,``) or the value of a kwarg (preceded by ``=``). Anything else
    # — a top-level identifier between imports, attribute access,
    # dictionary keys — can't be ours, and bailing here skips ~12 ms of
    # buffer ast.parse on a 1k-line file.
    if not _is_signal_arg_position(source, partial_start):
        return empty

    head = source[:partial_start]
    inserted = _MARKER
    closes = _close_brackets(head + inserted)
    patched = head + inserted + closes
    # If the result ends as a bare decorator, append a synthetic
    # ``def _():pass`` so the parser is happy.
    if _needs_decorator_body(patched):
        patched += "\ndef __iommi_lsp_sig_body__():\n    pass\n"
    try:
        tree = ast.parse(patched)
    except SyntaxError:
        return empty

    # Find the marker as a Name and inspect its enclosing Call.
    target_call: ast.Call | None = None
    target_kwarg: str | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Positional arg form (first positional of @receiver).
        for i, a in enumerate(node.args):
            if isinstance(a, ast.Name) and a.id == _MARKER:
                target_call = node
                target_kwarg = "<positional:0>" if i == 0 else None
                break
        if target_call is not None:
            break
        for kw in node.keywords:
            if isinstance(kw.value, ast.Name) and kw.value.id == _MARKER:
                target_call = node
                target_kwarg = kw.arg
                break
        if target_call is not None:
            break

    if target_call is None:
        return empty

    callee = _callee_simple_name(target_call.func)

    # ``signal=`` on .connect/.disconnect → suggest signal names.
    if (
        target_kwarg == "signal"
        and callee in {"connect", "disconnect"}
    ):
        items = _signal_items(partial)
        return CompletionResult(items=items, exclusive=False)

    # First positional of ``receiver(post_save, ...)``: signal names.
    if target_kwarg == "<positional:0>" and callee == "receiver":
        items = _signal_items(partial)
        return CompletionResult(items=items, exclusive=False)

    # ``sender=`` on receiver / connect / disconnect → model classes.
    # Exclusive: ty's default expression-position completion at this
    # slot is mostly noise (``False``/``and``/``for``/…) — the popup
    # was being dominated by Python keywords with our models buried
    # below. Users registering custom-class senders (non-Model
    # signals) can still type the class name without completion.
    if target_kwarg == "sender" and callee in {"receiver", "connect", "disconnect"}:
        if index is None:
            return empty
        return CompletionResult(
            items=_model_items(index, partial),
            exclusive=True,
        )

    return empty


def _callee_simple_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _signal_items(partial: str) -> list[dict]:
    out: list[dict] = []
    for name in KNOWN_SIGNALS:
        if partial and not name.startswith(partial):
            continue
        out.append({
            "label": name,
            "kind": 21,   # Constant
            "insertText": name,
            "detail": "django.db.models.signals",
            "data": {"source": "iommi_lsp.signal-name"},
        })
    return out


def _model_items(index: "DjangoIndex", partial: str) -> list[dict]:
    out: list[dict] = []
    for qualname, m in index.models.items():
        if getattr(m, "abstract", False):
            continue
        name = m.name
        if partial and not name.startswith(partial):
            continue
        out.append({
            "label": name,
            "kind": 7,    # Class
            "insertText": name,
            "detail": f"Django model ({qualname})",
            "data": {"source": "iommi_lsp.signal-sender", "model": qualname},
        })
    # Deduplicate by label — multiple modules can host same-named class.
    seen: set[str] = set()
    out_dedup: list[dict] = []
    for item in sorted(out, key=lambda d: d["label"]):
        lab = item["label"]
        if lab in seen:
            continue
        seen.add(lab)
        out_dedup.append(item)
    return out_dedup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uri_to_path(uri: str) -> Path | None:
    if not uri.startswith("file://"):
        return None
    parsed = urlparse(uri)
    return Path(unquote(parsed.path))


def _offset_from_lsp_position(text: str, line: int, character: int) -> int:
    offset = 0
    cur_line = 0
    n = len(text)
    while offset < n and cur_line < line:
        if text[offset] == "\n":
            cur_line += 1
        offset += 1
    char_units = 0
    while offset < n and char_units < character:
        ch = text[offset]
        if ch == "\n":
            break
        char_units += 2 if ord(ch) > 0xFFFF else 1
        offset += 1
    return offset


def _needs_decorator_body(src: str) -> bool:
    """True when the last non-blank line is a decorator without a body."""
    lines = src.rstrip().splitlines()
    if not lines:
        return False
    # Walk backward over blank lines.
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith("@")
    return False


def _is_signal_arg_position(source: str, partial_start: int) -> bool:
    """True if *partial_start* could be a signals-call argument slot.

    Either a fresh positional/kwarg name (``(`` or ``,`` before, possibly
    across whitespace), or the value of a kwarg (``=`` before). Anything
    else can't be a position we recognise — bail before the buffer parse.
    """
    i = partial_start - 1
    while i >= 0 and source[i].isspace():
        i -= 1
    if i < 0:
        return False
    return source[i] in "(,="


def _close_brackets(src: str) -> str:
    stack: list[str] = []
    pair = {"(": ")", "[": "]", "{": "}"}
    in_string: str | None = None
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if in_string is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in '"\'':
            in_string = ch
        elif ch in "([{":
            stack.append(pair[ch])
        elif ch in ")]}":
            if stack and stack[-1] == ch:
                stack.pop()
        elif ch == "#":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        i += 1
    return "".join(reversed(stack))
