"""Stand-alone repro for ty's completion latency, with no iommi_lsp proxy.

Talks LSP straight to ``ty server`` over stdio so we can attribute slow
typing to ty (or rule it out). Spawns ty, drives an initialize handshake,
opens a Python file, then sends a series of ``textDocument/completion``
requests at the given position and prints each request's elapsed time.

Run against the bundled synthetic workspace to confirm ty works fine on
a small project::

    python benchmarks/ty_direct.py

Then point at the real workspace to repro the slowness::

    python benchmarks/ty_direct.py \\
        --workspace ~/Projects/dryft \\
        --file ~/Projects/dryft/dryft/integrations/fortnox/__init__.py \\
        --position 0,5 \\
        --partial rever

The script writes nothing to the target workspace; it just opens the
file LSP-style. ``--partial`` is the in-progress identifier the user
typed; the cursor offset is computed as position + len(partial).

If you only want to test cold latency, pass ``--requests 1``. The
default is 5 so you can see whether ty caches across requests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path


# ---------------------------------------------------------------------------
# LSP framing — kept inline so the script is genuinely stand-alone.
# ---------------------------------------------------------------------------


def encode(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


async def read_one(reader: asyncio.StreamReader) -> dict | None:
    content_length: int | None = None
    while True:
        line = await reader.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii").rstrip().partition(":")
        if name.strip().lower() == "content-length":
            content_length = int(value.strip())
    if content_length is None:
        return None
    body = await reader.readexactly(content_length)
    return json.loads(body)


# ---------------------------------------------------------------------------
# Synthetic fallback workspace.
# ---------------------------------------------------------------------------


_SYNTHETIC_FILE = "module.py"
_SYNTHETIC_SOURCE = """\
\"\"\"A tiny module so ty has something to chew on.\"\"\"

from typing import Any


def reverse(s: str) -> str:
    return s[::-1]


def reveal(x: Any) -> Any:
    return x
"""


def populate_synthetic(root: Path) -> None:
    (root / _SYNTHETIC_FILE).write_text(_SYNTHETIC_SOURCE)
    (root / "pyproject.toml").write_text('[project]\nname = "ty_direct_demo"\nversion = "0.0.0"\n')


# ---------------------------------------------------------------------------
# LSP client driver.
# ---------------------------------------------------------------------------


class TyDriver:
    """Minimal client that speaks just enough LSP to drive ty's completion."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdin is not None and proc.stdout is not None
        self._proc = proc
        self._stdin = proc.stdin
        self._stdout = proc.stdout
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        # Filled in by :meth:`initialize` so we can answer ty's
        # workspace/workspaceFolders requests during the handshake.
        self._workspace_folders: list[dict] = []
        self._reader_task = asyncio.create_task(self._reader_loop())

    def _alloc_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    async def _reader_loop(self) -> None:
        try:
            while True:
                msg = await read_one(self._stdout)
                if msg is None:
                    return
                # Three shapes from ty:
                #   1. Response to a request we sent (has id, no method).
                #   2. Server-to-client request (has id AND method) — ty
                #      will block waiting for our reply, so we must
                #      answer it. Default to ``result: null`` for any
                #      request we don't specifically know about.
                #   3. Notification (no id) — ignore.
                if "method" in msg and "id" in msg:
                    await self._respond_to_server_request(msg)
                elif "id" in msg and "method" not in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(exc)

    async def _respond_to_server_request(self, request: dict) -> None:
        method = request.get("method")
        msg_id = request["id"]
        # The few that need a non-null answer to keep ty making progress.
        if method == "workspace/configuration":
            # An array, one entry per items[i] the server asked about,
            # each containing the (sub-)settings object. Empty objects
            # are fine for our purposes.
            items = (request.get("params") or {}).get("items") or []
            result: object = [{} for _ in items]
        elif method == "workspace/workspaceFolders":
            result = self._workspace_folders
        else:
            # registerCapability, applyEdit, etc. — null/{} is fine.
            result = None
        self._stdin.write(encode({
            "jsonrpc": "2.0", "id": msg_id, "result": result,
        }))
        await self._stdin.drain()

    async def _request(self, method: str, params: dict) -> dict:
        msg_id = self._alloc_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        self._stdin.write(encode({
            "jsonrpc": "2.0", "id": msg_id, "method": method, "params": params,
        }))
        await self._stdin.drain()
        return await fut

    async def _notify(self, method: str, params: dict | None = None) -> None:
        self._stdin.write(encode({
            "jsonrpc": "2.0", "method": method,
            **({"params": params} if params is not None else {}),
        }))
        await self._stdin.drain()

    async def initialize(self, workspace: Path) -> dict:
        uri = workspace.resolve().as_uri()
        self._workspace_folders = [{"uri": uri, "name": workspace.name}]
        return await self._request("initialize", {
            "processId": None,
            "clientInfo": {"name": "ty_direct_repro", "version": "0.0.0"},
            "rootUri": uri,
            "capabilities": {
                "textDocument": {
                    "completion": {
                        "completionItem": {"snippetSupport": False},
                    },
                },
                "workspace": {
                    "workspaceFolders": True,
                    "configuration": True,
                },
            },
            "workspaceFolders": [{"uri": uri, "name": workspace.name}],
        })

    async def did_open(self, file: Path, text: str) -> None:
        await self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": file.resolve().as_uri(),
                "languageId": "python",
                "version": 1,
                "text": text,
            },
        })

    async def did_change(self, file: Path, version: int, text: str) -> None:
        await self._notify("textDocument/didChange", {
            "textDocument": {"uri": file.resolve().as_uri(), "version": version},
            "contentChanges": [{"text": text}],   # full-document sync
        })

    async def completion(self, file: Path, line: int, character: int) -> tuple[float, dict]:
        start = time.perf_counter()
        response = await self._request("textDocument/completion", {
            "textDocument": {"uri": file.resolve().as_uri()},
            "position": {"line": line, "character": character},
        })
        elapsed = time.perf_counter() - start
        return elapsed, response

    async def shutdown(self) -> None:
        # ``shutdown`` takes no params (LSP defines it as ``void``); ty
        # rejects ``{}`` as invalid. Send without a params key.
        msg_id = self._alloc_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        self._stdin.write(encode({
            "jsonrpc": "2.0", "id": msg_id, "method": "shutdown",
        }))
        try:
            await self._stdin.drain()
            await asyncio.wait_for(fut, timeout=2.0)
        except Exception:
            pass
        try:
            self._stdin.write(encode({"jsonrpc": "2.0", "method": "exit"}))
            await self._stdin.drain()
        except Exception:
            pass
        self._reader_task.cancel()
        try:
            await self._reader_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def _count_items(result) -> int:
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        items = result.get("items")
        if isinstance(items, list):
            return len(items)
    return 0


def _is_incomplete(result) -> bool | None:
    if isinstance(result, dict):
        v = result.get("isIncomplete")
        if isinstance(v, bool):
            return v
    return None


def _resolve_ty_command(arg: str | None) -> list[str]:
    if arg:
        return arg.split()
    # Prefer the ty that ships alongside the installed iommi_lsp tool —
    # that's the one running in the user's editor, so reproducing
    # against the same binary keeps the comparison fair.
    for candidate in (
        Path.home() / ".local/share/uv/tools/iommi-lsp/bin/ty",
        Path(shutil.which("ty", path=str(Path(sys.executable).parent)) or ""),
        Path(shutil.which("ty") or ""),
    ):
        if candidate and candidate.is_file():
            return [str(candidate), "server"]
    return ["ty", "server"]


async def _run(args: argparse.Namespace) -> int:
    if args.workspace is not None:
        workspace = args.workspace.resolve()
        if not workspace.is_dir():
            print(f"error: workspace {workspace} is not a directory", file=sys.stderr)
            return 2
        file_path = args.file.resolve() if args.file else workspace / _SYNTHETIC_FILE
        if not file_path.exists():
            print(f"error: file {file_path} does not exist", file=sys.stderr)
            return 2
        text = file_path.read_text(encoding="utf-8")
        tmp_ctx = None
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="ty-direct-")
        workspace = Path(tmp_ctx.__enter__())
        populate_synthetic(workspace)
        file_path = workspace / _SYNTHETIC_FILE
        text = file_path.read_text(encoding="utf-8")

    ty_cmd = _resolve_ty_command(args.ty_command)
    print(f"ty command : {' '.join(ty_cmd)}")
    print(f"workspace  : {workspace}")
    print(f"file       : {file_path}")
    print(f"position   : line={args.line} char={args.character} partial={args.partial!r}")
    print()

    # Editor-style insertion: the partial is already in the buffer at the
    # cursor — exactly the state when the user has typed it.
    if args.partial:
        text = _insert_partial(text, args.line, args.character, args.partial)
        # Cursor ends up at character + len(partial).
        cursor_char = args.character + len(args.partial)
    else:
        cursor_char = args.character

    proc = await asyncio.create_subprocess_exec(
        *ty_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,
    )
    driver = TyDriver(proc)
    try:
        t0 = time.perf_counter()
        await driver.initialize(workspace)
        await driver._notify("initialized", {})
        await driver.did_open(file_path, text)
        if args.open_extra_glob:
            extras = sorted(workspace.glob(args.open_extra_glob))
            extras = [p for p in extras if p != file_path][: args.open_extra_cap]
            print(f"extras     : opening {len(extras)} additional files via {args.open_extra_glob!r}")
            for p in extras:
                try:
                    extra_text = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                await driver.did_open(p, extra_text)
        print(f"handshake  : {(time.perf_counter() - t0)*1000:.0f} ms")
        # Give ty a beat to start indexing — without this, the first
        # completion sometimes races initialisation and skews high.
        await asyncio.sleep(args.warmup_delay)

        print()
        mode = "didChange-each" if args.simulate_typing else "warm"
        print(f"mode: {mode}")
        print(f"{'#':>3} {'elapsed':>10} {'items':>6} {'isIncomplete'}")
        print("-" * 40)
        version = 1
        # Track the buffer state we'll mutate when --simulate-typing is on.
        live_text = text
        live_partial = args.partial
        live_cursor_char = cursor_char
        for i in range(1, args.requests + 1):
            if args.simulate_typing and i > 1:
                # Pretend the user typed one more character of the
                # identifier (cycle through 'a', 'b', ...). Each
                # didChange invalidates ty's cached analysis for the
                # file, which is the editor's actual pattern.
                extra = chr(ord("a") + ((i - 2) % 26))
                live_partial = live_partial + extra
                live_text = _insert_partial(
                    text, args.line, args.character, live_partial,
                )
                live_cursor_char = args.character + len(live_partial)
                version += 1
                await driver.did_change(file_path, version, live_text)
            elapsed, response = await driver.completion(
                file_path, args.line, live_cursor_char,
            )
            result = response.get("result")
            print(
                f"{i:>3} {elapsed*1000:>8.0f} ms "
                f"{_count_items(result):>6} {_is_incomplete(result)}"
            )
    finally:
        await driver.shutdown()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if tmp_ctx is not None:
            tmp_ctx.__exit__(None, None, None)
    return 0


def _insert_partial(text: str, line: int, character: int, partial: str) -> str:
    """Insert *partial* at (line, character) in *text* and return the result."""
    lines = text.splitlines(keepends=True)
    while len(lines) <= line:
        lines.append("")
    target = lines[line]
    # Strip trailing newline (if any) for character math; reattach at end.
    has_nl = target.endswith("\n")
    body = target.rstrip("\n")
    if character > len(body):
        body = body + " " * (character - len(body))
    new = body[:character] + partial + body[character:]
    lines[line] = new + ("\n" if has_nl else "")
    return "".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ty-command", default=None,
                        help="ty command to spawn (default: bundled `ty server`).")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="Workspace root. Default: a temp dir with a tiny module.")
    parser.add_argument("--file", type=Path, default=None,
                        help="File to open inside the workspace. Default: the synthetic module.")
    parser.add_argument("--line", type=int, default=0,
                        help="LSP line of the cursor base position (0-indexed).")
    parser.add_argument("--character", type=int, default=0,
                        help="LSP character of the cursor base position.")
    parser.add_argument("--partial", default="",
                        help="In-progress identifier to insert at the cursor (e.g. 'rever').")
    parser.add_argument("--requests", type=int, default=5,
                        help="How many back-to-back completion requests to send.")
    parser.add_argument("--warmup-delay", type=float, default=0.5,
                        help="Seconds to wait after initialize before the first request.")
    parser.add_argument("--simulate-typing", action="store_true",
                        help="Send a textDocument/didChange before each completion "
                             "after the first, mimicking the editor's per-keystroke "
                             "pattern. Reveals whether ty's cache survives edits.")
    parser.add_argument("--open-extra-glob", default=None,
                        help="Glob (e.g. 'dryft/**/*.py') of additional files under "
                             "the workspace to didOpen before the test. Simulates an "
                             "editor with many tabs open. Capped at --open-extra-cap.")
    parser.add_argument("--open-extra-cap", type=int, default=200,
                        help="Maximum number of extra files opened via --open-extra-glob.")

    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
