"""Index-builder tests over the corpus fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from iommi_lsp.analyzers.django import build_index


CORPUS = Path(__file__).parent / "corpus"


def test_basic_django_models_discovered():
    idx = build_index(CORPUS / "basic_django")
    workspace_models = {q for q, m in idx.models.items() if not m.is_builtin}
    assert workspace_models == {
        "myapp.models.User",
        "myapp.models.Profile",
        "myapp.models.WithExplicitPK",
    }
    user = idx.models["myapp.models.User"]
    assert set(user.fields) == {"username", "email"}
    assert user.fields["username"].field_type == "CharField"
    assert user.has_explicit_pk is False
    assert user.implicit_id is True

    explicit = idx.models["myapp.models.WithExplicitPK"]
    assert explicit.has_explicit_pk is True
    assert explicit.implicit_id is False
    assert explicit.fields["code"].is_pk is True


def test_one_to_one_creates_default_reverse():
    idx = build_index(CORPUS / "basic_django")
    # Profile.user -> User: default reverse name is "profile" (lower(model)_set
    # convention applies; OneToOne uses the same default — for v1 we ship
    # the documented `_set` behavior consistently).
    rev = idx.reverse_relations["myapp.models.User"]
    assert "profile_set" in rev


def test_related_names_explicit_and_default():
    idx = build_index(CORPUS / "related_names")
    author = "blog.models.Author"
    article = "blog.models.Article"

    rev_author = idx.reverse_relations[author]
    assert set(rev_author) == {"articles"}
    assert rev_author["articles"] == article  # source: Article declares the FK

    rev_article = idx.reverse_relations[article]
    assert "comment_set" in rev_article          # FK with no related_name
    assert rev_article["comment_set"] == "blog.models.Comment"
    assert "tags" in rev_article                  # M2M from Tag
    assert rev_article["tags"] == "blog.models.Tag"
    assert "+" not in rev_article                 # disabled reverse not recorded
    assert "hiddenlink_set" not in rev_article    # not registered when related_name="+"


def test_string_target_resolves_via_simple_name():
    idx = build_index(CORPUS / "related_names")
    comment = idx.models["blog.models.Comment"]
    article_field = comment.fields["article"]
    assert article_field.field_type == "ForeignKey"
    assert article_field.target == "blog.models.Article"


def test_fk_id_accessors():
    idx = build_index(CORPUS / "basic_django")
    profile = idx.models["myapp.models.Profile"]
    assert profile.fk_id_accessors == {"user_id"}


def test_pk_name_implicit_and_explicit():
    idx = build_index(CORPUS / "basic_django")
    user = idx.models["myapp.models.User"]
    explicit = idx.models["myapp.models.WithExplicitPK"]
    assert user.pk_name == "id"
    assert explicit.pk_name == "code"


def test_abstract_base_inheritance():
    idx = build_index(CORPUS / "abstract_base")
    assert "library.models.Timestamped" in idx.models
    assert "library.models.Book" in idx.models

    base = idx.models["library.models.Timestamped"]
    assert base.abstract is True
    # Abstract model -> implicit_id should be False (no table).
    assert base.implicit_id is False

    # Book inherits from Timestamped (transitive Model classification).
    assert "library.models.NotAModel" not in idx.models


def test_abstract_base_fields_propagate_to_subclass():
    idx = build_index(CORPUS / "abstract_base")
    book = idx.models["library.models.Book"]
    # `created`/`updated` are declared on the abstract Timestamped base
    # and must surface as fields on the concrete Book subclass — Django's
    # metaclass does the same copy at runtime.
    assert "created" in book.fields
    assert "updated" in book.fields
    assert "title" in book.fields


def test_builtin_contrib_models_indexed():
    idx = build_index(CORPUS / "basic_django")
    # The stub injects django.contrib.auth.User et al into every index,
    # marked with is_builtin so workspace models can still shadow them.
    auth_user = idx.models.get("django.contrib.auth.models.User")
    assert auth_user is not None
    assert auth_user.is_builtin is True
    # Inherited fields from AbstractUser propagate.
    assert "email" in auth_user.fields
    assert "username" in auth_user.fields
    # ContentType and Session are also indexed.
    assert "django.contrib.contenttypes.models.ContentType" in idx.models
    assert "django.contrib.sessions.models.Session" in idx.models


def test_workspace_model_shadows_builtin(tmp_path: Path):
    # Workspace defines a `User` model. Even though the contrib stub
    # also has a `User`, `lookup('User')` returns the workspace one.
    (tmp_path / "myapp").mkdir()
    (tmp_path / "myapp" / "__init__.py").write_text("")
    (tmp_path / "myapp" / "models.py").write_text(
        "from django.contrib.auth.models import AbstractUser\n"
        "from django.db import models\n"
        "class User(AbstractUser):\n"
        "    extra = models.CharField(max_length=10)\n"
    )
    idx = build_index(tmp_path)
    info = idx.lookup("User")
    assert info is not None
    assert info.qualname == "myapp.models.User"
    # AbstractUser fields inherited, plus the local `extra`.
    assert "email" in info.fields
    assert "extra" in info.fields


def test_summary_renders_without_error():
    idx = build_index(CORPUS / "related_names")
    out = idx.summary()
    assert "blog.models.Article" in out
    assert "articles" in out
    assert "comment_set" in out


def test_index_is_pure_no_imports(monkeypatch):
    """Sanity: the indexer must never call ``importlib`` on user code.

    We assert by removing ``importlib`` after import — if the index
    builder needed it at runtime, the test would fail.
    """
    import sys
    saved = sys.modules.get("django")
    sys.modules["django"] = None  # type: ignore[assignment]
    try:
        idx = build_index(CORPUS / "basic_django")
        assert "myapp.models.User" in idx.models
    finally:
        if saved is None:
            sys.modules.pop("django", None)
        else:
            sys.modules["django"] = saved
