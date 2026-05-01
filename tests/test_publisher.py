from __future__ import annotations

import json
from unittest.mock import patch

import pytest

# Importing surveys.subjects registers the survey events even when
# Django apps.ready() has not run (e.g. in unit tests with no DB).
import surveys.subjects  # noqa: F401
from app.messaging.publisher import publish
from app.messaging.subjects import registered_events, subject_token_for
from surveys.events import (
    SurveyCreated,
    SurveyDeleted,
    SurveyPublished,
    SurveyUnpublished,
    SurveyUpdated,
)


@pytest.fixture
def db():
    return None


def test_subject_registry_maps_each_survey_event() -> None:
    assert subject_token_for(SurveyCreated) == "survey.created"
    assert subject_token_for(SurveyUpdated) == "survey.updated"
    assert subject_token_for(SurveyPublished) == "survey.published"
    assert subject_token_for(SurveyUnpublished) == "survey.unpublished"
    assert subject_token_for(SurveyDeleted) == "survey.deleted"


def test_subject_registry_includes_collection_events() -> None:
    import survey_collections.subjects  # noqa: F401
    from survey_collections.events import (
        CollectionCreated,
        CollectionDeleted,
        CollectionPublished,
        CollectionUnpublished,
        CollectionUpdated,
    )

    assert subject_token_for(CollectionCreated) == "collection.created"
    assert subject_token_for(CollectionUpdated) == "collection.updated"
    assert subject_token_for(CollectionPublished) == "collection.published"
    assert subject_token_for(CollectionUnpublished) == "collection.unpublished"
    assert subject_token_for(CollectionDeleted) == "collection.deleted"


def test_publish_writes_outbox_row_with_subject_token_in_aggregate_type() -> None:
    captured = {}

    def _add(**kwargs):
        captured.update(kwargs)

    with patch("app.messaging.publisher._outbox.add", side_effect=_add):
        event = SurveyCreated(
            aggregate_id=42,
            organization_id="org-1",
            survey={"id": "42", "organization_id": "org-1"},
        )
        publish(event)

    assert captured["aggregate_type"] == "survey.created"
    assert captured["aggregate_id"] == "42"
    assert captured["event_type"] == "SurveyCreated"
    assert captured["payload"]["survey"]["id"] == "42"
    assert captured["headers"]["event_id"]
    json.dumps(captured["payload"])


def test_publish_raises_when_event_class_not_registered() -> None:
    from surveys.events import DomainEvent

    class Unregistered(DomainEvent):
        aggregate_type: str = "x"

    with pytest.raises(LookupError):
        publish(Unregistered(aggregate_id="1"))


def test_registered_events_returns_copy() -> None:
    snapshot = registered_events()
    snapshot[type("X", (), {})] = "x"
    assert SurveyCreated in registered_events()
