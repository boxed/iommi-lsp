"""Tests for staticfiles completion in the TemplateAnalyzer.

The template analyzer was extended to also discover ``static/`` files
under workspace apps and offer them inside ``static('...')`` calls. The
``/`` heuristic from template-name completion does not apply here — the
callee identifier already pins us to a static-file context.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.templates import TemplateAnalyzer
from iommi_lsp.analyzers.templates.analyzer import discover_statics


def _write_with_cursor(
    tmp_path: Path, src_before: str, src_after: str = "",
) -> tuple[str, dict]:
    f = tmp_path / "u.py"
    f.write_text(src_before + src_after)
    line = src_before.count("\n")
    last_nl = src_before.rfind("\n")
    character = len(src_before) - (last_nl + 1)
    return f.as_uri(), {"line": line, "character": character}


def _labels(result) -> list[str]:
    return [it["label"] for it in result.items]


@pytest.fixture
def analyzer(tmp_path: Path) -> TemplateAnalyzer:
    (tmp_path / "myapp" / "static" / "myapp").mkdir(parents=True)
    (tmp_path / "myapp" / "static" / "myapp" / "style.css").write_text("")
    (tmp_path / "myapp" / "static" / "myapp" / "logo.png").write_text("")
    a = TemplateAnalyzer(workspace_root=tmp_path)
    asyncio.run(a.index(tmp_path))
    return a


def test_discover_statics(tmp_path: Path) -> None:
    (tmp_path / "app" / "static").mkdir(parents=True)
    (tmp_path / "app" / "static" / "foo.css").write_text("")
    (tmp_path / "app" / "static" / "bar.js").write_text("")
    assert discover_statics(tmp_path) == {"foo.css", "bar.js"}


def test_discover_statics_skips_venv(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "lib" / "static").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "static" / "bad.css").write_text("")
    (tmp_path / "real" / "static").mkdir(parents=True)
    (tmp_path / "real" / "static" / "good.css").write_text("")
    assert discover_statics(tmp_path) == {"good.css"}


def test_static_call_completion(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.templatetags.static import static\n"
        "url = static('"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    assert "myapp/style.css" in labels
    assert "myapp/logo.png" in labels


def test_static_partial_filters(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.templatetags.static import static\n"
        "url = static('myapp/sty"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["myapp/style.css"]


def test_static_call_no_slash_still_completes(analyzer, tmp_path: Path) -> None:
    """Unlike templates, ``static(...)`` completion triggers without a slash."""
    src = (
        "from django.templatetags.static import static\n"
        "url = static('"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    # Just ``'`` typed — staticfiles list shows up anyway.
    assert result.items, "expected static-file completions even without a slash"


def test_template_completion_still_works(analyzer, tmp_path: Path) -> None:
    """Pre-existing template-name behaviour is unaffected."""
    (tmp_path / "myapp" / "templates" / "myapp").mkdir(parents=True)
    (tmp_path / "myapp" / "templates" / "myapp" / "index.html").write_text("")
    # Re-index with the new templates directory.
    asyncio.run(analyzer.index(tmp_path))
    src = "x = 'myapp/in"
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["myapp/index.html"]
