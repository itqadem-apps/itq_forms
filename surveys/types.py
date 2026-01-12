from __future__ import annotations

from typing import List

import strawberry
import strawberry_django
from strawberry import auto


from .models import Question, Section, Survey
from user_surveys.models import UserAssessment


@strawberry_django.type(Survey)
class SurveyType:
    id: auto
    title: auto
    description: auto
    short_description: auto
    language: auto
    status_id: auto
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
    category_id: auto
    sponsor: auto
    price: auto
    created_at: auto
    updated_at: auto
    sections: List["SectionType"]

    @strawberry.field
    def status(self) -> str | None:
        return self.status.status if self.status_id else None


@strawberry_django.type(Section)
class SectionType:
    id: auto
    title: auto
    description: auto
    survey_id: auto
    order: auto
    is_hidden: auto
    cover_asset_id: auto
    created_at: auto
    updated_at: auto
    questions: List["QuestionType"]


@strawberry_django.type(Question)
class QuestionType:
    id: auto
    title: auto
    description: auto
    survey_id: auto
    section_id: auto
    order: auto
    is_required: auto
    type: auto
    cover_asset_id: auto
    created_at: auto
    updated_at: auto

    @strawberry.field
    def answer_time(self) -> str | None:
        value = self.__dict__.get("answer_time")
        if value is None:
            return None
        return str(value)


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


@strawberry_django.type(UserAssessment)
class UserAssessmentType:
    id: auto
    is_paid: auto
    survey_id: auto
    user_id: auto
    child_id: auto
    count_of_ending_options: auto
    evaluated_at: auto
    submitted_at: auto
    score: auto
    progress: auto
    last_question_id: auto
    action_id: auto
