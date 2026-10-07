"""Story survey-flow 2.8 follow-up — every seeded survey is numbered survey-wide (`forms:AD-4`),
and `--truncate` removes every seeded survey, survey 10 included."""

import io

import pytest
from django.core.management import call_command

from conftest import ORG
from surveys.management.commands import seed_test_surveys
from surveys.management.commands.seed_test_surveys import CREATORS, TAG
from surveys.models import Question, Survey, SurveyTranslation
from surveys.question_order import flat_question_ids

BRANCHING = {f"{TAG}Section Jump Navigation", f"{TAG}Section Jump Navigation (Scored)"}


def _seed(*args):
    """The surveys this run created, by English title."""
    before = set(Survey.objects.values_list("id", flat=True))
    call_command("seed_test_surveys", "--organization-id", str(ORG), *args, stdout=io.StringIO())
    return {
        t.title: t.survey
        for t in SurveyTranslation.objects.filter(language="en").exclude(survey_id__in=before).select_related("survey")
    }


def _orders(survey):
    return list(Question.objects.filter(survey=survey).values_list("order", flat=True))


@pytest.fixture
def recorded(monkeypatch):
    """Spy on the seed's explicit renumber calls: every sequence given, per survey id."""
    real = seed_test_surveys.renumber_questions
    calls = {}

    def spy(survey_id, sequence=None, *args, **kwargs):
        seq = list(sequence) if sequence is not None else None
        calls.setdefault(survey_id, []).append(seq)
        return real(survey_id, seq, *args, **kwargs)

    monkeypatch.setattr(seed_test_surveys, "renumber_questions", spy)
    return calls


def test_every_seeded_question_is_numbered_one_to_n():
    """Regression guard: the numbering comes from the `Question` post_save signal, which renumbers
    every create through `renumber_questions` (`forms:AD-4`)."""
    created = _seed()
    assert len(created) == len(CREATORS)
    for title, survey in created.items():
        orders = _orders(survey)
        assert orders, title
        assert None not in orders, title
        assert sorted(orders) == list(range(1, len(orders) + 1)), title


def test_branching_surveys_keep_their_explicit_sequence(recorded):
    created = _seed()
    for title in BRANCHING:
        survey = created[title]
        assert len(recorded[survey.id]) == 1
        (sequence,) = recorded[survey.id]
        assert sequence is not None
        by_order = list(Question.objects.filter(survey=survey).order_by("order").values_list("id", flat=True))
        assert by_order == sequence
        assert flat_question_ids(Question.objects.filter(survey=survey)) == sequence


def test_truncate_removes_every_seeded_survey():
    _seed()
    second = _seed("--truncate")
    assert Survey.objects.count() == len(CREATORS)
    assert set(Survey.objects.values_list("id", flat=True)) == {s.id for s in second.values()}
    assert f"{TAG}Demographics Survey" in second


def test_survey_10_title_is_tagged_and_arabic_unchanged():
    created = _seed()
    survey = created[f"{TAG}Demographics Survey"]
    assert all(title.startswith(TAG) for title in created)
    ar = SurveyTranslation.objects.get(survey=survey, language="ar")
    assert ar.title == "استبيان البيانات الديموغرافية"


def test_truncate_spares_an_untagged_survey():
    authored = Survey.objects.create(organization_id=ORG, primary_language="en")
    SurveyTranslation.objects.create(survey=authored, language="en", title="Authored Survey")
    _seed()
    _seed("--truncate")
    assert Survey.objects.filter(id=authored.id).exists()
    assert Survey.objects.count() == len(CREATORS) + 1
