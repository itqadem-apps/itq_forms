from __future__ import annotations

from typing import List

import strawberry

from .common import FacetGQL
from .survey import SurveyType, UserSurveyType
from .content import QuestionType


@strawberry.type
class SurveyResultsGQL:
    items: List[SurveyType]
    total: int
    facets: List[FacetGQL]


@strawberry.type
class QuestionsResultsGQL:
    items: List[QuestionType]
    total: int


@strawberry.type
class UserSurveysResultsGQL:
    items: List[UserSurveyType]
    total: int
