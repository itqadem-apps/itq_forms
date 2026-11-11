import os

import django
import pytest
from asgiref.sync import async_to_sync

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

import accounts.messaging as messaging
from accounts.messaging import handle_child_event, handle_child_guardian_event


@pytest.fixture
def db():
    return None


def test_child_events_upsert_local_child_projection(monkeypatch):
    calls = []

    async def upsert_child(child):
        calls.append(child)

    monkeypatch.setattr(messaging, "_upsert_child", upsert_child)

    async_to_sync(handle_child_event)(
        {
            "event": "ChildProfileCreated",
            "aggregate_id": "child-1",
            "child": {
                "id": "child-1",
                "name": "Alice",
                "photo_id": "photo-1",
                "status": "active",
            },
        },
        "users.child.child_profile_created",
    )

    assert calls == [
        {
            "id": "child-1",
            "name": "Alice",
            "photo_id": "photo-1",
            "status": "active",
        }
    ]


def test_child_guardian_events_upsert_and_end_relation(monkeypatch):
    upserts = []
    ended = []

    async def upsert_guardian(guardian, payload):
        upserts.append((guardian, payload))

    async def mark_ended(relation_id, payload):
        ended.append((relation_id, payload))

    monkeypatch.setattr(messaging, "_upsert_child_guardian", upsert_guardian)
    monkeypatch.setattr(messaging, "_mark_child_guardian_ended", mark_ended)

    async_to_sync(handle_child_guardian_event)(
        {
            "event": "GuardianRelationCreated",
            "aggregate_id": "relation-1",
            "user_id": "user-1",
            "child_id": "child-1",
            "status": "active",
            "role": "guardian",
            "guardian": {
                "id": "relation-1",
                "user_id": "user-1",
                "child_id": "child-1",
                "status": "active",
                "role": "guardian",
            },
        },
        "users.child_guardian.guardian_relation_created",
    )

    assert len(upserts) == 1
    assert upserts[0][0]["id"] == "relation-1"
    assert upserts[0][0]["child_id"] == "child-1"

    async_to_sync(handle_child_guardian_event)(
        {
            "event": "GuardianRelationEnded",
            "aggregate_id": "relation-1",
            "user_id": "user-1",
            "child_id": "child-1",
        },
        "users.child_guardian.guardian_relation_ended",
    )

    assert len(ended) == 1
    assert len(upserts) == 1
    assert ended[0][0] == "relation-1"
    assert ended[0][1]["child_id"] == "child-1"


def _stub_guardian_writes(monkeypatch):
    upserts = []
    ended = []

    async def upsert_guardian(guardian, payload):
        upserts.append((guardian, payload))

    async def mark_ended(relation_id, payload):
        ended.append((relation_id, payload))

    monkeypatch.setattr(messaging, "_upsert_child_guardian", upsert_guardian)
    monkeypatch.setattr(messaging, "_mark_child_guardian_ended", mark_ended)
    return upserts, ended


def _guardian_payload(event=None):
    payload = {
        "aggregate_id": "relation-1",
        "user_id": "user-1",
        "child_id": "child-1",
        "status": "active",
        "role": "guardian",
        "guardian": {
            "id": "relation-1",
            "user_id": "user-1",
            "child_id": "child-1",
            "status": "active",
            "role": "guardian",
        },
    }
    if event is not None:
        payload["event"] = event
    return payload


def test_child_guardian_approved_upserts_relation(monkeypatch):
    upserts, ended = _stub_guardian_writes(monkeypatch)
    payload = _guardian_payload("GuardianRelationApproved")

    async_to_sync(handle_child_guardian_event)(
        payload, "users.child_guardian.guardian_relation_approved"
    )

    assert upserts == [(payload["guardian"], payload)]
    assert ended == []


@pytest.mark.parametrize(
    "event",
    ["GuardianRelationRejected", "GuardianParentSet", "SomethingNew", None],
)
def test_child_guardian_non_allowlisted_events_write_nothing(monkeypatch, event):
    upserts, ended = _stub_guardian_writes(monkeypatch)

    result = async_to_sync(handle_child_guardian_event)(
        _guardian_payload(event), "users.child_guardian.whatever"
    )

    assert result is None
    assert upserts == []
    assert ended == []
