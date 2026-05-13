"""Domain events for user_surveys (the assessment-runtime app)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(slots=True)
class DomainEvent:
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    aggregate_type: str = ""
    aggregate_id: int | str | None = None
    organization_id: str | None = None
    metadata: dict[str, Any] | None = None
    event: str = ""


@dataclass(slots=True)
class SurveyResponseSubmitted(DomainEvent):
    """Emitted when a learner submits a survey/assessment (finishes the form).

    Consumers (e.g. itq_courses for quiz-lesson progress) read this to
    record that the user is "done" with the survey and at what score.
    Fires on ANY submission — including incomplete/forced terminations
    that fall through to ``finish_assessment``.
    """
    aggregate_type: str = "survey_response"
    aggregate_id: int | str | None = None  # user_survey.id
    event: str = "SurveyResponseSubmitted"

    survey_id: int | None = None
    user_survey_id: int | None = None
    respondent_user_id: int | None = None
    score: int | None = None  # nullable for unscored quizzes
    submitted_at: datetime | None = None
