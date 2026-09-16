"""Task #79 / story `forms-category-projection`: the taxonomy category projection.

The cases that matter are the ordering ones. One durable carries create, update
and delete for a category (estate:AD-15), so nothing guarantees they arrive in
the order they happened, and every one of these tests is really asking "does the
projection still end up in the right state".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from asgiref.sync import async_to_sync
from django.test import override_settings

from taxonomy.messaging import handle_category_event
from taxonomy.models import Category, CategoryTranslation, DeferredCategoryEvent

TREE = "11111111-1111-1111-1111-111111111111"
OTHER_TREE = "22222222-2222-2222-2222-222222222222"

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def _at(minutes: int) -> str:
    """The wire format: naive UTC isoformat, as the outbox bus writes it."""
    return (T0 + timedelta(minutes=minutes)).replace(tzinfo=None).isoformat()


def _created(category_id, path, *, tree_id=TREE, minutes=0, name="Autism", slug="autism"):
    return {
        "event_id": str(uuid4()),
        "aggregate_type": "category",
        "occurred_at": _at(minutes),
        "category_id": str(category_id),
        "tree_id": tree_id,
        "path": path,
        "assets_count": 0,
        "translations": [{"language": "en", "name": name, "slug": slug}],
    }


def _updated(category_id, path, *, minutes=1, name="Autism", slug="autism", path_changed=False):
    return {
        "event_id": str(uuid4()),
        "aggregate_type": "category",
        "occurred_at": _at(minutes),
        "category_id": str(category_id),
        "path": path,
        "path_changed": path_changed,
        "translations_changed": True,
        "assets_changed": False,
        "translations": [{"language": "en", "name": name, "slug": slug}],
    }


def _deleted(category_id, *, minutes=2, hard=False):
    return {
        "event_id": str(uuid4()),
        "aggregate_type": "category",
        "occurred_at": _at(minutes),
        "category_id": str(category_id),
        "hard": hard,
        "translations": [],
    }


def _handle(payload, subject="taxonomy.category.created"):
    async_to_sync(handle_category_event)(payload, subject)


@pytest.fixture(autouse=True)
def _configured_tree():
    with override_settings(CATEGORY_TREE_ID=TREE):
        yield


def test_created_projects_the_category_and_its_translations():
    category_id = uuid4()
    _handle(_created(category_id, "autism"))

    row = Category.objects.get(category_id=category_id)
    assert str(row.tree_id) == TREE
    assert row.path_text == "autism"
    assert row.name == "Autism"
    assert row.deleted_at is None
    assert row.occurred_at == T0

    translation = CategoryTranslation.objects.get(category_id=category_id)
    assert (translation.language, translation.name, translation.slug) == ("en", "Autism", "autism")


def test_a_create_for_another_tree_is_ignored():
    category_id = uuid4()
    _handle(_created(category_id, "cooking", tree_id=OTHER_TREE))

    assert not Category.objects.filter(category_id=category_id).exists()


def test_update_renames_the_category():
    category_id = uuid4()
    _handle(_created(category_id, "autism"))
    _handle(_updated(category_id, "autism", name="Autism Spectrum", slug="autism-spectrum"))

    row = Category.objects.get(category_id=category_id)
    assert row.name == "Autism Spectrum"
    assert CategoryTranslation.objects.get(category_id=category_id).slug == "autism-spectrum"


def test_a_stale_update_does_not_clobber_newer_state():
    """An update that happened *before* the state we hold must lose."""
    category_id = uuid4()
    _handle(_created(category_id, "autism", minutes=5, name="Current"))
    _handle(_updated(category_id, "autism", minutes=1, name="Stale"))

    assert Category.objects.get(category_id=category_id).name == "Current"


def test_an_update_before_its_create_is_parked_and_replayed():
    """The gap itq_courses has: it logs and drops, losing the rename."""
    category_id = uuid4()

    _handle(_updated(category_id, "autism", minutes=5, name="Renamed", slug="renamed"))
    assert not Category.objects.filter(category_id=category_id).exists()
    assert DeferredCategoryEvent.objects.filter(category_id=category_id).count() == 1

    _handle(_created(category_id, "autism", minutes=1, name="Original", slug="autism"))

    row = Category.objects.get(category_id=category_id)
    assert row.name == "Renamed", "the parked update must win: it is the newer event"
    assert CategoryTranslation.objects.get(category_id=category_id).slug == "renamed"
    assert not DeferredCategoryEvent.objects.filter(category_id=category_id).exists()


def test_a_parked_update_for_another_tree_is_never_applied():
    """Parking is safe for foreign-tree updates: no create ever replays them."""
    category_id = uuid4()
    _handle(_updated(category_id, "cooking", minutes=5, name="Baking"))
    _handle(_created(category_id, "cooking", tree_id=OTHER_TREE, minutes=1))

    assert not Category.objects.filter(category_id=category_id).exists()
    assert DeferredCategoryEvent.objects.filter(category_id=category_id).count() == 1


def test_moving_a_category_rewrites_its_descendants_paths():
    parent, child, grandchild = uuid4(), uuid4(), uuid4()
    _handle(_created(parent, "interventions", minutes=0, slug="interventions"))
    _handle(_created(child, "interventions.aba", minutes=0, slug="aba"))
    _handle(_created(grandchild, "interventions.aba.early", minutes=0, slug="early"))

    _handle(_updated(parent, "therapies", minutes=10, path_changed=True, slug="therapies"))

    assert Category.objects.get(category_id=parent).path_text == "therapies"
    assert Category.objects.get(category_id=child).path_text == "therapies.aba"
    assert Category.objects.get(category_id=grandchild).path_text == "therapies.aba.early"


def test_a_move_does_not_advance_descendant_watermarks():
    """A descendant's own state did not change, so a later update to it must still apply."""
    parent, child = uuid4(), uuid4()
    _handle(_created(parent, "interventions", minutes=0))
    _handle(_created(child, "interventions.aba", minutes=0, name="ABA", slug="aba"))

    _handle(_updated(parent, "therapies", minutes=10, path_changed=True))
    _handle(_updated(child, "therapies.aba", minutes=5, name="Applied Behaviour", slug="aba"))

    assert Category.objects.get(category_id=child).name == "Applied Behaviour"


def test_delete_tombstones_the_subtree_and_hides_it_from_readers():
    parent, child = uuid4(), uuid4()
    _handle(_created(parent, "interventions", minutes=0))
    _handle(_created(child, "interventions.aba", minutes=0))

    _handle(_deleted(parent, minutes=10))

    assert Category.objects.get(category_id=parent).deleted_at is not None
    assert Category.objects.get(category_id=child).deleted_at is not None
    assert not Category.live(tree_id=TREE).filter(category_id=parent).exists()
    assert not Category.live(tree_id=TREE).filter(category_id=child).exists()


def test_a_delete_before_its_create_still_suppresses_the_category():
    """The reason a tombstone exists at all: an absent row cannot refuse a create."""
    category_id = uuid4()

    _handle(_deleted(category_id, minutes=10))
    _handle(_created(category_id, "autism", minutes=1))

    row = Category.objects.get(category_id=category_id)
    assert row.deleted_at is not None
    assert not Category.live(tree_id=TREE).filter(category_id=category_id).exists()


def test_a_create_newer_than_the_tombstone_restores_the_category():
    category_id = uuid4()
    _handle(_created(category_id, "autism", minutes=0))
    _handle(_deleted(category_id, minutes=5))
    _handle(_created(category_id, "autism", minutes=10, name="Back"))

    row = Category.objects.get(category_id=category_id)
    assert row.deleted_at is None
    assert row.name == "Back"
    assert Category.live(tree_id=TREE).filter(category_id=category_id).exists()


def test_a_replayed_event_is_idempotent():
    """Redelivery is normal on a durable; the same event twice must change nothing."""
    category_id = uuid4()
    payload = _created(category_id, "autism")

    _handle(payload)
    _handle(payload)

    assert Category.objects.filter(category_id=category_id).count() == 1
    assert CategoryTranslation.objects.filter(category_id=category_id).count() == 1


def test_an_unrecognized_payload_shape_is_ignored():
    _handle({"event_id": "x", "aggregate_type": "category", "category_id": str(uuid4())})
    assert Category.objects.count() == 0
