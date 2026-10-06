"""Story autism-merge 1.1 — the apply release moves exactly the reported items and republishes them,
or writes nothing and fails the deploy (report #64, `estate:AD-20`, `estate:AD-15`)."""

import importlib
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from survey_collections.models import SurveyCollection
from surveys import autism_merge
from surveys.models import Survey
from taxonomy.models import Category, CategoryTranslation
from tests.test_autism_merge_report import OTHER_TREE, TREE, _cat, _snapshot

MIGRATION = importlib.import_module("surveys.migrations.0054_apply_autism_merge")


def _clone(obj):
    copy = type(obj).objects.get(pk=obj.pk)
    copy.pk = None
    copy.save()
    return copy


@pytest.fixture
def world(survey, collection, monkeypatch):
    """Live التوحد and اضطراب طيف التوحد in one tree, two surveys and two collections on التوحد,
    and the module's reported plan pointed at them."""
    source = _cat("التوحد", path="1")
    target = _cat("اضطراب طيف التوحد", path="2")
    surveys = [survey, _clone(survey)]
    collections = [collection, _clone(collection)]
    for item in surveys + collections:
        item.category = source
        item.save(update_fields=["category"])
    monkeypatch.setattr(autism_merge, "APPLY_SOURCE", str(source.category_id))
    monkeypatch.setattr(autism_merge, "APPLY_TARGET", str(target.category_id))
    monkeypatch.setattr(autism_merge, "APPLY_SURVEYS", frozenset(str(s.pk) for s in surveys))
    monkeypatch.setattr(autism_merge, "APPLY_COLLECTIONS", frozenset(str(c.pk) for c in collections))
    return {"source": source, "target": target, "surveys": surveys, "collections": collections}


def _run(capsys):
    with patch("app.messaging.publisher._outbox.add") as outbox_add:
        MIGRATION.forwards(None, None)
    return capsys.readouterr().out, outbox_add


def _categories():
    return (
        sorted(Category.objects.values_list("category_id", "tree_id", "name", "path_text", "deleted_at")),
        sorted(CategoryTranslation.objects.values_list("id", "category_id", "language", "name")),
    )


def test_the_plan_is_the_report_read_from_prod():
    assert autism_merge.APPLY_SOURCE == "7878f298-ee3c-40ba-88f3-9cecfe841b14"
    assert autism_merge.APPLY_TARGET == "6684c538-b347-446a-b4fe-993176be6335"
    assert autism_merge.APPLY_SURVEYS == {"189", "5"}
    assert autism_merge.APPLY_COLLECTIONS == {"1", "2", "3", "4", "5", "6", "7"}


def test_a_matching_plan_moves_the_items_and_republishes_each(world, capsys):
    categories = _categories()
    target = world["target"].category_id

    out, outbox_add = _run(capsys)

    assert _categories() == categories
    for item in world["surveys"] + world["collections"]:
        item.refresh_from_db()
        assert item.category_id == target
    assert not Survey.objects.filter(category=world["source"]).exists()
    assert not SurveyCollection.objects.filter(category=world["source"]).exists()
    published = [(c.kwargs["event_type"], c.kwargs["aggregate_id"], c.kwargs["payload"]) for c in outbox_add.call_args_list]
    assert sorted((e, a) for e, a, _ in published) == sorted(
        [("SurveyUpdated", str(s.pk)) for s in world["surveys"]]
        + [("CollectionUpdated", str(c.pk)) for c in world["collections"]]
    )
    for event, _, payload in published:
        body = payload["survey"] if event == "SurveyUpdated" else payload["collection"]
        assert body["category_id"] == str(target)
    survey_ids = sorted(str(s.pk) for s in world["surveys"])
    assert f"autism-merge: surveys moved {world['source'].category_id} -> {target}: 2 {sorted(survey_ids, key=int)}" in out
    assert "autism-merge: collections moved" in out
    assert "autism-merge: moved: 4" in out


@pytest.mark.parametrize(
    "break_it, expect",
    [
        ("extra_survey", "surveys on source differ from the report: extra"),
        ("missing_collection", "collections on source differ from the report: extra [] missing"),
        ("tombstoned_target", "is tombstoned"),
        ("tombstoned_source", "is tombstoned"),
        ("missing_target", "target category missing"),
        ("other_tree", "source tree"),
        ("child", "source has children"),
    ],
)
def test_a_mismatch_raises_and_writes_nothing(world, survey, capsys, monkeypatch, break_it, expect):
    if break_it == "extra_survey":
        extra = _clone(survey)
        extra.category = world["source"]
        extra.save(update_fields=["category"])
    elif break_it == "missing_collection":
        world["collections"][0].category = None
        world["collections"][0].save(update_fields=["category"])
    elif break_it in ("tombstoned_target", "tombstoned_source"):
        cat = world["target" if break_it == "tombstoned_target" else "source"]
        cat.deleted_at = datetime.now(timezone.utc)
        cat.save(update_fields=["deleted_at"])
    elif break_it == "missing_target":
        monkeypatch.setattr(autism_merge, "APPLY_TARGET", "00000000-0000-0000-0000-000000000000")
    elif break_it == "other_tree":
        Category.objects.filter(pk=world["target"].pk).update(tree_id=OTHER_TREE)
    elif break_it == "child":
        _cat("فرعي", path="1.5")
    before = _snapshot()

    with patch("app.messaging.publisher._outbox.add") as outbox_add, pytest.raises(autism_merge.PlanMismatch):
        MIGRATION.forwards(None, None)

    assert _snapshot() == before
    outbox_add.assert_not_called()
    out = capsys.readouterr().out
    assert "autism-merge: MISMATCH" in out
    assert expect in out


def test_a_rerun_after_the_move_is_a_noop(world, capsys):
    _run(capsys)
    before = _snapshot()

    out, outbox_add = _run(capsys)

    assert _snapshot() == before
    outbox_add.assert_not_called()
    assert "already applied" in out
    assert "autism-merge: moved: 0" in out


def test_a_database_without_either_category_is_a_noop(survey, capsys):
    before = _snapshot()

    out, outbox_add = _run(capsys)

    assert _snapshot() == before
    outbox_add.assert_not_called()
    assert "not in this database: nothing to move" in out


def test_a_same_path_in_another_tree_is_not_a_child(world, capsys):
    _cat("فرعي", tree=OTHER_TREE, path="1.5")

    out, _ = _run(capsys)

    assert "autism-merge: moved: 4" in out


def test_an_item_leaving_the_source_after_the_check_raises_before_republishing(world, monkeypatch):
    from django.db import transaction

    real_check = autism_merge._check

    def check_then_race(*args):
        problems = real_check(*args)
        SurveyCollection.objects.filter(pk=world["collections"][0].pk).update(category=None)
        return problems

    monkeypatch.setattr(autism_merge, "_check", check_then_race)

    with patch("app.messaging.publisher._outbox.add") as outbox_add, pytest.raises(
        autism_merge.PlanMismatch, match="collections moved 1, expected 2"
    ), transaction.atomic():
        MIGRATION.forwards(None, None)

    outbox_add.assert_not_called()
    for s in world["surveys"]:
        s.refresh_from_db()
        assert s.category_id == world["source"].category_id
