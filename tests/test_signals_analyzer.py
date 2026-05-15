"""Tests for SignalsAnalyzer — sender= / signal= autocomplete."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.django import build_index
from iommi_lsp.analyzers.signals import SignalsAnalyzer


CORPUS = Path(__file__).parent / "corpus"


def _write_with_cursor(
    tmp_path: Path, src_before: str, src_after: str = "",
) -> tuple[str, dict]:
    f = tmp_path / "signals.py"
    f.write_text(src_before + src_after)
    line = src_before.count("\n")
    last_nl = src_before.rfind("\n")
    character = len(src_before) - (last_nl + 1)
    return f.as_uri(), {"line": line, "character": character}


def _labels(result) -> list[str]:
    return [it["label"] for it in result.items]


@pytest.fixture
def analyzer() -> SignalsAnalyzer:
    index = build_index(CORPUS / "basic_django")
    a = SignalsAnalyzer(
        workspace_root=CORPUS / "basic_django",
        django_index_provider=lambda: index,
    )
    asyncio.run(a.index(CORPUS / "basic_django"))
    return a


def test_sender_in_receiver_decorator(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.db.models.signals import post_save\n"
        "from django.dispatch import receiver\n"
        "\n"
        "@receiver(post_save, sender="
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    labels = set(_labels(result))
    assert "User" in labels
    assert "Profile" in labels
    # Exclusive — ty's keyword suggestions at this slot are noise.
    assert result.exclusive is True


def test_sender_with_partial(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.db.models.signals import post_save\n"
        "from django.dispatch import receiver\n"
        "\n"
        "@receiver(post_save, sender=Us"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["User"]


def test_sender_in_connect(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.db.models.signals import post_save\n"
        "post_save.connect(handler, sender="
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert "User" in _labels(result)


def test_signal_first_positional_of_receiver(analyzer, tmp_path: Path) -> None:
    src = (
        "from django.dispatch import receiver\n"
        "\n"
        "@receiver(post"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    labels = set(_labels(result))
    assert "post_save" in labels
    assert "post_delete" in labels


def test_signal_kwarg_on_connect(analyzer, tmp_path: Path) -> None:
    src = (
        "thing.connect(handler, signal=pre"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    labels = set(_labels(result))
    assert "pre_save" in labels
    assert "pre_delete" in labels


def test_unrelated_kwarg_silent(analyzer, tmp_path: Path) -> None:
    src = "foo(bar=ba"
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.items == []


def test_sender_without_index_silent(tmp_path: Path) -> None:
    a = SignalsAnalyzer(workspace_root=tmp_path)
    src = (
        "from django.dispatch import receiver\n"
        "@receiver(post_save, sender=Us"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = a.completions(uri, pos)
    assert result.items == []
