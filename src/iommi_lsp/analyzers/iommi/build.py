"""``iommi-lsp graph build`` — produce the workspace's iommi graph.

Spawns a subprocess running ``python -m iommi_lsp.analyzers.iommi.reflect``
and captures its JSON output. Defaulting to ``sys.executable`` works when
iommi-lsp is installed in the same venv as iommi (the recommended setup).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ... import log
from .graph import GRAPH_FILENAME, IommiGraph, from_json, save_graph
from .reflect import DEFAULT_SEEDS


_log = log.get("iommi.build")


class GraphBuildError(RuntimeError):
    pass


def build_in_subprocess(
    *,
    python: str | None = None,
    seeds: list[str] | tuple[str, ...] = DEFAULT_SEEDS,
    timeout: float = 60.0,
) -> IommiGraph:
    py = python or sys.executable
    args = [py, "-m", "iommi_lsp.analyzers.iommi.reflect"]
    if seeds and tuple(seeds) != DEFAULT_SEEDS:
        args += ["--seeds", ",".join(seeds)]
    _log.info("running graph builder: %s", " ".join(args))
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise GraphBuildError(f"could not exec {py!r}: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise GraphBuildError(f"graph build timed out after {timeout}s") from e

    if proc.returncode != 0:
        raise GraphBuildError(
            f"graph builder exited {proc.returncode}\nstderr:\n{proc.stderr}"
        )
    try:
        return from_json(proc.stdout)
    except Exception as e:
        raise GraphBuildError(f"could not parse graph output: {e}") from e


def build_for_workspace(
    workspace_root: Path,
    *,
    python: str | None = None,
    seeds: list[str] | tuple[str, ...] = DEFAULT_SEEDS,
) -> Path:
    """Build the graph and write it to ``<workspace>/.iommi-lsp-graph.json``."""
    graph = build_in_subprocess(python=python, seeds=seeds)
    out_path = workspace_root / GRAPH_FILENAME
    save_graph(graph, out_path)
    _log.info(
        "wrote iommi graph: %d classes -> %s (iommi %s)",
        len(graph.classes),
        out_path,
        graph.iommi_version,
    )
    return out_path
