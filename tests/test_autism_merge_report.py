"""Story autism-merge 1.1 — the report release prints the التوحد move plan and writes nothing
(report #64, `estate:AD-20`, `estate:AD-15`)."""

import importlib
import uuid
from datetime import datetime, timezone

import pytest

from survey_collections.models import SurveyCollection
from surveys import autism_merge
from surveys.models import Survey
from taxonomy.models import Category, CategoryTranslation

TREE = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_TREE = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _cat(name_ar, *, tree=TREE, path=None, deleted=False, name_en=None):
    c = Category.objects.create(
        tree_id=tree,
        name=name_en or name_ar,
        path_text=path,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    CategoryTranslation.objects.create(category=c, language="ar", name=name_ar)
    if name_en:
        CategoryTranslation.objects.create(category=c, language="en", name=name_en)
    return c


def _snapshot():
    return (
        sorted(Category.objects.values_list("category_id", "tree_id", "name", "path_text", "deleted_at")),
        sorted(CategoryTranslation.objects.values_list("id", "category_id", "language", "name")),
        sorted(Survey.objects.values_list("id", "category_id")),
        sorted(SurveyCollection.objects.values_list("id", "category_id")),
    )


def _run(capsys):
    migration = importlib.import_module("surveys.migrations.0053_report_autism_merge")
    migration.forwards(None, None)
    return capsys.readouterr().out


def test_it_reports_the_items_on_autism_and_their_target_and_writes_nothing(survey, collection, capsys):
    source = _cat("التوحد", path="1", name_en="Autism")
    target = _cat("اضطراب طيف التوحد", path="2", name_en="Autism Spectrum Disorder")
    _cat("اضطراب طيف التوحد", tree=OTHER_TREE, path="9")
    survey.category = source
    survey.save(update_fields=["category"])
    collection.category = source
    collection.save(update_fields=["category"])
    before = _snapshot()

    out = _run(capsys)

    assert _snapshot() == before
    assert f"source {source.category_id} tree={TREE} path=1 live" in out
    assert f"target: {target.category_id}" in out
    assert f"surveys: 1 ['{survey.id}']" in out
    assert f"collections: 1 ['{collection.id}']" in out
    assert "items that would move: 2" in out


def test_it_says_so_when_no_category_is_named_autism(db, capsys):
    _cat("اضطراب طيف التوحد", path="2")

    out = _run(capsys)

    assert "no category named التوحد in the projection: nothing to move" in out


def test_it_says_so_when_autism_exists_but_no_item_references_it(db, capsys):
    _cat("التوحد", path="1")
    _cat("اضطراب طيف التوحد", path="2")

    out = _run(capsys)

    assert "surveys: 0 []" in out
    assert "no survey or collection references a category named التوحد: nothing to move" in out


def test_a_tombstoned_autism_is_listed_with_its_items(survey, capsys):
    source = _cat("التوحد", path="1", deleted=True)
    _cat("اضطراب طيف التوحد", path="2")
    survey.category = source
    survey.save(update_fields=["category"])

    out = _run(capsys)

    assert f"source {source.category_id} tree={TREE} path=1 tombstoned" in out
    assert "items that would move: 1" in out


def test_a_missing_or_tombstoned_target_is_flagged(db, capsys):
    _cat("التوحد", path="1")
    _cat("اضطراب طيف التوحد", path="2", deleted=True)

    out = _run(capsys)

    assert "target: NONE live in this tree (apply would refuse)" in out


def test_two_live_targets_in_the_tree_are_flagged_ambiguous(db, capsys):
    _cat("التوحد", path="1")
    _cat("اضطراب طيف التوحد", path="2")
    _cat("اضطراب طيف التوحد", path="3")

    out = _run(capsys)

    assert "target: AMBIGUOUS" in out


def test_children_of_autism_and_their_items_are_listed(survey, capsys):
    _cat("التوحد", path="1")
    child = _cat("فرعي", path="1.5")
    _cat("اضطراب طيف التوحد", path="2")
    survey.category = child
    survey.save(update_fields=["category"])

    out = _run(capsys)

    assert "children: 1" in out
    assert f"child {child.category_id} path=1.5 live" in out
    assert f"surveys: 1 ['{survey.id}']" in out
    assert "items on children of التوحد: 1" in out


def test_the_english_display_name_alone_does_not_make_a_category_autism(db):
    c = Category.objects.create(tree_id=TREE, name="Autism", path_text="1")
    CategoryTranslation.objects.create(category=c, language="ar", name="شيء آخر")

    assert autism_merge.plan()["sources"] == []
