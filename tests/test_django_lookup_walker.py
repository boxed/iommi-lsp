"""Pure-function tests for the Django ORM lookup walker."""

from __future__ import annotations

import pytest

from iommi_lsp.analyzers.django.index import DjangoIndex, FieldInfo, ModelInfo
from iommi_lsp.analyzers.django.lookup_walker import OK, Problem, walk


@pytest.fixture
def index() -> DjangoIndex:
    """Hand-built minimal index covering FK forward, reverse, M2M and leaf fields."""
    author = ModelInfo(
        qualname="x.Author",
        module="x",
        name="Author",
        file_path=None,  # type: ignore[arg-type]
        bases=[],
    )
    author.fields["name"] = FieldInfo(name="name", field_type="CharField")

    article = ModelInfo(
        qualname="x.Article",
        module="x",
        name="Article",
        file_path=None,  # type: ignore[arg-type]
        bases=[],
    )
    article.fields["title"] = FieldInfo(name="title", field_type="CharField")
    article.fields["author"] = FieldInfo(
        name="author", field_type="ForeignKey", target="x.Author"
    )
    article.fields["pubdate"] = FieldInfo(name="pubdate", field_type="DateField")

    tag = ModelInfo(
        qualname="x.Tag",
        module="x",
        name="Tag",
        file_path=None,  # type: ignore[arg-type]
        bases=[],
    )
    tag.fields["name"] = FieldInfo(name="name", field_type="CharField")
    tag.fields["articles"] = FieldInfo(
        name="articles",
        field_type="ManyToManyField",
        target="x.Article",
        related_name="tags",
    )

    idx = DjangoIndex()
    for m in (author, article, tag):
        idx.add_model(m)
    # Reverse: Article declares author FK (default name "article_set" on Author);
    # Tag.articles M2M with related_name="tags" creates tags on Article.
    idx.reverse_relations["x.Author"]["article_set"] = "x.Article"
    idx.reverse_relations["x.Article"]["tags"] = "x.Tag"
    return idx


def test_known_field_passes(index):
    assert walk(index, "x.Article", ["title"]) is OK


def test_unknown_field_fails(index):
    res = walk(index, "x.Article", ["bogus"])
    assert isinstance(res, Problem)
    assert res.outcome == "unknown_field"
    assert res.bad_segment == "bogus"
    assert res.segment_index == 0
    assert res.on_model == "x.Article"
    assert "title" in res.available


def test_pk_is_always_valid(index):
    assert walk(index, "x.Article", ["pk"]) is OK


def test_pk_with_lookup_is_valid(index):
    assert walk(index, "x.Article", ["pk", "exact"]) is OK


def test_fk_id_accessor_is_valid(index):
    assert walk(index, "x.Article", ["author_id"]) is OK


def test_lookup_after_leaf_passes(index):
    assert walk(index, "x.Article", ["title", "icontains"]) is OK


def test_unknown_lookup_after_leaf_fails(index):
    res = walk(index, "x.Article", ["title", "bogus"])
    assert isinstance(res, Problem)
    assert res.outcome == "unknown_lookup"
    assert res.bad_segment == "bogus"
    assert res.segment_index == 1


def test_relation_traversal_validates_target_field(index):
    assert walk(index, "x.Article", ["author", "name", "icontains"]) is OK


def test_relation_traversal_unknown_field_on_target(index):
    res = walk(index, "x.Article", ["author", "bogus"])
    assert isinstance(res, Problem)
    assert res.outcome == "unknown_field"
    assert res.bad_segment == "bogus"
    assert res.segment_index == 1
    assert res.on_model == "x.Author"


def test_terminal_relation_is_ok(index):
    # `Article.objects.filter(author=user)` — relation ends at the field.
    assert walk(index, "x.Article", ["author"]) is OK


def test_reverse_relation_traversal(index):
    # Author.objects.filter(article_set__title="x") — Django allows reverse
    # traversal in lookups (typically via related_name; default <model>_set
    # works the same here).
    assert walk(index, "x.Author", ["article_set", "title"]) is OK


def test_m2m_reverse_traversal(index):
    # Article.objects.filter(tags__name="python")
    assert walk(index, "x.Article", ["tags", "name"]) is OK


def test_m2m_in_lookup_is_valid(index):
    # `Article.objects.filter(tags__in=[tag1, tag2])` — m2m + IN lookup
    # filters by PK. The relation acts as a leaf, no field traversal.
    assert walk(index, "x.Article", ["tags", "in"]) is OK


def test_fk_in_lookup_is_valid(index):
    # `Article.objects.filter(author__in=[u1, u2])`.
    assert walk(index, "x.Article", ["author", "in"]) is OK


def test_fk_isnull_lookup_is_valid(index):
    # `Article.objects.filter(author__isnull=True)`.
    assert walk(index, "x.Article", ["author", "isnull"]) is OK


def test_relation_traversal_still_validates_target_after_in_check(index):
    # `tags__name__icontains` should still walk into Tag.name, not be
    # short-circuited by the lookup check.
    assert walk(index, "x.Article", ["tags", "name", "icontains"]) is OK


def test_transform_chain_passes(index):
    # Date transform + lookup — accept everything past the first lookup.
    assert walk(index, "x.Article", ["pubdate", "year", "gte"]) is OK


def test_unknown_model_passes(index):
    # Bias: we don't know the model, so we don't validate.
    assert walk(index, "x.NotAModel", ["whatever"]) is OK


def test_empty_chain_passes(index):
    assert walk(index, "x.Article", []) is OK
