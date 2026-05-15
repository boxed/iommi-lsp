"""Tests for MigrationsAnalyzer — dependency-tuple autocomplete."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.migrations import (
    MigrationsAnalyzer,
    discover_migrations,
)


def _write_with_cursor(
    tmp_path: Path, src_before: str, src_after: str = "",
    filename: str = "u.py",
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
def analyzer(tmp_path: Path) -> MigrationsAnalyzer:
    (tmp_path / "shop" / "migrations").mkdir(parents=True)
    (tmp_path / "shop" / "migrations" / "__init__.py").write_text("")
    (tmp_path / "shop" / "migrations" / "0001_initial.py").write_text("")
    (tmp_path / "shop" / "migrations" / "0002_extra.py").write_text("")
    (tmp_path / "blog" / "migrations").mkdir(parents=True)
    (tmp_path / "blog" / "migrations" / "__init__.py").write_text("")
    (tmp_path / "blog" / "migrations" / "0001_initial.py").write_text("")
    a = MigrationsAnalyzer(workspace_root=tmp_path)
    asyncio.run(a.index(tmp_path))
    return a


def test_discover_migrations(tmp_path: Path) -> None:
    (tmp_path / "app" / "migrations").mkdir(parents=True)
    (tmp_path / "app" / "migrations" / "__init__.py").write_text("")
    (tmp_path / "app" / "migrations" / "0001_initial.py").write_text("")
    (tmp_path / "app" / "migrations" / "0002_more.py").write_text("")
    found = discover_migrations(tmp_path)
    assert found == {"app": ["0001_initial", "0002_more"]}


def test_discover_skips_folders_without_init(tmp_path: Path) -> None:
    (tmp_path / "app" / "migrations").mkdir(parents=True)
    # No __init__.py — not a Django migrations folder.
    (tmp_path / "app" / "migrations" / "0001_initial.py").write_text("")
    assert discover_migrations(tmp_path) == {}


def test_completion_after_app_name(analyzer, tmp_path: Path) -> None:
    src = (
        "class Migration:\n"
        "    dependencies = [\n"
        "        ('shop', '"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    assert set(_labels(result)) == {"0001_initial", "0002_extra"}


def test_completion_partial(analyzer, tmp_path: Path) -> None:
    src = (
        "class Migration:\n"
        "    dependencies = [\n"
        "        ('shop', '0001"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["0001_initial"]


def test_completion_different_app(analyzer, tmp_path: Path) -> None:
    src = (
        "class Migration:\n"
        "    dependencies = [\n"
        "        ('blog', '"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["0001_initial"]


def test_completion_unknown_app(analyzer, tmp_path: Path) -> None:
    src = (
        "class Migration:\n"
        "    dependencies = [\n"
        "        ('nonexistent', '"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.items == []


def test_completion_outside_dependencies(analyzer, tmp_path: Path) -> None:
    src = "data = [('shop', '"
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    # Not under ``dependencies =`` → silent.
    assert result.items == []
