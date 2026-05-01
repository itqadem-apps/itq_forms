import uuid

from surveys.messaging import build_survey_payload_or_log, serialize_survey


def test_serialize_survey_returns_none_when_survey_org_missing(survey):
    payload = serialize_survey(survey)

    assert payload["organization_id"] is None


def test_serialize_survey_uses_survey_organization_id(survey):
    org_id = uuid.uuid4()
    survey.organization_id = org_id

    payload = serialize_survey(survey)

    assert payload["organization_id"] == str(org_id)


def test_serialize_survey_translations_match_orders_contract(survey):
    payload = serialize_survey(survey)

    translation = payload["translations"][0]
    assert translation["language"] == "en"
    assert translation["title"] == "Test Survey"
    assert translation["description"] == "A test survey"
    assert translation["summary"] == "Short desc"


def test_build_survey_payload_or_log_skips_when_org_missing(survey, caplog):
    with caplog.at_level("WARNING"):
        payload = build_survey_payload_or_log(survey, "SurveyPublished")

    assert payload is None
    assert (
        f"reason=missing_organization_id survey_id={survey.pk} event=SurveyPublished"
        in caplog.text
    )


def test_build_survey_payload_or_log_returns_payload_when_org_valid(survey):
    org_id = uuid.uuid4()
    survey.organization_id = org_id

    payload = build_survey_payload_or_log(survey, "SurveyCreated")

    assert payload is not None
    assert payload["organization_id"] == str(org_id)
