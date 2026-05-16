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


# ---------------------------------------------------------------------------
# Nested Subquery: F() inside the inner queryset must validate against the
# inner model, not the outer .annotate() receiver. Regression for a real
# bug where ``.annotate(x=Subquery(Slot.objects...annotate(total=Sum(
# F('minutes') - F('overlap_minutes')))...))`` flagged ``minutes`` and
# ``overlap_minutes`` as unknown on the outer ``Project`` model.
# ---------------------------------------------------------------------------


def _build_nested_subquery_workspace(tmp_path: Path) -> DjangoAnalyzer:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "models.py").write_text(
        "from django.db import models\n"
        "class Project(models.Model):\n"
        "    project_number = models.IntegerField()\n"
        "    start_date = models.DateField(null=True)\n"
        "    end_date = models.DateField(null=True)\n"
        "class Slot(models.Model):\n"
        "    project = models.ForeignKey(Project, on_delete=models.CASCADE)\n"
        "    date = models.DateField()\n"
        "    minutes = models.IntegerField()\n"
        "    overlap_minutes = models.IntegerField()\n"
    )
    a = DjangoAnalyzer(workspace_root=tmp_path)
    a.django_index = build_index(tmp_path)
    return a


def test_nested_subquery_f_validates_against_inner_model(tmp_path: Path) -> None:
    """``F('minutes')`` inside a Subquery whose queryset is rooted at
    ``Slot`` must validate against Slot, not the outer Project."""
    a = _build_nested_subquery_workspace(tmp_path)
    src = (
        "from django.db.models import F, OuterRef, Subquery, Sum\n"
        "from app.models import Project, Slot\n"
        "Project.objects.annotate(\n"
        "    total_minutes=Subquery(\n"
        "        Slot.objects.filter(project=OuterRef('pk'))\n"
        "        .values('project')\n"
        "        .annotate(total=Sum(F('minutes') - F('overlap_minutes')))\n"
        "        .values('total')[:1],\n"
        "    ),\n"
        ")\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = a.additional_diagnostics(f.as_uri())
    # ``minutes`` and ``overlap_minutes`` are valid on Slot. The outer
    # .annotate() context must not flag them against Project.
    bad = [d for d in diags if "Project" in d.get("message", "") and (
        "minutes" in d.get("message", "")
    )]
    assert not bad, [d["message"] for d in diags]


def test_nested_subquery_inner_f_unknown_still_flagged(tmp_path: Path) -> None:
    """The inner queryset is still validated — F('bogus') against Slot
    is still flagged, just attributed to Slot rather than Project."""
    a = _build_nested_subquery_workspace(tmp_path)
    src = (
        "from django.db.models import F, OuterRef, Subquery, Sum\n"
        "from app.models import Project, Slot\n"
        "Project.objects.annotate(\n"
        "    total=Subquery(\n"
        "        Slot.objects.filter(project=OuterRef('pk'))\n"
        "        .annotate(total=Sum(F('bogus_field')))\n"
        "        .values('total')[:1],\n"
        "    ),\n"
        ")\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = a.additional_diagnostics(f.as_uri())
    msgs = [d.get("message", "") for d in diags]
    assert any("bogus_field" in m and "Slot" in m for m in msgs), msgs


def test_outer_f_still_validates_against_outer_model(tmp_path: Path) -> None:
    """Sanity: F() at the outer .annotate() level still validates against
    the outer (Project) model. The fix should not regress this."""
    a = _build_nested_subquery_workspace(tmp_path)
    src = (
        "from django.db.models import F\n"
        "from app.models import Project\n"
        "Project.objects.annotate(x=F('not_on_project'))\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    diags = a.additional_diagnostics(f.as_uri())
    msgs = [d.get("message", "") for d in diags]
    assert any("not_on_project" in m and "Project" in m for m in msgs), msgs
