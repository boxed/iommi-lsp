"""Tests for Django template *filter* completion.

Built-in filters from ``django.template.defaultfilters`` are always
offered (no ``{% load %}`` needed). Custom filters discovered in any
``templatetags/*.py`` are offered when their library is referenced via
``{% load <library> %}`` in the same file.

Trigger position: identifier whose immediately-preceding non-identifier
character is ``|``, inside ``{{ … }}`` or ``{% … %}``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.templates import (
    BUILTIN_FILTERS,
    TemplateAnalyzer,
    discover_templatetag_filters,
)


def _write_with_cursor(
    path: Path, src_before: str, src_after: str = "",
) -> tuple[str, dict]:
    path.write_text(src_before + src_after)
    line = src_before.count("\n")
    last_nl = src_before.rfind("\n")
    character = len(src_before) - (last_nl + 1)
    return path.as_uri(), {"line": line, "character": character}


def _labels(result) -> list[str]:
    return [it["label"] for it in result.items]


def _seed_filter_lib(tmp_path: Path, lib: str = "myapp_extras") -> None:
    pkg = tmp_path / "myapp" / "templatetags"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / f"{lib}.py").write_text(
        "from django import template\n"
        "register = template.Library()\n"
        "\n"
        "@register.filter\n"
        "def shout(value):\n"
        "    return value.upper()\n"
        "\n"
        "@register.filter()\n"
        "def whisper(value):\n"
        "    return value.lower()\n"
        "\n"
        "@register.filter(name='renamed')\n"
        "def actually_named_differently(value):\n"
        "    return value\n"
        "\n"
        "@register.filter('positional_name')\n"
        "def positional(value):\n"
        "    return value\n"
        "\n"
        "def reverse_filter(value):\n"
        "    return value[::-1]\n"
        "\n"
        "register.filter('reverse', reverse_filter)\n"
        "\n"
        "@register.simple_tag\n"
        "def some_tag():\n"
        "    return ''\n"
    )


@pytest.fixture
def analyzer(tmp_path: Path) -> TemplateAnalyzer:
    _seed_filter_lib(tmp_path)
    a = TemplateAnalyzer(workspace_root=tmp_path)
    asyncio.run(a.index(tmp_path))
    return a


# ---------------------------------------------------------------------------
# discover_templatetag_filters
# ---------------------------------------------------------------------------


def test_discover_filters_picks_up_decorator_forms(tmp_path: Path) -> None:
    _seed_filter_lib(tmp_path)
    found = discover_templatetag_filters(tmp_path)
    assert "myapp_extras" in found
    names = found["myapp_extras"]
    # Bare @register.filter — function name.
    assert "shout" in names
    # @register.filter() — function name.
    assert "whisper" in names
    # @register.filter(name='renamed').
    assert "renamed" in names
    assert "actually_named_differently" not in names
    # @register.filter('positional_name').
    assert "positional_name" in names
    # register.filter('reverse', fn) direct call.
    assert "reverse" in names
    # @register.simple_tag is a tag, not a filter.
    assert "some_tag" not in names


def test_discover_filters_skips_libraries_with_none(tmp_path: Path) -> None:
    pkg = tmp_path / "app" / "templatetags"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "tags_only.py").write_text(
        "from django import template\n"
        "register = template.Library()\n"
        "@register.simple_tag\n"
        "def t():\n"
        "    return ''\n"
    )
    found = discover_templatetag_filters(tmp_path)
    assert found == {}


def test_discover_filters_handles_syntax_errors(tmp_path: Path) -> None:
    pkg = tmp_path / "app" / "templatetags"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "broken.py").write_text("def oops(\n")   # syntax error
    (pkg / "good.py").write_text(
        "from django import template\n"
        "register = template.Library()\n"
        "@register.filter\n"
        "def works(value):\n"
        "    return value\n"
    )
    found = discover_templatetag_filters(tmp_path)
    assert found == {"good": {"works"}}


def test_indexed_libraries_include_filter_only_modules(tmp_path: Path) -> None:
    """Even if a templatetags library has no plain ``.py`` discovery
    hits, anything that registered a filter gets surfaced through
    ``templatetags`` so ``{% load %}`` completion stays consistent."""
    _seed_filter_lib(tmp_path, lib="filter_only")
    a = TemplateAnalyzer(workspace_root=tmp_path)
    asyncio.run(a.index(tmp_path))
    assert "filter_only" in a.templatetags


# ---------------------------------------------------------------------------
# Built-in filters
# ---------------------------------------------------------------------------


def test_builtin_filter_completion_in_variable_expr(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "{{ name|")
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    # Some representative built-ins should be there.
    assert "upper" in labels
    assert "lower" in labels
    assert "length" in labels
    assert "default" in labels


def test_builtin_filter_completion_filtered_by_partial(
    analyzer, tmp_path: Path,
) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "{{ x|trun")
    labels = set(_labels(analyzer.completions(uri, pos)))
    # Every "trun…" filter; nothing else.
    assert labels == {
        "truncatechars", "truncatechars_html",
        "truncatewords", "truncatewords_html",
    }


def test_filter_completion_textedit_replaces_partial(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    src = "{{ x|tr"
    uri, pos = _write_with_cursor(tpl, src)
    result = analyzer.completions(uri, pos)
    item = next(it for it in result.items if it["label"] == "truncatewords")
    edit = item["textEdit"]
    assert edit["newText"] == "truncatewords"
    pipe_col = src.index("|") + 1
    assert edit["range"] == {
        "start": {"line": 0, "character": pipe_col},
        "end": {"line": 0, "character": len(src)},
    }


def test_filter_completion_chained_pipes(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "{{ x|upper|le")
    labels = set(_labels(analyzer.completions(uri, pos)))
    assert "length" in labels
    assert "length_is" in labels


def test_filter_completion_in_if_tag(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "{% if x|de")
    labels = set(_labels(analyzer.completions(uri, pos)))
    assert "default" in labels
    assert "default_if_none" in labels


# ---------------------------------------------------------------------------
# Custom filters from {% load %}
# ---------------------------------------------------------------------------


def test_custom_filter_only_offered_when_loaded(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    # Without a {% load %}, no custom filters.
    uri, pos = _write_with_cursor(tpl, "{{ x|")
    labels_unloaded = set(_labels(analyzer.completions(uri, pos)))
    assert "shout" not in labels_unloaded
    assert "whisper" not in labels_unloaded
    # Built-ins still there.
    assert "upper" in labels_unloaded


def test_custom_filter_offered_after_load(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(
        tpl,
        "{% load myapp_extras %}\n"
        "{{ x|",
    )
    labels = set(_labels(analyzer.completions(uri, pos)))
    assert {"shout", "whisper", "renamed", "positional_name", "reverse"} <= labels
    # Built-ins still there too.
    assert "upper" in labels


def test_custom_filter_marked_as_custom(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(
        tpl,
        "{% load myapp_extras %}\n"
        "{{ x|sho",
    )
    items = analyzer.completions(uri, pos).items
    item = next(it for it in items if it["label"] == "shout")
    # Built-ins use plain "filter"; library-defined are tagged "custom".
    assert item["detail"] == "filter (custom)"


def test_load_from_form_still_loads_library(tmp_path: Path) -> None:
    _seed_filter_lib(tmp_path, lib="bag")
    a = TemplateAnalyzer(workspace_root=tmp_path)
    asyncio.run(a.index(tmp_path))
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(
        tpl,
        "{% load shout from bag %}\n"
        "{{ x|sho",
    )
    labels = set(_labels(a.completions(uri, pos)))
    assert "shout" in labels


# ---------------------------------------------------------------------------
# Negative / boundary cases
# ---------------------------------------------------------------------------


def test_no_filter_completion_outside_expression(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "<p>x|up")
    result = analyzer.completions(uri, pos)
    assert result.items == []
    assert result.exclusive is False


def test_no_filter_completion_in_string_arg(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    # Pipe inside a string arg of ``default:"…|…"`` is not a filter
    # boundary — bail out.
    uri, pos = _write_with_cursor(tpl, "{{ x|default:\"|fa")
    result = analyzer.completions(uri, pos)
    # The cursor sits inside a string; we have nothing to offer here.
    assert result.items == []


def test_no_filter_completion_without_pipe(analyzer, tmp_path: Path) -> None:
    tpl = tmp_path / "page.html"
    # Inside a variable expression but no pipe yet — variable name
    # completion isn't our job.
    uri, pos = _write_with_cursor(tpl, "{{ na")
    result = analyzer.completions(uri, pos)
    assert result.items == []
    # We do "own" the position because we're inside ``{{ … }}`` and the
    # template-tag dispatcher returns empty (non-exclusive) here too.
    assert result.exclusive is False


def test_filter_completion_zero_width_partial_after_pipe(
    analyzer, tmp_path: Path,
) -> None:
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "{{ x|")
    result = analyzer.completions(uri, pos)
    # Every built-in should be offered; partial is empty so no filtering.
    labels = set(_labels(result))
    assert BUILTIN_FILTERS <= labels


def test_filter_completion_works_in_python_source_unchanged(tmp_path: Path) -> None:
    """The filter scanner is HTML-only — Python files are unaffected."""
    _seed_filter_lib(tmp_path)
    a = TemplateAnalyzer(workspace_root=tmp_path)
    asyncio.run(a.index(tmp_path))
    py = tmp_path / "u.py"
    uri, pos = _write_with_cursor(py, "x = 'foo|up")
    result = a.completions(uri, pos)
    # Python-side completion is governed by the slash-heuristic; "|"
    # isn't in the partial logic at all.
    labels = set(_labels(result))
    assert "upper" not in labels
