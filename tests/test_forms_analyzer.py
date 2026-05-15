"""Tests for FormsAnalyzer — Form / ModelForm awareness."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from iommi_lsp.analyzers.forms import FormsAnalyzer
from iommi_lsp.analyzers.django import build_index


CORPUS = Path(__file__).parent / "corpus"


def _write_with_cursor(
    tmp_path: Path, src_before: str, src_after: str = "",
    filename: str = "forms.py",
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
def analyzer() -> FormsAnalyzer:
    index = build_index(CORPUS / "basic_django")
    a = FormsAnalyzer(
        workspace_root=CORPUS / "basic_django",
        django_index_provider=lambda: index,
    )
    asyncio.run(a.index(CORPUS / "basic_django"))
    return a


# ---------------------------------------------------------------------------
# Meta.fields / Meta.exclude completion
# ---------------------------------------------------------------------------


def test_completion_meta_fields(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    assert "email" in labels
    assert "username" in labels
    # ``__all__`` is offered as a special sentinel.
    assert "__all__" in labels


def test_completion_meta_exclude(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        exclude = ['"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    assert "email" in _labels(result)


def test_completion_meta_fields_partial(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['em"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["email"]


def test_completion_outside_form_silent(analyzer, tmp_path: Path) -> None:
    src = "x = '"
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.items == []
    assert result.exclusive is False


# ---------------------------------------------------------------------------
# self.fields / self.cleaned_data completion
# ---------------------------------------------------------------------------


def test_completion_self_fields_in_modelform(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email', 'username']\n"
        "    def go(self):\n"
        "        return self.fields['"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    assert set(_labels(result)) == {"email", "username"}


def test_completion_self_cleaned_data(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "class MyForm(forms.Form):\n"
        "    name = forms.CharField()\n"
        "    age = forms.IntegerField()\n"
        "    def clean(self):\n"
        "        return self.cleaned_data['"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    assert set(_labels(result)) == {"age", "name"}


# ---------------------------------------------------------------------------
# Diagnostics: Meta.fields
# ---------------------------------------------------------------------------


def test_diagnostic_unknown_meta_field(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email', 'eemail']\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-form-field"
        and "eemail" in d.get("message", "")
        for d in diags
    )


def test_diagnostic_known_meta_field_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email', 'username']\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_all_sentinel_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = '__all__'\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


# ---------------------------------------------------------------------------
# Diagnostics: clean_<field>
# ---------------------------------------------------------------------------


def test_diagnostic_clean_method_missing_field(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "class MyForm(forms.Form):\n"
        "    name = forms.CharField()\n"
        "    def clean_emial(self):\n"
        "        return self.cleaned_data['emial']\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-clean-method"
        and "emial" in d.get("message", "")
        for d in diags
    )


def test_diagnostic_clean_method_matches_field_silent(
    analyzer, tmp_path: Path,
) -> None:
    src = (
        "from django import forms\n"
        "class MyForm(forms.Form):\n"
        "    name = forms.CharField()\n"
        "    def clean_name(self):\n"
        "        return self.cleaned_data['name']\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_clean_method_matches_modelform_field_silent(
    analyzer, tmp_path: Path,
) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email']\n"
        "    def clean_email(self):\n"
        "        return self.cleaned_data['email']\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_clean_root_method_silent(analyzer, tmp_path: Path) -> None:
    """``clean(self)`` (no underscore suffix) is the form-wide cleaner."""
    src = (
        "from django import forms\n"
        "class MyForm(forms.Form):\n"
        "    name = forms.CharField()\n"
        "    def clean(self):\n"
        "        return self.cleaned_data\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


def test_diagnostic_no_fields_silent(analyzer, tmp_path: Path) -> None:
    """When a form has zero discoverable fields we don't fire — too many false positives."""
    src = (
        "from django import forms\n"
        "class MyForm(forms.Form):\n"
        "    def clean_anything(self):\n"
        "        return self.cleaned_data\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    assert analyzer.additional_diagnostics(f.as_uri()) == []


# ---------------------------------------------------------------------------
# Diagnostics: Meta.widgets / labels / help_texts / error_messages dict keys
# ---------------------------------------------------------------------------


def test_diagnostic_meta_widgets_unknown_key(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email', 'username']\n"
        "        widgets = {'email': forms.EmailInput(),\n"
        "                   'eemail': forms.EmailInput()}\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-form-field"
        and "eemail" in d.get("message", "")
        and "widgets" in d.get("message", "")
        for d in diags
    )


def test_diagnostic_meta_labels_known_key_silent(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email']\n"
        "        labels = {'email': 'E-mail'}\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert [d for d in diags if d.get("code") == "django-unknown-form-field"] == []


def test_diagnostic_meta_help_texts_unknown_key(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email']\n"
        "        help_texts = {'whatever': 'nope'}\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-form-field"
        and "whatever" in d.get("message", "")
        for d in diags
    )


def test_diagnostic_meta_error_messages_unknown_key(
    analyzer, tmp_path: Path,
) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email']\n"
        "        error_messages = {'usrname': {'required': 'Required.'}}\n"
    )
    f = tmp_path / "forms.py"
    f.write_text(src)
    diags = analyzer.additional_diagnostics(f.as_uri())
    assert any(
        d.get("code") == "django-unknown-form-field"
        and "usrname" in d.get("message", "")
        for d in diags
    )


# ---------------------------------------------------------------------------
# Completion: Meta.widgets dict keys
# ---------------------------------------------------------------------------


def test_completion_meta_widgets_key(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email', 'username']\n"
        "        widgets = {'"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    labels = set(_labels(result))
    assert "email" in labels
    assert "username" in labels
    # ``__all__`` is *not* offered for dict keys (unlike Meta.fields).
    assert "__all__" not in labels


def test_completion_meta_widgets_key_partial(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email', 'username']\n"
        "        widgets = {'em"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert _labels(result) == ["email"]


def test_completion_meta_widgets_second_key(analyzer, tmp_path: Path) -> None:
    """Second key of an in-progress dict — still completes correctly."""
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email', 'username']\n"
        "        widgets = {\n"
        "            'email': forms.EmailInput(),\n"
        "            '"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.exclusive is True
    assert "username" in set(_labels(result))


def test_completion_meta_labels_key(analyzer, tmp_path: Path) -> None:
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email']\n"
        "        labels = {'"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert "email" in set(_labels(result))


def test_completion_meta_widgets_value_not_field(analyzer, tmp_path: Path) -> None:
    """Cursor on the value side of a key:value pair should *not* be
    treated as a field-name slot — that's a widget class instance."""
    src = (
        "from django import forms\n"
        "from myapp.models import User\n"
        "\n"
        "class UserForm(forms.ModelForm):\n"
        "    class Meta:\n"
        "        model = User\n"
        "        fields = ['email']\n"
        "        labels = {'email': '"
    )
    uri, pos = _write_with_cursor(tmp_path, src)
    result = analyzer.completions(uri, pos)
    assert result.items == []
    assert result.exclusive is False
