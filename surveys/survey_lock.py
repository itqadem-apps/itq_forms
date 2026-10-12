"""The survey row lock every builder structure write takes first (`forms:AD-25`).

Each helper resolves the survey through `all_objects`, so a row already soft-deleted
(`forms:AD-21`) still finds its survey, and locks it with `select_for_update` inside the caller's
transaction. Only the primary key is selected, so the lock does not depend on the survey's other
columns. Each returns the locked survey id, which is the one the caller then renumbers.
"""

from __future__ import annotations

from surveys.models import Question, Section, Survey


def lock_survey(survey_id: int) -> int:
    return Survey.objects.select_for_update().values_list("pk", flat=True).get(pk=survey_id)


def lock_survey_of_section(section_id) -> int:
    return lock_survey(Section.all_objects.values_list("survey_id", flat=True).get(pk=section_id))


def lock_survey_of_question(question_id) -> int:
    """A legacy question may have no `survey_id`; it belongs to its section's survey."""
    survey_id, section_survey_id = Question.all_objects.values_list("survey_id", "section__survey_id").get(pk=question_id)
    return lock_survey(survey_id or section_survey_id)
