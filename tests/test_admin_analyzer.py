"""Tests for AdminAnalyzer — ModelAdmin field validation + completion."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.admin import AdminAnalyzer
from iommi_lsp.analyzers.django import build_index


CORPUS = Path(__file__).parent / "corpus"


def _write_with_cursor(
    tmp_path: Path, src_before: str, src_after: str = "",
    filename: str = "admin.py",
) -> tuple[str, dict]:
    f = tmp_path / filename
    f.write_text(src_before + src_after)
    line = src_before.count("\n")
    last_nl = src_before.rfind("\n")
    character = len(src_before) - (last_nl + 1)
    return f.as_uri(), {"line": line, "character": character}


def _labels(result) -> list[str]:
    return [it["label"] for it in result.items]


@pytest.fixture
def analyzer() -> AdminAnalyzer:
    index = build_index(CORPUS / "basic_django")
    a = AdminAnalyzer(
        workspace_root=CORPUS / "basic_django",
        django_index_provider=lambda: index,
    )
    asyncio.run(a.index(CORPUS / "basic_django"))
    return a


# ---------------------------------------------------------------------------
# @admin.register(Model)
# ---------------------------------------------------------------------------


def test_completion_inside_list_display(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    list_display = ('"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    assert "username" in labels
    assert "email" in labels
    assert "pk" in labels


def test_completion_inside_list_display_partial(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    list_display = ('em"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["email"]


def test_completion_inside_search_fields_with_prefix(
    analyzer, tmp_path: Path,
) -> None:
    """``search_fields = ('=em'` — the ``=`` prefix is stripped."""
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    search_fields = ('=em"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["email"]


def test_completion_ordering_dash_prefix(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    ordering = ('-em"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["email"]


def test_completion_outside_admin_class_silent(
    analyzer, tmp_path: Path,
) -> None:
    src = "x = '"
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.items == []
    assert result.exclusive is False


# ---------------------------------------------------------------------------
# admin.site.register(Model, AdminClass)
# ---------------------------------------------------------------------------


def test_completion_with_site_register(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    list_display = ('em"
    )
    suffix = ",)\n\nadmin.site.register(User, UserAdmin)\n"
    uri, pos = _write_with_cursor(tmp_path, src, suffix)
    result = analyzer.completions(uri, pos)
    assert "email" in _labels(result)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_diagnostic_unknown_field(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    list_display = ('username', 'eemail')\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-admin-field"
        and "eemail" in d.get("message", "")
        for d in diags
    )


def test_diagnostic_known_field_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    list_display = ('username', 'email')\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_search_fields_with_prefix(analyzer, tmp_path: Path) -> None:
    """Prefix sigils are stripped before validation."""
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    search_fields = ('=email', '^username', '@eemail')\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("eemail" in d.get("message", "") for d in diags)
    # ``=email`` and ``^username`` validate fine.
    assert not any(
        "email" in d.get("message", "") and "eemail" not in d.get("message", "")
        for d in diags
    )


def test_diagnostic_admin_method_name_silent(analyzer, tmp_path: Path) -> None:
    """``list_display`` can reference a method on the admin class itself."""
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    list_display = ('username', 'colored_name')\n"
        "    def colored_name(self, obj):\n"
        "        return obj.username\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_fieldsets(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    fieldsets = [\n"
        "        ('Info', {'fields': ('username', 'eemail')}),\n"
        "    ]\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("eemail" in d.get("message", "") for d in diags)


def test_diagnostic_date_hierarchy(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    date_hierarchy = 'eemail'\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("eemail" in d.get("message", "") for d in diags)


def test_diagnostic_prepopulated_fields(analyzer, tmp_path: Path) -> None:
    """Both dict keys and values are field names."""
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import User\n"
        "\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    prepopulated_fields = {'eemail': ('username',)}\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("eemail" in d.get("message", "") for d in diags)


def test_diagnostic_no_index_silent(tmp_path: Path) -> None:
    """No Django index → emit nothing rather than crashing."""
    a = AdminAnalyzer(workspace_root=tmp_path)
    src = (
        "from django.contrib import admin\n"
        "@admin.register(User)\n"
        "class UserAdmin(admin.ModelAdmin):\n"
        "    list_display = ('email',)\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    assert a.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_unrelated_class_ignored(analyzer, tmp_path: Path) -> None:
    """A class that's not a ModelAdmin shouldn't trigger admin validation."""
    src = (
        "class NotAdmin:\n"
        "    list_display = ('eemail',)\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


# ---------------------------------------------------------------------------
# Traversal across relations
# ---------------------------------------------------------------------------


def test_diagnostic_traversal_in_list_display(analyzer, tmp_path: Path) -> None:
    """Profile has FK user→User; ``user__bogus`` invalid, ``user__email`` ok."""
    src = (
        "from django.contrib import admin\n"
        "from myapp.models import Profile\n"
        "\n"
        "@admin.register(Profile)\n"
        "class ProfileAdmin(admin.ModelAdmin):\n"
        "    list_display = ('user__email', 'user__bogus')\n"
    )
    f = tmp_path / "admin.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any("bogus" in d.get("message", "") for d in diags)
    # ``user__email`` is a valid traversal.
    assert not any(
        "user__email" in d.get("message", "") for d in diags
    )
