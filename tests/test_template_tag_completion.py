"""Tests for Django template-tag completion + diagnostics in .html files.

Covers ``{% url %}``, ``{% extends %}`` / ``{% include %}``,
``{% block %}``, ``{% load %}``, and ``{% static %}`` tags inside
template files. Also covers the ``django-unknown-url-name`` diagnostic
emitted for ``{% url 'unknown' %}``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.templates import (
    TemplateAnalyzer,
    discover_templatetags,
)
from iommi_lsp.analyzers.urls import UrlAnalyzer


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


def _build_analyzers(tmp_path: Path) -> TemplateAnalyzer:
    url_analyzer = UrlAnalyzer(workspace_root=tmp_path)
    asyncio.run(url_analyzer.index(tmp_path))
    template_analyzer = TemplateAnalyzer(
        workspace_root=tmp_path,
        url_index_provider=lambda: url_analyzer.url_index,
    )
    asyncio.run(template_analyzer.index(tmp_path))
    return template_analyzer


# ---------------------------------------------------------------------------
# discover_templatetags
# ---------------------------------------------------------------------------


def test_discover_templatetags_basic(tmp_path: Path) -> None:
    pkg = tmp_path / "myapp" / "templatetags"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "myapp_extras.py").write_text("# tags\n")
    (pkg / "myapp_filters.py").write_text("# filters\n")
    found = discover_templatetags(tmp_path)
    assert found == {"myapp_extras", "myapp_filters"}


def test_discover_templatetags_skips_dunders_and_dotfiles(tmp_path: Path) -> None:
    pkg = tmp_path / "blog" / "templatetags"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "_helper.py").write_text("# private\n")
    (pkg / ".hidden.py").write_text("# hidden\n")
    (pkg / "blog_tags.py").write_text("")
    assert discover_templatetags(tmp_path) == {"blog_tags"}


def test_discover_templatetags_skips_venv(tmp_path: Path) -> None:
    venv_pkg = tmp_path / ".venv" / "lib" / "x" / "templatetags"
    venv_pkg.mkdir(parents=True)
    (venv_pkg / "leak.py").write_text("")
    real = tmp_path / "app" / "templatetags"
    real.mkdir(parents=True)
    (real / "good.py").write_text("")
    assert discover_templatetags(tmp_path) == {"good"}


def test_discover_templatetags_only_py(tmp_path: Path) -> None:
    pkg = tmp_path / "app" / "templatetags"
    pkg.mkdir(parents=True)
    (pkg / "tags.py").write_text("")
    (pkg / "tags.pyc").write_text("")
    (pkg / "README.md").write_text("")
    assert discover_templatetags(tmp_path) == {"tags"}


# ---------------------------------------------------------------------------
# {% url %} completion
# ---------------------------------------------------------------------------


def _seed_urlconf(tmp_path: Path) -> None:
    (tmp_path / "blog").mkdir()
    (tmp_path / "blog" / "__init__.py").write_text("")
    (tmp_path / "blog" / "urls.py").write_text(
        "from django.urls import path\n"
        "app_name = 'blog'\n"
        "urlpatterns = [\n"
        "    path('', None, name='index'),\n"
        "    path('<int:pk>/', None, name='detail'),\n"
        "]\n"
    )
    (tmp_path / "urls.py").write_text(
        "from django.urls import include, path\n"
        "urlpatterns = [\n"
        "    path('blog/', include('blog.urls')),\n"
        "    path('about/', None, name='about'),\n"
        "]\n"
    )


def test_url_tag_completion_offers_url_names(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "<a href=\"{% url '")
    result = a.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    assert "about" in labels
    assert "blog:index" in labels
    assert "blog:detail" in labels


def test_url_tag_completion_filtered_by_partial(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "<a href=\"{% url 'blog:")
    labels = set(_labels(a.completions(uri, pos)))
    assert labels == {"blog:index", "blog:detail"}


def test_url_tag_completion_replaces_full_partial_via_textedit(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    src = "<a href=\"{% url 'blog:de"
    uri, pos = _write_with_cursor(tpl, src)
    result = a.completions(uri, pos)
    item = next(it for it in result.items if it["label"] == "blog:detail")
    edit = item["textEdit"]
    quote_col = src.index("'")
    assert edit["newText"] == "blog:detail"
    assert edit["range"] == {
        "start": {"line": 0, "character": quote_col + 1},
        "end": {"line": 0, "character": len(src)},
    }


def test_url_tag_completion_double_quote(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, '<a href="{% url "')
    labels = set(_labels(a.completions(uri, pos)))
    assert "about" in labels


def test_url_tag_no_completion_outside_string(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    # Cursor sits between the tag name and the args — no string yet.
    uri, pos = _write_with_cursor(tpl, "{% url ")
    result = a.completions(uri, pos)
    # Inside the tag but not in a string — we have nothing meaningful to
    # offer, but the position is "owned" so we stay exclusive when the
    # url tag is recognised. Just assert empty items.
    assert result.items == []


# ---------------------------------------------------------------------------
# {% url %} diagnostics
# ---------------------------------------------------------------------------


def test_url_tag_diagnostic_for_unknown(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    tpl.write_text("<a href=\"{% url 'noooo' %}\">x</a>\n")
    diags = a.additional_diagnostics(tpl.as_uri())
    assert len(diags) == 1
    d = diags[0]
    assert d["code"] == "django-unknown-url-name"
    assert "noooo" in d["message"]
    # Range should cover just the value 'noooo' (between the quotes).
    rng = d["range"]
    assert rng["start"]["line"] == 0
    line0 = "<a href=\"{% url 'noooo' %}\">x</a>"
    expected_start = line0.index("noooo")
    assert rng["start"]["character"] == expected_start
    assert rng["end"]["character"] == expected_start + len("noooo")


def test_url_tag_diagnostic_silent_for_known(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    tpl.write_text("<a href=\"{% url 'about' %}\">x</a>\n")
    assert a.additional_diagnostics(tpl.as_uri()) == []


def test_url_tag_diagnostic_handles_namespaces(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    tpl.write_text("<a href=\"{% url 'blog:index' %}\">x</a>\n")
    assert a.additional_diagnostics(tpl.as_uri()) == []


def test_url_tag_diagnostic_silent_for_python_files(tmp_path: Path) -> None:
    _seed_urlconf(tmp_path)
    a = _build_analyzers(tmp_path)
    py = tmp_path / "noisy.py"
    py.write_text("# {% url 'noooo' %}\n")
    # .py files go through the URL analyzer's own scanner, not this one.
    assert a.additional_diagnostics(py.as_uri()) == []


# ---------------------------------------------------------------------------
# {% extends %} / {% include %} completion
# ---------------------------------------------------------------------------


def _seed_templates(tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir(parents=True)
    (tmp_path / "templates" / "base.html").write_text(
        "{% block content %}{% endblock %}\n"
        "{% block sidebar %}{% endblock %}\n"
    )
    (tmp_path / "templates" / "_partial.html").write_text("hi\n")
    (tmp_path / "myapp" / "templates" / "myapp").mkdir(parents=True)
    (tmp_path / "myapp" / "templates" / "myapp" / "list.html").write_text("")


def test_extends_completion_offers_template_names(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    uri, pos = _write_with_cursor(tpl, "{% extends '")
    result = a.completions(uri, pos)
    labels = set(_labels(result))
    # No ``/`` heuristic — every template should be offered.
    assert "base.html" in labels
    assert "_partial.html" in labels
    assert "myapp/list.html" in labels


def test_include_completion_offers_template_names(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    uri, pos = _write_with_cursor(tpl, "{% include '")
    labels = set(_labels(a.completions(uri, pos)))
    assert "base.html" in labels
    assert "myapp/list.html" in labels


def test_include_completion_filtered_by_partial(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    uri, pos = _write_with_cursor(tpl, "{% include 'myapp/")
    labels = set(_labels(a.completions(uri, pos)))
    assert labels == {"myapp/list.html"}


# ---------------------------------------------------------------------------
# {% block %} completion in child templates
# ---------------------------------------------------------------------------


def test_block_completion_offers_parent_block_names(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    src = (
        "{% extends 'base.html' %}\n"
        "{% block "
    )
    uri, pos = _write_with_cursor(tpl, src)
    result = a.completions(uri, pos)
    labels = set(_labels(result))
    assert labels == {"content", "sidebar"}


def test_block_completion_filtered_by_partial(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    src = (
        "{% extends 'base.html' %}\n"
        "{% block sid"
    )
    uri, pos = _write_with_cursor(tpl, src)
    result = a.completions(uri, pos)
    labels = set(_labels(result))
    assert labels == {"sidebar"}


def test_block_completion_replaces_partial_via_textedit(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    src = (
        "{% extends 'base.html' %}\n"
        "{% block sid"
    )
    uri, pos = _write_with_cursor(tpl, src)
    result = a.completions(uri, pos)
    item = next(it for it in result.items if it["label"] == "sidebar")
    edit = item["textEdit"]
    assert edit["newText"] == "sidebar"
    # Replacement covers from start of "sid" to end of partial.
    assert edit["range"]["start"]["line"] == 1
    assert edit["range"]["end"]["line"] == 1
    line2 = "{% block sid"
    expected_start = line2.index("sid")
    assert edit["range"]["start"]["character"] == expected_start
    assert edit["range"]["end"]["character"] == expected_start + len("sid")


def test_block_completion_no_extends_returns_exclusive_empty(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    uri, pos = _write_with_cursor(tpl, "{% block ")
    result = a.completions(uri, pos)
    assert result.items == []
    # We claim the position so ty's noise doesn't backfill.
    assert result.exclusive is True


def test_block_completion_recurses_into_grandparent(tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "root.html").write_text(
        "{% block header %}{% endblock %}\n"
    )
    (tmp_path / "templates" / "mid.html").write_text(
        "{% extends 'root.html' %}\n"
        "{% block midway %}{% endblock %}\n"
    )
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "child.html"
    uri, pos = _write_with_cursor(
        tpl,
        "{% extends 'mid.html' %}\n"
        "{% block ",
    )
    labels = set(_labels(a.completions(uri, pos)))
    # Should include both midway (parent) and header (grandparent).
    assert "midway" in labels
    assert "header" in labels


# ---------------------------------------------------------------------------
# {% load %} completion
# ---------------------------------------------------------------------------


def test_load_completion_offers_templatetags(tmp_path: Path) -> None:
    pkg = tmp_path / "app" / "templatetags"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "app_extras.py").write_text("")
    (pkg / "app_filters.py").write_text("")
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "{% load ")
    result = a.completions(uri, pos)
    labels = set(_labels(result))
    assert labels == {"app_extras", "app_filters"}


def test_load_completion_filtered_by_partial(tmp_path: Path) -> None:
    pkg = tmp_path / "app" / "templatetags"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "app_extras.py").write_text("")
    (pkg / "app_filters.py").write_text("")
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "{% load app_ext")
    labels = set(_labels(a.completions(uri, pos)))
    assert labels == {"app_extras"}


# ---------------------------------------------------------------------------
# {% static %} completion
# ---------------------------------------------------------------------------


def test_static_tag_completion_offers_static_files(tmp_path: Path) -> None:
    sd = tmp_path / "app" / "static" / "app"
    sd.mkdir(parents=True)
    (sd / "style.css").write_text("")
    (sd / "logo.png").write_text("")
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "<link href=\"{% static '")
    result = a.completions(uri, pos)
    labels = set(_labels(result))
    assert labels == {"app/style.css", "app/logo.png"}


def test_static_tag_completion_filtered_by_partial(tmp_path: Path) -> None:
    sd = tmp_path / "app" / "static" / "app"
    sd.mkdir(parents=True)
    (sd / "style.css").write_text("")
    (sd / "logo.png").write_text("")
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "<link href=\"{% static 'app/sty")
    labels = set(_labels(a.completions(uri, pos)))
    assert labels == {"app/style.css"}


# ---------------------------------------------------------------------------
# Sanity: outside any tag → no completions
# ---------------------------------------------------------------------------


def test_no_completions_outside_tag(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    uri, pos = _write_with_cursor(tpl, "<p>plain text 'foo' content</p>")
    result = a.completions(uri, pos)
    assert result.items == []
    assert result.exclusive is False


def test_no_completions_after_closing_tag(tmp_path: Path) -> None:
    _seed_templates(tmp_path)
    a = _build_analyzers(tmp_path)
    tpl = tmp_path / "page.html"
    src = "{% url 'about' %}<a href='"
    uri, pos = _write_with_cursor(tpl, src)
    result = a.completions(uri, pos)
    assert result.items == []
