import uuid

from surveys.messaging import (
    publish_assessment_status_event,
    serialize_assessment,
)
from surveys.models import Survey


def test_serialize_assessment_returns_none_when_survey_org_missing(survey):
    payload = serialize_assessment(survey)

    assert payload["organization_id"] is None


def test_serialize_assessment_uses_survey_organization_id(survey):
    org_id = uuid.uuid4()
    survey.organization_id = org_id

    payload = serialize_assessment(survey)

    assert payload["organization_id"] == str(org_id)


def test_publish_assessment_status_event_skips_when_org_missing(survey, monkeypatch, caplog):
    published_events = []

    def _fake_publish(event):
        published_events.append(event)

    monkeypatch.setattr("surveys.messaging.event_bus.publish", _fake_publish)
    survey.status = Survey.STATUS_PUBLISHED

    with caplog.at_level("WARNING"):
        publish_assessment_status_event(survey)

    assert published_events == []
    assert (
        f"reason=missing_organization_id assessment_id={survey.pk} event=AssessmentPublished"
        in caplog.text
    )


def test_publish_assessment_status_event_publishes_when_survey_org_valid(survey, monkeypatch):
    org_id = uuid.uuid4()
    survey.organization_id = org_id
    published_events = []

    def _fake_publish(event):
        published_events.append(event)

    monkeypatch.setattr("surveys.messaging.event_bus.publish", _fake_publish)
    survey.status = Survey.STATUS_PUBLISHED

    publish_assessment_status_event(survey)

    assert len(published_events) == 1
    assert published_events[0].event == "AssessmentPublished"
    assert published_events[0].organization_id == str(org_id)
    assert published_events[0].assessment["organization_id"] == str(org_id)
