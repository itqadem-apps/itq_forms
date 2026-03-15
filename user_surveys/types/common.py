from __future__ import annotations

from typing import List, Optional

import strawberry

from .user_survey import UserSurveyClassificationType, UserSurveyRecommendationType


@strawberry.type
class FinishAssessmentResult:
    status: str
    score: Optional[int]
    evaluated_at: Optional[str]
    classifications: List[UserSurveyClassificationType]
    recommendations: List[UserSurveyRecommendationType]
