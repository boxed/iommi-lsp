"""Tests for ``F`` / ``Count`` / ``Sum`` / ``OuterRef`` field-path validation.

The walker already handled ``F('field__path')``; we extend the matcher
to cover the rest of the ``django.db.models`` aggregate/expression set
(``Count``, ``Sum``, ``Avg``, ``Min``, ``Max``, ``StdDev``, ``Variance``,
``OuterRef``, ``Subquery``).

We also wire ``annotate`` / ``aggregate`` / ``alias`` into the call-shape
list so inner aggregate calls get walked even though the kwarg *names*
on these methods are user-defined aliases (not field names).
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


# ---------------------------------------------------------------------------
# Count/Sum/etc. inside annotate()
# ---------------------------------------------------------------------------


def test_count_inside_annotate_unknown_field_warned(analyzer, tmp_path: Path) -> None:
    src = (
        "from myapp.models import User\n"
        "from django.db.models import Count\n"
        "User.objects.annotate(n=Count('eemail'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-orm-lookup" and "eemail" in d.get("message", "")
        for d in diags
    )


def test_sum_inside_aggregate_known_field_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from myapp.models import User\n"
        "from django.db.models import Sum\n"
        "User.objects.aggregate(total=Sum('email'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert not [d for d in diags if "email" in d.get("message", "")]


def test_outer_ref_path_validated(analyzer, tmp_path: Path) -> None:
    src = (
        "from myapp.models import User\n"
        "from django.db.models import OuterRef, Subquery\n"
        "User.objects.filter(email=OuterRef('eemail'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("eemail" in d.get("message", "") for d in diags)


def test_count_dotted_models_attribute(analyzer, tmp_path: Path) -> None:
    """``models.Count('bad')`` should be detected just like ``Count('bad')``."""
    src = (
        "from myapp.models import User\n"
        "from django.db import models\n"
        "User.objects.annotate(n=models.Count('nope_field'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("nope_field" in d.get("message", "") for d in diags)


def test_min_max_traversal(analyzer, tmp_path: Path) -> None:
    """``Max('profile_set__bogus')`` traverses the reverse rel to Profile."""
    src = (
        "from myapp.models import User\n"
        "from django.db.models import Max\n"
        "User.objects.aggregate(m=Max('profile_set__bogus'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("bogus" in d.get("message", "") for d in diags)


def test_annotate_alias_kwarg_not_validated_as_field(analyzer, tmp_path: Path) -> None:
    """``annotate(my_alias=Count(...))`` — ``my_alias`` is NOT a field name.

    We only validate F/Count/etc. *values*, never the kwarg names on
    annotate/aggregate/alias — those are user-defined.
    """
    src = (
        "from myapp.models import User\n"
        "from django.db.models import Count\n"
        "User.objects.annotate(my_alias=Count('email'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert not [d for d in diags if "my_alias" in d.get("message", "")]
