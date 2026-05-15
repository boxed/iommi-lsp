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


# ---------------------------------------------------------------------------
# False-positive suppression for ``self.<inherited CBV attr>``
# ---------------------------------------------------------------------------


def _unresolved_diag(
    line: int, col_start: int, col_end: int, attr: str,
) -> dict:
    return {
        "code": "unresolved-attribute",
        "message": f"has no attribute {attr!r}",
        "range": {
            "start": {"line": line, "character": col_start},
            "end": {"line": line, "character": col_end},
        },
        "severity": 1,
        "source": "ty",
    }


def test_suppress_self_paginate_by_in_cbv(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import ListView\n"
        "\n"
        "class Wide(ListView):\n"
        "    paginate_by = 50\n"
        "    def get_paginate_by(self, qs):\n"
        "        return self.paginate_by * 2\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    line = src.splitlines().index("        return self.paginate_by * 2")
    col = src.splitlines()[line].index("paginate_by")
    diag = _unresolved_diag(line, col, col + len("paginate_by"), "paginate_by")
    assert analyzer.is_false_positive(f.as_uri(), diag) is True


def test_suppress_self_context_object_name_in_cbv(
    analyzer, tmp_path: Path,
) -> None:
    src = (
        "from django.views.generic import DetailView\n"
        "\n"
        "class Show(DetailView):\n"
        "    def get_context_data(self, **kwargs):\n"
        "        kwargs[self.context_object_name] = None\n"
        "        return kwargs\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    line = src.splitlines().index(
        "        kwargs[self.context_object_name] = None"
    )
    col = src.splitlines()[line].index("context_object_name")
    diag = _unresolved_diag(
        line, col, col + len("context_object_name"), "context_object_name",
    )
    assert analyzer.is_false_positive(f.as_uri(), diag) is True


def test_suppress_self_template_name(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import TemplateView\n"
        "\n"
        "class Hello(TemplateView):\n"
        "    def get(self, *a, **k):\n"
        "        return self.template_name\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    line = src.splitlines().index("        return self.template_name")
    col = src.splitlines()[line].index("template_name")
    diag = _unresolved_diag(
        line, col, col + len("template_name"), "template_name",
    )
    assert analyzer.is_false_positive(f.as_uri(), diag) is True


def test_keep_unknown_attr_on_self(analyzer, tmp_path: Path) -> None:
    """A truly unknown attr on ``self`` in a CBV stays — only the
    whitelisted CBV attrs are dropped, otherwise we'd mask real typos."""
    src = (
        "from django.views.generic import ListView\n"
        "\n"
        "class Foo(ListView):\n"
        "    def go(self):\n"
        "        return self.nonsense_attr\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    line = src.splitlines().index("        return self.nonsense_attr")
    col = src.splitlines()[line].index("nonsense_attr")
    diag = _unresolved_diag(
        line, col, col + len("nonsense_attr"), "nonsense_attr",
    )
    assert analyzer.is_false_positive(f.as_uri(), diag) is False


def test_keep_paginate_by_outside_cbv(analyzer, tmp_path: Path) -> None:
    """``self.paginate_by`` outside any CBV class is not ours to drop."""
    src = (
        "class Random:\n"
        "    def go(self):\n"
        "        return self.paginate_by\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src)
    line = src.splitlines().index("        return self.paginate_by")
    col = src.splitlines()[line].index("paginate_by")
    diag = _unresolved_diag(
        line, col, col + len("paginate_by"), "paginate_by",
    )
    assert analyzer.is_false_positive(f.as_uri(), diag) is False


def test_keep_paginate_by_on_other_receiver(analyzer, tmp_path: Path) -> None:
    """``other.paginate_by`` — not on ``self`` — is left alone."""
    src = (
        "from django.views.generic import ListView\n"
        "\n"
        "class Foo(ListView):\n"
        "    def go(self, other):\n"
        "        return other.paginate_by\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    line = src.splitlines().index("        return other.paginate_by")
    col = src.splitlines()[line].index("paginate_by")
    diag = _unresolved_diag(
        line, col, col + len("paginate_by"), "paginate_by",
    )
    assert analyzer.is_false_positive(f.as_uri(), diag) is False


def test_keep_unrelated_diagnostic_code(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.views.generic import ListView\n"
        "\n"
        "class Foo(ListView):\n"
        "    def go(self):\n"
        "        return self.paginate_by\n"
    )
    f = tmp_path / "views.py"
    f.write_text(src)
    line = src.splitlines().index("        return self.paginate_by")
    col = src.splitlines()[line].index("paginate_by")
    diag = _unresolved_diag(
        line, col, col + len("paginate_by"), "paginate_by",
    )
    diag["code"] = "some-other-rule"
    assert analyzer.is_false_positive(f.as_uri(), diag) is False
