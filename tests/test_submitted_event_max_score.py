"""`SurveyResponseSubmitted` carries the attempt's `max_score` (`forms:AD-10`) beside its raw
`score`, so itq_courses grades a submission as score / max_score."""

import json
from unittest.mock import patch

from surveys.models import Survey
from user_surveys.services import finish_assessment, max_score

from tests.test_score_basis import _enrol, _mine, _pick, _scored, branched, qs  # noqa: F401


def _submitted_payload(us):
    captured = []
    with patch("app.messaging.publisher._outbox.add", side_effect=lambda **kw: captured.append(kw)):
        finish_assessment(us)
    us.refresh_from_db()
    rows = [row for row in captured if row["event_type"] == "SurveyResponseSubmitted"]
    assert len(rows) == 1
    json.dumps(rows[0]["payload"])
    return rows[0]["payload"]


def test_a_scored_submission_carries_its_max(user, survey, qs):
    low, _ = _scored(qs[0], 30, 100)
    _scored(qs[1], 0, 50)
    _scored(qs[2], 0, 50)
    us = _enrol(user, survey)
    _pick(us, qs[0], low)
    _pick(us, qs[1])
    _pick(us, qs[2])
    payload = _submitted_payload(us)
    assert (payload["score"], payload["max_score"]) == (30, 200)


def test_the_max_follows_the_basis(user, survey, qs, branched):
    skip, _ = branched
    us = _enrol(user, survey)
    _pick(us, qs[0], skip)
    _pick(us, qs[2])
    payload = _submitted_payload(us)
    assert not _mine(us, qs[1]).on_path
    assert payload["max_score"] == max_score(us) == 10 + 30


def test_an_unscored_submission_has_no_max(user, survey, qs):
    Survey.objects.filter(pk=survey.pk).update(use_score=False)
    us = _enrol(user, survey)
    _pick(us, qs[0])
    payload = _submitted_payload(us)
    assert payload["max_score"] is None


def test_a_manually_evaluated_submission_has_no_max_yet(user, survey, qs):
    Survey.objects.filter(pk=survey.pk).update(evaluation_type=Survey.EVALUATION_TYPE_MANUAL_EVALUATION)
    us = _enrol(user, survey)
    _pick(us, qs[0])
    payload = _submitted_payload(us)
    assert (payload["score"], payload["max_score"]) == (None, None)
