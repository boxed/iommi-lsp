"""Tests for Django auto-generated method suppression.

Covers ``get_<field>_display`` (when a field has ``choices=``) and
``get_next_by_<datefield>`` / ``get_previous_by_<datefield>`` (on
date/datetime fields). These methods are injected by Django's metaclass
and never appear in user source, so ty flags every call to them as an
``unresolved-attribute``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iommi_lsp.analyzers.django import DjangoAnalyzer, build_index
from iommi_lsp.analyzers.django.index import build_index as _build_index


def _diag(line: int, col_start: int, col_end: int, attr: str):
    return {
        "code": "unresolved-attribute",
        "message": f"Type \"…\" has no attribute \"{attr}\"",
        "range": {
            "start": {"line": line, "character": col_start},
            "end": {"line": line, "character": col_end},
        },
        "severity": 1,
        "source": "ty",
    }


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "__init__.py").write_text("")
    (tmp_path / "shop" / "models.py").write_text(
        "from django.db import models\n"
        "\n"
        "class Order(models.Model):\n"
        "    STATUS_CHOICES = [('p', 'Pending'), ('s', 'Sent')]\n"
        "    status = models.CharField(max_length=1, choices=STATUS_CHOICES)\n"
        "    created = models.DateTimeField()\n"
        "    published_on = models.DateField()\n"
        "    title = models.CharField(max_length=100)\n"
    )
    return tmp_path


def test_index_tracks_has_choices(project: Path) -> None:
    idx = _build_index(project)
    [order_qn] = [q for q in idx.models if q.endswith(".Order")]
    order = idx.models[order_qn]
    assert order.fields["status"].has_choices is True
    assert order.fields["title"].has_choices is False


def test_generated_method_names_for_choices(project: Path) -> None:
    idx = _build_index(project)
    [order_qn] = [q for q in idx.models if q.endswith(".Order")]
    order = idx.models[order_qn]
    names = order.generated_method_names
    assert "get_status_display" in names
    # ``title`` has no choices → no get_title_display.
    assert "get_title_display" not in names


def test_generated_method_names_for_dates(project: Path) -> None:
    idx = _build_index(project)
    [order_qn] = [q for q in idx.models if q.endswith(".Order")]
    order = idx.models[order_qn]
    names = order.generated_method_names
    assert "get_next_by_created" in names
    assert "get_previous_by_created" in names
    assert "get_next_by_published_on" in names
    assert "get_previous_by_published_on" in names


def test_get_field_display_is_dropped(project: Path) -> None:
    a = DjangoAnalyzer(workspace_root=project)
    a.django_index = build_index(project)
    src = (
        "from shop.models import Order\n"
        "o = Order.objects.get(pk=1)\n"
        "print(o.get_status_display())\n"
    )
    f = project / "u.py"
    f.write_text(src)
    # Pin the diagnostic to `get_status_display` on line 2.
    line = 2
    col = src.splitlines()[line].index("get_status_display")
    diag = _diag(line, col, col + len("get_status_display"), "get_status_display")
    assert a.is_false_positive(f.as_uri(), diag) is True


def test_get_unknown_display_is_kept(project: Path) -> None:
    a = DjangoAnalyzer(workspace_root=project)
    a.django_index = build_index(project)
    src = (
        "from shop.models import Order\n"
        "o = Order.objects.get(pk=1)\n"
        "print(o.get_nope_display())\n"
    )
    f = project / "u.py"
    f.write_text(src)
    line = 2
    col = src.splitlines()[line].index("get_nope_display")
    diag = _diag(line, col, col + len("get_nope_display"), "get_nope_display")
    # Real typo — keep the diagnostic.
    assert a.is_false_positive(f.as_uri(), diag) is False


def test_get_next_by_date_is_dropped(project: Path) -> None:
    a = DjangoAnalyzer(workspace_root=project)
    a.django_index = build_index(project)
    src = (
        "from shop.models import Order\n"
        "o = Order.objects.get(pk=1)\n"
        "n = o.get_next_by_created()\n"
    )
    f = project / "u.py"
    f.write_text(src)
    line = 2
    col = src.splitlines()[line].index("get_next_by_created")
    diag = _diag(line, col, col + len("get_next_by_created"), "get_next_by_created")
    assert a.is_false_positive(f.as_uri(), diag) is True


def test_get_previous_by_date_is_dropped(project: Path) -> None:
    a = DjangoAnalyzer(workspace_root=project)
    a.django_index = build_index(project)
    src = (
        "from shop.models import Order\n"
        "o = Order.objects.get(pk=1)\n"
        "n = o.get_previous_by_published_on()\n"
    )
    f = project / "u.py"
    f.write_text(src)
    line = 2
    col = src.splitlines()[line].index("get_previous_by_published_on")
    diag = _diag(
        line,
        col,
        col + len("get_previous_by_published_on"),
        "get_previous_by_published_on",
    )
    assert a.is_false_positive(f.as_uri(), diag) is True


def test_get_next_by_non_date_field_is_kept(project: Path) -> None:
    """``status`` is a CharField — there's no get_next_by_status method."""
    a = DjangoAnalyzer(workspace_root=project)
    a.django_index = build_index(project)
    src = (
        "from shop.models import Order\n"
        "o = Order.objects.get(pk=1)\n"
        "n = o.get_next_by_status()\n"
    )
    f = project / "u.py"
    f.write_text(src)
    line = 2
    col = src.splitlines()[line].index("get_next_by_status")
    diag = _diag(line, col, col + len("get_next_by_status"), "get_next_by_status")
    assert a.is_false_positive(f.as_uri(), diag) is False


def test_disabled_generated_rule_keeps_diagnostic(project: Path) -> None:
    from iommi_lsp.config import Config
    a = DjangoAnalyzer(
        workspace_root=project,
        config=Config(disabled_rules=frozenset({"generated"})),
    )
    a.django_index = build_index(project)
    src = (
        "from shop.models import Order\n"
        "o = Order.objects.get(pk=1)\n"
        "print(o.get_status_display())\n"
    )
    f = project / "u.py"
    f.write_text(src)
    line = 2
    col = src.splitlines()[line].index("get_status_display")
    diag = _diag(line, col, col + len("get_status_display"), "get_status_display")
    # Rule disabled → don't drop the diagnostic.
    assert a.is_false_positive(f.as_uri(), diag) is False
