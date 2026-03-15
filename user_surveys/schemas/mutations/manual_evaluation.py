from typing import Optional

import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction

from app.auth_utils import with_django_user
from user_surveys.models import (
    UserAction,
    UserAnswer,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)
from user_surveys.services import evaluate_assessment
from user_surveys.types import FinishAssessmentResult
from user_surveys.types.user_survey import UserAnswerType
from ..common import RequireAuth


@strawberry.input
class ScoreAnswerInput:
    answer_id: int
    score: int


@strawberry.type
class ManualEvaluationMutation:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def score_answer(
        self,
        info: Info,
        user_survey_id: int,
        answer_id: int,
        score: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserAnswerType:
        """Set the score for a single answer (admin review)."""
        user_answer = UserAnswer.objects.filter(
            id=answer_id,
            user_survey_id=user_survey_id,
        ).first()
        if not user_answer:
            raise ValidationError("Answer not found.")

        user_survey = user_answer.user_survey
        if not user_survey.submitted_at:
            raise ValidationError("Assessment has not been submitted yet.")

        user_answer.score = score
        user_answer.save(update_fields=["score"])
        return user_answer

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def score_answers_batch(
        self,
        info: Info,
        user_survey_id: int,
        scores: list[ScoreAnswerInput],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> list[UserAnswerType]:
        """Set scores for multiple answers at once (admin review)."""
        user_survey = UserSurvey.objects.filter(id=user_survey_id).first()
        if not user_survey:
            raise ValidationError("Assessment not found.")
        if not user_survey.submitted_at:
            raise ValidationError("Assessment has not been submitted yet.")

        answer_ids = [s.answer_id for s in scores]
        answers = {
            a.id: a
            for a in UserAnswer.objects.filter(
                id__in=answer_ids, user_survey_id=user_survey_id
            )
        }

        missing = set(answer_ids) - set(answers.keys())
        if missing:
            raise ValidationError(f"Answers not found: {missing}")

        with transaction.atomic():
            for s in scores:
                answer = answers[s.answer_id]
                answer.score = s.score
            UserAnswer.objects.bulk_update(answers.values(), ["score"])

        return list(answers.values())

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def evaluate_manual_assessment(
        self,
        info: Info,
        user_survey_id: int,
        score_override: Optional[int] = None,
        action_id_override: Optional[int] = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> FinishAssessmentResult:
        """Trigger evaluation for a manually-evaluated assessment.

        1. Aggregates per-answer scores, classifications, and recommendations
           using the same logic as automatic evaluation.
        2. If score_override is provided, replaces the aggregated score.
        3. If action_id_override is provided, uses that action instead of
           score-range matching.
        """
        user_survey = UserSurvey.objects.filter(id=user_survey_id).first()
        if not user_survey:
            raise ValidationError("Assessment not found.")
        if not user_survey.submitted_at:
            raise ValidationError("Assessment has not been submitted yet.")

        with transaction.atomic():
            # Run standard evaluation (aggregates scores, classifications, etc.)
            evaluate_assessment(user_survey)

            # Apply overrides
            update_fields = []
            if score_override is not None:
                user_survey.score = score_override
                update_fields.append("score")
            if action_id_override is not None:
                action = UserAction.objects.filter(
                    id=action_id_override,
                    user_survey=user_survey,
                ).first()
                if not action:
                    raise ValidationError("Action not found for this assessment.")
                user_survey.action = action
                update_fields.append("action")
            if update_fields:
                user_survey.save(update_fields=update_fields)

        user_survey.refresh_from_db()
        return FinishAssessmentResult(
            status="evaluated",
            score=user_survey.score,
            evaluated_at=user_survey.evaluated_at.isoformat() if user_survey.evaluated_at else None,
            classifications=list(user_survey.usersurveyclassification_set.all()),
            recommendations=list(user_survey.usersurveyrecommendation_set.all()),
        )
