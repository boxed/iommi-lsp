"""Regression-against-ty: confirm ty still emits the false positive we're
suppressing for Django ``IntegerChoices`` / ``TextChoices``.

We run the real ``ty check`` binary against a minimal fixture. The test
fails if ty stops producing ``invalid-assignment`` on an Enum member —
the signal that our suppression in :mod:`iommi_lsp.analyzers.django.analyzer`
can be removed.

Skipped if ``ty`` isn't on PATH.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


TY_BIN = shutil.which("ty")
pytestmark = pytest.mark.skipif(
    TY_BIN is None,
    reason="real ty binary not on PATH; skipping regression check",
)


CHOICES_FIXTURE = """\
from django.db import models


class MyChoices(models.IntegerChoices):
    GOOD = 1, "I like this"
    LESS_GOOD = 2, "not so much"
"""


def test_ty_still_flags_choices_enum_members(tmp_path):
    """If this stops failing on Choices tuple members, delete the hijack."""
    assert TY_BIN is not None
    f = tmp_path / "choices_sample.py"
    f.write_text(CHOICES_FIXTURE)

    result = subprocess.run(
        [TY_BIN, "check", str(f)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    combined = (result.stdout or "") + (result.stderr or "")

    assert "invalid-assignment" in combined, (
        "ty no longer emits invalid-assignment for IntegerChoices members — "
        "the choices_enum suppression in DjangoAnalyzer can be removed.\n"
        f"output:\n{combined}"
    )
    assert "Enum member" in combined, (
        "ty's invalid-assignment text for Enum tuple members changed shape — "
        "update or remove _is_choices_enum_member_assignment.\n"
        f"output:\n{combined}"
    )
