"""Tests for iommi extras: rows=/instance= queryset binding + style completion."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.django import build_index
from iommi_lsp.analyzers.iommi import IommiAnalyzer


CORPUS = Path(__file__).parent / "corpus"


def _write_with_cursor(
    tmp_path: Path, src_before: str, src_after: str = "",
) -> tuple[str, dict]:
    f = tmp_path / "u.py"
    f.write_text(src_before + src_after)
    line = src_before.count("\n")
    last_nl = src_before.rfind("\n")
    character = len(src_before) - (last_nl + 1)
    return f.as_uri(), {"line": line, "character": character}


def _labels(result) -> list[str]:
    return [it["label"] for it in result.items]


@pytest.fixture
def analyzer() -> IommiAnalyzer:
    index = build_index(CORPUS / "basic_django")
    a = IommiAnalyzer(
        workspace_root=CORPUS / "basic_django",
        django_index_provider=lambda: index,
        auto_build=False,
    )
    asyncio.run(a.index(CORPUS / "basic_django"))
    return a


def test_rows_kwarg_binds_model(analyzer, tmp_path: Path) -> None:
    """``Table(rows=User.objects.all(), columns__‸)`` — top-level rows= binds."""
    src = (
        "from iommi import Table\n"
        "from myapp.models import User\n"
        "Table(rows=User.objects.all(), columns__"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    labels = set(_labels(result))
    # Labels include the chain-continuation suffix.
    assert any(l.startswith("columns__email") for l in labels)
    assert any(l.startswith("columns__username") for l in labels)


def test_instance_kwarg_binds_model(analyzer, tmp_path: Path) -> None:
    """``Form(instance=user, fields__‸)`` — instance= binds when it's a queryset shape."""
    src = (
        "from iommi import Form\n"
        "from myapp.models import User\n"
        "Form(instance=User.objects.get(pk=1), fields__"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    labels = set(_labels(result))
    assert any(l.startswith("fields__email") for l in labels)


def test_style_completion(analyzer, tmp_path: Path) -> None:
    src = (
        "from iommi import Table\n"
        "Table(style='"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    labels = set(_labels(result))
    assert "bootstrap5" in labels
    assert "bootstrap" in labels
    assert "water" in labels
    # Non-exclusive — custom-registered styles shouldn't be suppressed.
    assert result.exclusive is False


def test_style_completion_partial(analyzer, tmp_path: Path) -> None:
    src = (
        "from iommi import Table\n"
        "Table(style='boot"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    labels = set(_labels(result))
    assert "bootstrap" in labels
    assert "bootstrap5" in labels
    assert "water" not in labels
