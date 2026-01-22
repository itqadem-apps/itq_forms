from __future__ import annotations

from typing import List, Optional

import strawberry
import strawberry_django
from strawberry import auto

from app.auth_utils import get_django_user
from user_surveys.models import UserAnswer, UserSurvey
from surveys.models import Question, Section
from .translations import QuestionTranslationType, SectionTranslationType
from .answer_schema import AnswerSchemaType
from .survey import UserAnswerType


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
    translations: List[SectionTranslationType]


@strawberry_django.type(Question)
class QuestionType:
    id: auto
    title: auto
    description: auto
    survey_id: auto
    section_id: auto
    section: "SectionType"
    order: auto
    is_required: auto
    type: auto
    cover_asset_id: auto
    created_at: auto
    updated_at: auto
    answer_schema: Optional[AnswerSchemaType]
    translations: List[QuestionTranslationType]

    @strawberry.field
    def answer_time(self) -> Optional[str]:
        value = self.__dict__.get("answer_time")
        if value is None:
            return None
        return str(value)

    @strawberry.field
    def next_question_id(self) -> Optional[int]:
        survey_id = self.survey_id or (self.section.survey_id if self.section_id else None)
        if not survey_id:
            return None
        ids = list(
            Question.objects.filter(survey_id=survey_id, section__isnull=False)
            .order_by("section__order", "order")
            .values_list("id", flat=True)
        )
        if not ids:
            return None
        try:
            idx = ids.index(self.id)
        except ValueError:
            return None
        return ids[idx + 1] if idx + 1 < len(ids) else None

    @strawberry.field
    def prev_question_id(self) -> Optional[int]:
        survey_id = self.survey_id or (self.section.survey_id if self.section_id else None)
        if not survey_id:
            return None
        ids = list(
            Question.objects.filter(survey_id=survey_id, section__isnull=False)
            .order_by("section__order", "order")
            .values_list("id", flat=True)
        )
        if not ids:
            return None
        try:
            idx = ids.index(self.id)
        except ValueError:
            return None
        return ids[idx - 1] if idx - 1 >= 0 else None

    @strawberry.field
    def user_answer(self, info, user_survey_id: Optional[int] = None) -> Optional[UserAnswerType]:
        django_user = get_django_user(info)
        if user_survey_id is None:
            user_survey_id = getattr(self, "_user_survey_id", None)
        if user_survey_id is None:
            return None
        assessment = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not assessment:
            return None
        return UserAnswer.objects.filter(user_survey=assessment, question_id=self.id).first()

    @strawberry.field
    def progress(self, info, user_survey_id: Optional[int] = None) -> Optional[int]:
        django_user = get_django_user(info)
        if user_survey_id is None:
            user_survey_id = getattr(self, "_user_survey_id", None)
        if user_survey_id is None:
            return None
        assessment = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not assessment:
            return None
        total = Question.objects.filter(survey_id=assessment.survey_id, section__isnull=False).count()
        if total == 0:
            return 0
        answered = (
            UserAnswer.objects.filter(user_survey=assessment)
            .exclude(answer__isnull=True, selected_options__isnull=True)
            .values_list("question_id", flat=True)
            .distinct()
            .count()
        )
        return int((answered / total) * 100)
