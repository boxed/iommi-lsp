"""``iommi-lsp`` entry point.

Two modes:

* No subcommand (default) — run as the LSP proxy on stdio. Spawns
  ``ty server`` from ``PATH`` unless ``--ty-command`` overrides.
* ``iommi-lsp index <path>`` — build the Django model index for *path*
  and dump it to stdout. A debugging tool for milestone 3.
"""

from __future__ import annotations

import argparse
import asyncio
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, log, proxy
from .analyzers.django import DjangoAnalyzer, build_index
from .analyzers.iommi import IommiAnalyzer
from .analyzers.iommi.build import GraphBuildError, build_for_workspace
from .interceptor import DiagnosticInterceptor, EditorRequestSniffer


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="iommi-lsp",
        description="Wrapper LSP that proxies ty and filters Django/iommi false positives.",
    )
    p.add_argument(
        "--ty-command",
        default="ty server",
        help="Command to spawn the backend type checker (default: %(default)r).",
    )
    p.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Eagerly index the given workspace at startup instead of waiting "
             "for the editor's `initialize` request.",
    )
    p.add_argument(
        "--log-level",
        default=None,
        help="Override the log level (DEBUG, INFO, WARNING, ERROR).",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"iommi-lsp {__version__}",
    )

    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    idx = sub.add_parser(
        "index",
        help="Build and print the Django model index for a workspace.",
    )
    idx.add_argument("path", type=Path, help="Workspace root to scan.")

    graph = sub.add_parser(
        "graph",
        help="Build / inspect the iommi reflection graph.",
    )
    graph_sub = graph.add_subparsers(dest="graph_command", metavar="ACTION")
    g_build = graph_sub.add_parser(
        "build",
        help="Reflect the installed iommi and write .iommi-lsp-graph.json.",
    )
    g_build.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path.cwd(),
        help="Workspace root (default: cwd). Graph is written here.",
    )
    g_build.add_argument(
        "--python",
        default=None,
        help="Python interpreter to invoke (default: this venv's interpreter).",
    )
    g_build.add_argument(
        "--seeds",
        default=None,
        help="Comma-separated list of fully-qualified iommi class seeds. "
             "Defaults to the public iommi exports.",
    )
    return p


def _run_proxy(ty_command_str: str, workspace: Path | None) -> int:
    ty_command = shlex.split(ty_command_str)
    if not ty_command:
        print("error: --ty-command must not be empty", file=sys.stderr)
        return 2

    root = workspace or Path.cwd()
    django_analyzer = DjangoAnalyzer(workspace_root=root)
    iommi_analyzer = IommiAnalyzer(workspace_root=root)
    analyzers = [django_analyzer, iommi_analyzer]

    interceptor = DiagnosticInterceptor(analyzers=analyzers)

    async def workspace_seen(root: Path) -> None:
        for a in analyzers:
            await a.index(root)

    async def file_changed(uri: str) -> None:
        for a in analyzers:
            await a.on_file_changed(uri)

    sniffer = EditorRequestSniffer(
        on_workspace=workspace_seen,
        on_file_changed=file_changed,
    )

    if workspace is not None:
        return asyncio.run(_eager_index_then_serve(
            ty_command, analyzers, workspace, interceptor, sniffer
        ))
    return asyncio.run(proxy.run(
        ty_command,
        editor_to_ty_hook=sniffer,
        ty_to_editor_hook=interceptor,
    ))


async def _eager_index_then_serve(
    ty_command, analyzers, workspace, interceptor, sniffer
) -> int:
    for a in analyzers:
        await a.index(workspace)
    return await proxy.run(
        ty_command,
        editor_to_ty_hook=sniffer,
        ty_to_editor_hook=interceptor,
    )


def _run_graph_build(path: Path, python: str | None, seeds: str | None) -> int:
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    kwargs: dict = {"python": python}
    if seeds:
        kwargs["seeds"] = tuple(s.strip() for s in seeds.split(",") if s.strip())
    try:
        out = build_for_workspace(path, **kwargs)
    except GraphBuildError as e:
        print(f"error: graph build failed: {e}", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    return 0


def _run_index(path: Path) -> int:
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    index = build_index(path)
    print(index.summary())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log.configure(level=args.log_level)

    try:
        if args.command == "index":
            return _run_index(args.path)
        if args.command == "graph":
            if args.graph_command == "build":
                return _run_graph_build(args.path, args.python, args.seeds)
            print("usage: iommi-lsp graph build [path]", file=sys.stderr)
            return 2
        return _run_proxy(args.ty_command, args.workspace)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
