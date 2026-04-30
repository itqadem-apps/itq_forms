"""Register survey domain events against their subject tokens."""

from __future__ import annotations

from app.messaging.subjects import register
from surveys.events import (
    SurveyCreated,
    SurveyDeleted,
    SurveyPublished,
    SurveyUnpublished,
    SurveyUpdated,
)

register(SurveyCreated, "survey.created")
register(SurveyUpdated, "survey.updated")
register(SurveyPublished, "survey.published")
register(SurveyUnpublished, "survey.unpublished")
register(SurveyDeleted, "survey.deleted")
