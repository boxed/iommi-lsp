"""Tests for the DefinitionRouter proxy hook pair."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iommi_lsp.analyzers.base import Analyzer
from iommi_lsp.interceptor import DefinitionRouter


class _CaptureWriter:
    """StreamWriter stub: stores framed writes for later inspection."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def write(self, data: bytes) -> None:
        self.buf.extend(data)

    async def drain(self) -> None:
        return None

    def messages(self) -> list[dict]:
        out: list[dict] = []
        view = bytes(self.buf)
        while view:
            header_end = view.find(b"\r\n\r\n")
            if header_end < 0:
                break
            header = view[:header_end].decode("ascii")
            cl = 0
            for line in header.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    cl = int(line.split(":", 1)[1].strip())
            body = view[header_end + 4:header_end + 4 + cl]
            out.append(json.loads(body))
            view = view[header_end + 4 + cl:]
        return out


def _frame(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


class _Resolver(Analyzer):
    """Test analyzer with a pre-baked resolve_definition return value."""

    name = "resolver"

    def __init__(self, location: dict | None) -> None:
        self.location = location
        self.calls: list[tuple[str, dict]] = []

    async def index(self, workspace_root: Path) -> None: ...
    async def on_file_changed(self, uri: str) -> None: ...
    def is_false_positive(self, uri, diag): return False

    def resolve_definition(self, uri: str, position: dict) -> dict | None:
        self.calls.append((uri, position))
        return self.location


@pytest.mark.asyncio
async def test_definition_request_short_circuits_when_resolver_returns_location():
    expected = {
        "uri": "file:///models.py",
        "range": {
            "start": {"line": 5, "character": 4},
            "end": {"line": 5, "character": 10},
        },
    }
    resolver = _Resolver(expected)
    writer = _CaptureWriter()
    router = DefinitionRouter(analyzers=[resolver])
    router.attach_editor_writer(writer)

    req = _frame({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": "file:///u.py"},
            "position": {"line": 3, "character": 7},
        },
    })
    out = await router.on_request(req)
    assert out is None  # dropped — we answered directly
    assert resolver.calls == [("file:///u.py", {"line": 3, "character": 7})]

    msgs = writer.messages()
    assert len(msgs) == 1
    assert msgs[0]["id"] == 11
    assert msgs[0]["result"] == expected


@pytest.mark.asyncio
async def test_definition_request_passes_through_when_no_resolver_claims():
    resolver = _Resolver(None)
    writer = _CaptureWriter()
    router = DefinitionRouter(analyzers=[resolver])
    router.attach_editor_writer(writer)

    req = _frame({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": "file:///u.py"},
            "position": {"line": 1, "character": 0},
        },
    })
    out = await router.on_request(req)
    assert out is req  # forwarded to ty
    assert writer.messages() == []


@pytest.mark.asyncio
async def test_unrelated_methods_pass_through():
    router = DefinitionRouter(analyzers=[_Resolver(None)])
    router.attach_editor_writer(_CaptureWriter())
    body = _frame({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {},
    })
    out = await router.on_request(body)
    assert out is body


@pytest.mark.asyncio
async def test_initialize_response_gets_definition_provider_capability():
    router = DefinitionRouter(analyzers=[])
    init_req = _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    await router.on_request(init_req)

    init_resp = _frame({
        "jsonrpc": "2.0", "id": 1,
        "result": {"capabilities": {"hoverProvider": True}},
    })
    out = await router.on_response(init_resp)
    assert out is not None
    decoded = json.loads(out)
    assert decoded["result"]["capabilities"]["definitionProvider"] is True
    # Existing capabilities preserved.
    assert decoded["result"]["capabilities"]["hoverProvider"] is True


@pytest.mark.asyncio
async def test_initialize_response_left_alone_when_ty_already_offers_definition():
    router = DefinitionRouter(analyzers=[])
    init_req = _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    await router.on_request(init_req)

    init_resp = _frame({
        "jsonrpc": "2.0", "id": 1,
        "result": {"capabilities": {"definitionProvider": {"workDoneProgress": False}}},
    })
    out = await router.on_response(init_resp)
    # Unmodified — original capability shape preserved verbatim.
    assert out == init_resp
