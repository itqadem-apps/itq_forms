from __future__ import annotations

from typing import List, Optional

import strawberry
import strawberry_django
from strawberry import auto

from survey_collections.models import SurveyCollection
from .survey import UserSurveyClassificationType, UserSurveyRecommendationType


@strawberry_django.type(SurveyCollection)
class SurveyCollectionType:
    id: auto
    status: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto
    language: auto
    created_at: auto
    updated_at: auto
    deleted_at: auto
    category_id: auto
    price: auto
    sponsor: auto
    type: auto


@strawberry.type
class FacetValueGQL:
    value: str
    count: int


@strawberry.type
class FacetGQL:
    name: str
    values: List[FacetValueGQL]


@strawberry.type
class SurveyCollectionsResultsGQL:
    items: List[SurveyCollectionType]
    total: int
    facets: List[FacetGQL]


@strawberry.type
class FinishAssessmentResult:
    status: str
    score: Optional[int]
    evaluated_at: Optional[str]
    classifications: List[UserSurveyClassificationType]
    recommendations: List[UserSurveyRecommendationType]

@strawberry.type
class QuestionsFiltersGQL:
    question_ids: Optional[List[int]]
    section_id: Optional[int]
    is_required: Optional[bool]
    question_type: Optional[str]
    answered: Optional[bool]
