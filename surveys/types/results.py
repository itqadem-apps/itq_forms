from __future__ import annotations

from typing import List, Optional

import strawberry

from app.schema_common import CategoryFacetNodeGQL, FacetValueGQL
from .survey import SurveyType
from .content import QuestionType


@strawberry.type
class SurveysFacetsGQL:
    status: List[FacetValueGQL]
    survey_type: List[FacetValueGQL]
    categories: List[CategoryFacetNodeGQL]


@strawberry.type
class SurveyResultsGQL:
    items: List[SurveyType]
    total: int
    facets: Optional[SurveysFacetsGQL] = None


@strawberry.type
class QuestionsResultsGQL:
    items: List[QuestionType]
    total: int
