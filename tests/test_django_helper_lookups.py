"""Tests for ``get_object_or_404`` / ``get_list_or_404`` ORM-lookup support.

Both helpers from ``django.shortcuts`` take a model (or queryset) as the
first positional arg and forward the rest as ``filter()``-style kwargs.
We treat their kwargs identically to ``Model.objects.filter(...)`` for
completion and diagnostics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iommi_lsp.analyzers.django import DjangoAnalyzer, build_index


CORPUS = Path(__file__).parent / "corpus"


def _write_with_cursor(tmp_path: Path, src_before: str, src_after: str = "") -> tuple[str, dict]:
    f = tmp_path / "u.py"
    f.write_text(src_before + src_after)
    line = src_before.count("\n")
    last_nl = src_before.rfind("\n")
    character = len(src_before) - (last_nl + 1)
    return f.as_uri(), {"line": line, "character": character}


def _labels(result) -> list[str]:
    return [it["label"] for it in result.items]


@pytest.fixture
def analyzer() -> DjangoAnalyzer:
    a = DjangoAnalyzer(workspace_root=CORPUS / "basic_django")
    a.django_index = build_index(CORPUS / "basic_django")
    return a


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


def test_get_object_or_404_completion(analyzer, tmp_path: Path) -> None:
    uri, pos = _write_with_cursor(
        tmp_path,
        "from myapp.models import User\n"
        "from django.shortcuts import get_object_or_404\n"
        "get_object_or_404(User, ",
    )
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    assert "email" in labels
    assert "username" in labels
    assert "pk" in labels


def test_get_list_or_404_completion(analyzer, tmp_path: Path) -> None:
    uri, pos = _write_with_cursor(
        tmp_path,
        "from myapp.models import User\n"
        "from django.shortcuts import get_list_or_404\n"
        "get_list_or_404(User, em",
    )
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    assert _labels(result) == ["email"]


def test_get_object_or_404_queryset_completion(analyzer, tmp_path: Path) -> None:
    """First arg is a queryset, not a bare model class."""
    uri, pos = _write_with_cursor(
        tmp_path,
        "from myapp.models import User\n"
        "from django.shortcuts import get_object_or_404\n"
        "get_object_or_404(User.objects.filter(email='x'), us",
    )
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    assert _labels(result) == ["username"]


def test_get_object_or_404_unknown_model_silent(analyzer, tmp_path: Path) -> None:
    uri, pos = _write_with_cursor(
        tmp_path,
        "from django.shortcuts import get_object_or_404\n"
        "get_object_or_404(SomeUnknown, em",
    )
    result = analyzer.completions(uri, pos)
    # No model resolved → silent (let ty have it).
    assert result.items == []
    assert result.exclusive is False


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_get_object_or_404_unknown_field_warned(analyzer, tmp_path: Path) -> None:
    src = (
        "from myapp.models import User\n"
        "from django.shortcuts import get_object_or_404\n"
        "get_object_or_404(User, eemail='x')\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-orm-lookup" and "eemail" in d.get("message", "")
        for d in diags
    )


def test_get_list_or_404_known_field_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from myapp.models import User\n"
        "from django.shortcuts import get_list_or_404\n"
        "get_list_or_404(User, email='x')\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert not [d for d in diags if "email" in d.get("message", "")]


def test_get_object_or_404_traversal_validates(analyzer, tmp_path: Path) -> None:
    """Profile has FK 'user' → User; ``user__bogus`` should warn."""
    src = (
        "from myapp.models import Profile\n"
        "from django.shortcuts import get_object_or_404\n"
        "get_object_or_404(Profile, user__bogus='x')\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("bogus" in d.get("message", "") for d in diags)
