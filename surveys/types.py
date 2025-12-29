from __future__ import annotations

from typing import List

import strawberry
import strawberry_django
from strawberry import auto


from .models import Survey


@strawberry_django.type(Survey)
class SurveyType:
    id: auto
    title: auto
    description: auto
    short_description: auto
    language: auto
    status_id: auto
    sponsor_id: auto
    assessment_type: auto
    display_option: auto
    is_timed: auto
    assignable_to_user: auto
    is_evaluable: auto
    evaluation_type: auto
    use_score: auto
    use_classifications: auto
    use_recommendations: auto
    use_actions: auto
    allow_end_based_on_answer_repeat: auto
    answers_count_to_end: auto
    end_based_on_answer_repeat_in_row: auto
    allow_update_answer_options_scores_based_on_classification: auto
    allow_update_answer_options_text_based_on_classification: auto
    create_option_for_each_classification: auto
    created_at: auto
    updated_at: auto
    content_type_id: auto
    object_id: auto

    @strawberry.field
    def status(self) -> str | None:
        return self.status.status if self.status_id else None


@strawberry.type
class FacetValueGQL:
    value: str
    count: int


@strawberry.type
class FacetGQL:
    name: str
    values: List[FacetValueGQL]


@strawberry.type
class SurveyResultsGQL:
    items: List[SurveyType]
    total: int
    facets: List[FacetGQL]
