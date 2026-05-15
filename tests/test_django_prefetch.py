"""Tests for ``Prefetch('rel', queryset=...)`` field-path validation.

The walker already handled the string form
``prefetch_related('rel')``; this extends it so the object form's first
positional arg is validated too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iommi_lsp.analyzers.django import DjangoAnalyzer, build_index


CORPUS = Path(__file__).parent / "corpus"


@pytest.fixture
def analyzer() -> DjangoAnalyzer:
    a = DjangoAnalyzer(workspace_root=CORPUS / "basic_django")
    a.django_index = build_index(CORPUS / "basic_django")
    return a


def test_prefetch_known_relation_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from myapp.models import User\n"
        "from django.db.models import Prefetch\n"
        "User.objects.prefetch_related(Prefetch('profile_set'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_prefetch_unknown_relation_warned(analyzer, tmp_path: Path) -> None:
    src = (
        "from myapp.models import User\n"
        "from django.db.models import Prefetch\n"
        "User.objects.prefetch_related(Prefetch('nope'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-orm-lookup" and "nope" in d.get("message", "")
        for d in diags
    )


def test_prefetch_dotted_models_attribute(analyzer, tmp_path: Path) -> None:
    """``models.Prefetch('bad')`` triggers the same as bare ``Prefetch('bad')``."""
    src = (
        "from myapp.models import User\n"
        "from django.db import models\n"
        "User.objects.prefetch_related(models.Prefetch('bogus'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("bogus" in d.get("message", "") for d in diags)


def test_prefetch_traversal(analyzer, tmp_path: Path) -> None:
    """``Prefetch('profile_set__bogus')`` traverses User → Profile."""
    src = (
        "from myapp.models import User\n"
        "from django.db.models import Prefetch\n"
        "User.objects.prefetch_related(Prefetch('profile_set__bogus'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("bogus" in d.get("message", "") for d in diags)
