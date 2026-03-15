from __future__ import annotations

from typing import List

import strawberry

from .user_survey import UserSurveyType


@strawberry.type
class UserSurveysResultsGQL:
    items: List[UserSurveyType]
    total: int
