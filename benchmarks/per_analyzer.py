"""Per-analyzer breakdown for the big-file ``reverse('re|')`` scenario.

A diagnostic companion to bench.py — same fixture, but instead of timing
the whole _gather pipeline we time each analyzer's completions() call
individually so we can see who's spending the budget.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "benchmarks"))

from bench import (
    _cursor_for,
    _huge_views_py,
    build_matchmaker,
    index_all,
    write_workspace,
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iommi-lsp-bench-") as tmp:
        root = Path(tmp)
        write_workspace(root)
        matchmaker, documents, analyzers = build_matchmaker(root)
        asyncio.run(index_all(analyzers, root))

        text, cur = _cursor_for(
            _huge_views_py("\nrever<CURSOR>\n")
        )
        uri = (root / "myapp/views.py").resolve().as_uri()
        documents.did_open(uri, text)
        position = {"line": cur[0], "character": cur[1]}

        print(f"file size: {len(text)} chars, {text.count(chr(10))} lines")
        print(f"{'analyzer':<14} {'min':>8} {'p50':>8} {'p95':>8} {'max':>8}")
        print("-" * 56)

        for a in analyzers:
            fn = getattr(a, "completions", None)
            if fn is None:
                continue
            for _ in range(20):
                fn(uri, position)
            samples = []
            for _ in range(100):
                t0 = time.perf_counter()
                fn(uri, position)
                t1 = time.perf_counter()
                samples.append((t1 - t0) * 1000.0)
            p95 = (
                statistics.quantiles(samples, n=20)[-1]
                if len(samples) >= 20
                else max(samples)
            )
            print(
                f"{a.name:<14} {min(samples):>8.2f} "
                f"{statistics.median(samples):>8.2f} "
                f"{p95:>8.2f} {max(samples):>8.2f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
