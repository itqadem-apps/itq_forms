"""Regression coverage for snapshot questions losing their section link.

Mobile reported a submitted attempt whose `sections` came back populated but
with `questions: []` on every section, so the results screen counted 0/0. The
read path is not the cause — `userSurvey.sections[].questions` is the plain
reverse of `UserQuestion.section`, with no visibility or submitted-state
filter anywhere on it. A snapshot question with `section = NULL` is the only
thing that produces that payload, and `create_survey_snapshot` used to write
one whenever a source section fell outside the survey's own section list.
"""

import pytest
from django.core.management import call_command
from django.utils.timezone import now
from io import StringIO

from surveys.models import Question, Section
from user_surveys.models import UserQuestion
from user_surveys.services import enroll_user_in_assessment


RESULTS_QUERY = """
query Results($input: UserSurveysListInput!) {
  userSurvey(userSurveysListInput: $input) {
    items {
      id
      questions { id sectionId }
      sections { id originId isHidden questions { id originId sectionId } }
    }
  }
}
"""


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user):
        self.request = None
        self.identity = _Identity(user)
        self.auth_context = None
        self.currency = None


def _results(user, user_survey):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        RESULTS_QUERY,
        variable_values={
            "input": {"limit": 1, "offset": 0, "filters": {"id": user_survey.id}, "sort": None}
        },
        context_value=_Context(user),
    )
    assert result.errors is None, result.errors
    return result.data["userSurvey"]["items"][0]


def _submit(user_survey):
    user_survey.submitted_at = now()
    user_survey.evaluated_at = now()
    user_survey.save(update_fields=["submitted_at", "evaluated_at"])
    return user_survey


def test_a_null_section_is_what_empties_the_sections_on_the_wire(user, survey, section, question):
    """Pins the mechanism behind the reported payload: sections present,
    questions empty, flat list still full."""
    user_survey = _submit(enroll_user_in_assessment(user, survey.id)[0])
    assert all(item["questions"] for item in _results(user, user_survey)["sections"])

    UserQuestion.objects.filter(user_survey=user_survey).update(section=None)

    payload = _results(user, user_survey)
    assert payload["questions"], "the flat list still carries every question"
    assert [item["questions"] for item in payload["sections"]] == [[]]


def test_a_section_outside_the_surveys_own_list_still_links(user, survey, section, question):
    """The regression itself.

    Nothing constrains `Question.section` to a section of the question's own
    survey, so a question can reference one the survey does not list. The
    snapshot built its section map from `survey.sections` alone and resolved
    that reference to NULL, taking the question out of every section on the
    results screen. The section is now snapshotted alongside it instead.
    """
    from surveys.models import Survey

    other_survey = Survey.objects.create(
        survey_type=Survey.ASSESSMENT_TYPE_SURVEY,
        display_option=Survey.DISPLAY_OPTION_BY_QUESTION,
        evaluation_type=Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION,
    )
    foreign_section = Section.objects.create(
        survey=other_survey, title="Belongs elsewhere", order=1
    )
    stray = Question.objects.create(
        survey=survey,
        section=foreign_section,
        title="Points at another survey's section",
        type=Question.QUESTION_TYPE_TEXT,
    )
    assert foreign_section not in list(survey.sections.all())

    user_survey = _submit(enroll_user_in_assessment(user, survey.id)[0])

    snapshot = UserQuestion.objects.get(user_survey=user_survey, origin_id=stray.id)
    assert snapshot.section is not None
    assert snapshot.section.origin_id == foreign_section.id

    payload = _results(user, user_survey)
    sectioned = {item["id"] for group in payload["sections"] for item in group["questions"]}
    assert {item["id"] for item in payload["questions"]} == sectioned


def test_a_source_question_cannot_be_left_without_a_section(user, survey, section):
    """The other shape that would empty a section is unreachable: the answer
    schema created alongside every question requires a section, so a
    sectionless question cannot be written in the first place. Worth pinning —
    if this constraint is ever relaxed, the flat `questions` list becomes the
    only complete one and the clients need a new rule."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        Question.objects.create(
            survey=survey, section=None, title="Sectionless", type=Question.QUESTION_TYPE_TEXT
        )


def test_repair_command_relinks_a_recoverable_orphan(user, survey, section, question):
    user_survey = _submit(enroll_user_in_assessment(user, survey.id)[0])
    UserQuestion.objects.filter(user_survey=user_survey).update(section=None)

    out = StringIO()
    call_command("repair_snapshot_sections", user_surveys=[user_survey.id], stdout=out)
    assert "recoverable — source section still known: 1" in out.getvalue()
    assert "Dry run" in out.getvalue()
    assert UserQuestion.objects.filter(user_survey=user_survey, section__isnull=True).count() == 1

    call_command("repair_snapshot_sections", "--apply", user_surveys=[user_survey.id], stdout=StringIO())
    assert not UserQuestion.objects.filter(user_survey=user_survey, section__isnull=True).exists()
    assert all(item["questions"] for item in _results(user, user_survey)["sections"])


def test_repair_command_reports_an_orphan_it_cannot_resolve(user, survey, section, question):
    """A snapshot whose source question is gone cannot be relinked; the command
    must say so rather than silently leaving it out of the tally."""
    user_survey = _submit(enroll_user_in_assessment(user, survey.id)[0])
    UserQuestion.objects.filter(user_survey=user_survey).update(section=None, origin_id=None)

    out = StringIO()
    call_command("repair_snapshot_sections", "--apply", user_surveys=[user_survey.id], stdout=out)
    assert "unresolved — source question or section is gone: 1" in out.getvalue()
    assert UserQuestion.objects.filter(user_survey=user_survey, section__isnull=True).count() == 1
