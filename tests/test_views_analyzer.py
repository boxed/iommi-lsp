"""Tests for ViewsAnalyzer — class-based view class-attr awareness."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.django import build_index
from iommi_lsp.analyzers.views import ViewsAnalyzer


CORPUS = Path(__file__).parent / "corpus"


def _write_with_cursor(
    tmp_path: Path, src_before: str, src_after: str = "",
) -> tuple[str, dict]:
    f = tmp_path / "views.py"
    f.write_text(src_before + src_after)
    line = src_before.count("\n")
    last_nl = src_before.rfind("\n")
    character = len(src_before) - (last_nl + 1)
    return f.as_uri(), {"line": line, "character": character}


def _labels(result) -> list[str]:
    return [it["label"] for it in result.items]


@pytest.fixture
def analyzer() -> ViewsAnalyzer:
    index = build_index(CORPUS / "basic_django")
    a = ViewsAnalyzer(
        workspace_root=CORPUS / "basic_django",
        django_index_provider=lambda: index,
    )
    asyncio.run(a.index(CORPUS / "basic_django"))
    return a


def test_completion_fields(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import UpdateView\n"
        "from myapp.models import User\n"
        "\n"
        "class UserUpdate(UpdateView):\n"
        "    model = User\n"
        "    fields = ['"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    assert "username" in labels
    assert "email" in labels


def test_completion_ordering_dash_prefix(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import ListView\n"
        "from myapp.models import User\n"
        "\n"
        "class UserList(ListView):\n"
        "    model = User\n"
        "    ordering = ['-em"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["email"]


def test_completion_slug_field_scalar(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import DetailView\n"
        "from myapp.models import User\n"
        "\n"
        "class UserDetail(DetailView):\n"
        "    model = User\n"
        "    slug_field = '"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert "username" in _labels(result)


def test_diagnostic_unknown_field(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import UpdateView\n"
        "from myapp.models import User\n"
        "\n"
        "class UserUpdate(UpdateView):\n"
        "    model = User\n"
        "    fields = ['email', 'eemail']\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-view-field"
        and "eemail" in d.get("message", "")
        for d in diags
    )


def test_diagnostic_known_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import UpdateView\n"
        "from myapp.models import User\n"
        "\n"
        "class UserUpdate(UpdateView):\n"
        "    model = User\n"
        "    fields = ['email', 'username']\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_ordering_strip_dash(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import ListView\n"
        "from myapp.models import User\n"
        "\n"
        "class UserList(ListView):\n"
        "    model = User\n"
        "    ordering = ['-eemail']\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("eemail" in d.get("message", "") for d in diags)


def test_diagnostic_no_model_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import ListView\n"
        "class FooList(ListView):\n"
        "    fields = ['anything']\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_non_cbv_class_ignored(analyzer, tmp_path: Path) -> None:
    src = (
        "class NotAView:\n"
        "    fields = ['eemail']\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []
