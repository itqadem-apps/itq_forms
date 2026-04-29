from __future__ import annotations

import pytest

from surveys.events import (
    AssessmentCreated,
    AssessmentDeleted,
    AssessmentPublished,
    AssessmentUnpublished,
    AssessmentUpdated,
    DomainEvent,
)
from surveys.outbox_adapter import _SUBJECT_TOKEN, SurveysOutboxEventBus


class _Repo:
    def __init__(self) -> None:
        self.calls = []

    def add(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def db():
    return None


def test_subject_token_maps_each_assessment_event_class() -> None:
    assert _SUBJECT_TOKEN == {
        AssessmentCreated: "assessment.created",
        AssessmentUpdated: "assessment.updated",
        AssessmentPublished: "assessment.published",
        AssessmentUnpublished: "assessment.unpublished",
        AssessmentDeleted: "assessment.deleted",
    }


def test_surveys_outbox_event_bus_falls_back_to_aggregate_type_for_unmapped_event() -> None:
    class AssessmentReindexed(DomainEvent):
        aggregate_type: str = "assessment"

    repo = _Repo()
    bus = SurveysOutboxEventBus(repo)

    bus.publish(AssessmentReindexed(aggregate_id="42", aggregate_type="assessment"))

    assert repo.calls[0]["aggregate_type"] == "assessment"
