"""Regression-against-ty: confirm ty still emits the false positive we're
suppressing for Django relation field declarations like
``project: Project = ForeignKey(Project, ...)``.

The test fails if ty stops producing ``invalid-assignment`` for such
declarations — the signal that our suppression in
:mod:`iommi_lsp.analyzers.django.analyzer` can be removed.

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


RELATION_FIELD_FIXTURE = """\
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=100)


class Task(models.Model):
    project: "Project" = models.ForeignKey(Project, on_delete=models.CASCADE)
"""


def test_ty_still_flags_relation_field_assignment(tmp_path):
    """If this stops failing on annotated FK fields, delete the hijack."""
    assert TY_BIN is not None
    f = tmp_path / "relation_sample.py"
    f.write_text(RELATION_FIELD_FIXTURE)

    result = subprocess.run(
        [TY_BIN, "check", str(f)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    combined = (result.stdout or "") + (result.stderr or "")

    assert "invalid-assignment" in combined, (
        "ty no longer emits invalid-assignment for annotated ForeignKey "
        "field declarations — the relation_field_assignment suppression "
        f"in DjangoAnalyzer can be removed.\noutput:\n{combined}"
    )
    assert "ForeignKey" in combined, (
        "ty's invalid-assignment text for relation field declarations "
        "no longer mentions ForeignKey — update or remove "
        f"_is_relation_field_assignment_message.\noutput:\n{combined}"
    )
