import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

import user_surveys.child_projection as child_projection


@pytest.fixture
def db():
    return None


class _Query:
    def __init__(self, relation):
        self._relation = relation
        self.filters = None

    def filter(self, **kwargs):
        self.filters = kwargs
        expected = {
            "user_id": "user-1",
            "child_id": "child-1",
            "status": "active",
            "child__status": "active",
        }
        return _Query(self._relation if kwargs == expected else None)

    def first(self):
        return self._relation


class _Manager:
    def __init__(self, relation):
        self._relation = relation

    def select_related(self, *fields):
        assert fields == ("child",)
        return _Query(self._relation)


class _Relation:
    def __init__(self, child):
        self.child = child


def test_get_active_child_for_user_accepts_active_relation_and_child(monkeypatch):
    child = object()
    monkeypatch.setattr(
        child_projection,
        "ChildGuardian",
        type("ChildGuardian", (), {"objects": _Manager(_Relation(child))}),
    )

    assert child_projection.get_active_child_for_user("user-1", "child-1") is child


@pytest.mark.parametrize(
    ("user_id", "child_id"),
    [
        ("other-user", "child-1"),
        ("user-1", "other-child"),
    ],
)
def test_get_active_child_for_user_rejects_missing_or_non_matching_relation(
    monkeypatch,
    user_id,
    child_id,
):
    child = object()
    monkeypatch.setattr(
        child_projection,
        "ChildGuardian",
        type("ChildGuardian", (), {"objects": _Manager(_Relation(child))}),
    )

    assert child_projection.get_active_child_for_user(user_id, child_id) is None


def test_get_active_child_for_user_rejects_missing_relation(monkeypatch):
    monkeypatch.setattr(
        child_projection,
        "ChildGuardian",
        type("ChildGuardian", (), {"objects": _Manager(None)}),
    )

    assert child_projection.get_active_child_for_user("user-1", "child-1") is None
