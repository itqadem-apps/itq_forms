"""Register user_surveys domain events against their subject tokens."""
from __future__ import annotations

from app.messaging.subjects import register
from user_surveys.events import SurveyResponseSubmitted

register(SurveyResponseSubmitted, "survey.response.submitted")
