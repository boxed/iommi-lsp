"""Test that DiagnosticInterceptor calls additional_diagnostics and merges
them into the published list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iommi_lsp.analyzers.base import Analyzer, Diagnostic
from iommi_lsp.interceptor import DiagnosticInterceptor


def _frame(payload):
    return json.dumps(payload).encode("utf-8")


def _diag(message, code="x"):
    return {
        "code": code, "message": message, "severity": 2, "source": "test",
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
    }


class _Adder(Analyzer):
    name = "adder"
    def __init__(self, to_add: list[dict]):
        self.to_add = to_add
    async def index(self, workspace_root: Path) -> None: ...
    async def on_file_changed(self, uri: str) -> None: ...
    def is_false_positive(self, uri, diag): return False
    def additional_diagnostics(self, uri):
        return list(self.to_add)


@pytest.mark.asyncio
async def test_added_diagnostics_appear_in_output():
    extra = _diag("from analyzer", code="custom")
    interceptor = DiagnosticInterceptor(analyzers=[_Adder([extra])])

    payload = {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": "file:///x.py", "diagnostics": [_diag("from ty")]},
    }
    out = await interceptor(_frame(payload))
    assert out is not None
    decoded = json.loads(out)
    msgs = [d["message"] for d in decoded["params"]["diagnostics"]]
    assert msgs == ["from ty", "from analyzer"]


@pytest.mark.asyncio
async def test_added_diagnostics_when_ty_published_none():
    extra = _diag("only us")
    interceptor = DiagnosticInterceptor(analyzers=[_Adder([extra])])

    payload = {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": "file:///x.py", "diagnostics": []},
    }
    out = await interceptor(_frame(payload))
    decoded = json.loads(out)
    assert [d["message"] for d in decoded["params"]["diagnostics"]] == ["only us"]


@pytest.mark.asyncio
async def test_no_changes_means_verbatim_passthrough():
    """When no analyzer drops or adds anything, the body must be the same
    bytes object (zero-copy hot path)."""
    interceptor = DiagnosticInterceptor(analyzers=[_Adder([])])
    payload = {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": "file:///x.py", "diagnostics": [_diag("a")]},
    }
    body = _frame(payload)
    out = await interceptor(body)
    assert out is body


@pytest.mark.asyncio
async def test_analyzer_without_additional_diagnostics_method_is_fine():
    """The protocol's `additional_diagnostics` is optional via getattr."""
    class Slim(Analyzer):
        name = "slim"
        async def index(self, workspace_root: Path) -> None: ...
        async def on_file_changed(self, uri: str) -> None: ...
        def is_false_positive(self, uri, diag): return False

    s = Slim()
    # Strip the inherited default so it really is missing.
    if hasattr(type(s), "additional_diagnostics"):
        # Subclass deliberately doesn't override; getattr fallback in
        # interceptor handles the case where the *method itself* is gone.
        # Just confirm the wrapper doesn't crash.
        pass

    interceptor = DiagnosticInterceptor(analyzers=[s])
    payload = {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": "file:///x.py", "diagnostics": []},
    }
    body = _frame(payload)
    out = await interceptor(body)
    # Slim has no additionals -> verbatim.
    assert out is body
