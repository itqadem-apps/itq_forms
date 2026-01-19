from collections import Counter

from django.shortcuts import get_object_or_404
from django.utils.timezone import now

from .models import (
    UserAnswer,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)
from surveys.models import Question, Survey


def enroll_user_in_assessment(request_user, survey_id, child_id=None):
    """
    Enroll the given user into a survey (assessment).
    Returns (user_assessment, created) where created is False if an open enrollment already exists.
    """
    survey = get_object_or_404(Survey, id=survey_id)

    if getattr(survey, "is_for_child", False):
        if not child_id:
            raise ValueError("child_id is required for this survey.")
        child = str(child_id)
    else:
        child = None

    existing = UserSurvey.objects.filter(
        user=request_user,
        survey=survey,
        child_id=child,
        submitted_at__isnull=True,
    ).first()
    if existing:
        return existing, False

    user_assessment = UserSurvey.objects.create(
        user=request_user,
        survey=survey,
        child_id=child,
    )
    return user_assessment, True


def _evaluate_answer(assessment: Survey, answer: UserAnswer) -> tuple[int, list, list]:
    selected = list(answer.selected_options.all())
    if not selected:
        return 0, [], []

    score = 0
    if assessment.use_score:
        if answer.type in (
            Question.QUESTION_TYPE_RADIO_MCQ,
            Question.QUESTION_TYPE_DROPDOWN_MCQ,
        ):
            score = selected[0].score or 0
        elif answer.type in (
            Question.QUESTION_TYPE_CHECKBOX_MCQ,
            Question.QUESTION_TYPE_RADIO_GRID,
            Question.QUESTION_TYPE_CHECKBOX_GRID,
        ):
            score = sum(opt.score or 0 for opt in selected)

    classifications = []
    if assessment.use_classifications:
        if answer.type in (
            Question.QUESTION_TYPE_RADIO_MCQ,
            Question.QUESTION_TYPE_DROPDOWN_MCQ,
        ):
            classifications = [selected[0].classification] if selected[0].classification else []
        else:
            classifications = [opt.classification for opt in selected if opt.classification]

    recommendations = []
    if assessment.use_recommendations:
        for opt in selected:
            recommendations.extend(list(opt.option_recommendations.all()))

    return score, classifications, recommendations


def evaluate_assessment(user_assessment: UserSurvey) -> None:
    assessment = user_assessment.survey
    if not assessment:
        return

    total_score = 0
    classifications = []
    recommendations = []
    answers = user_assessment.useranswer_set.exclude(question__section__isnull=True)
    for answer in answers:
        score, answer_classifications, answer_recommendations = _evaluate_answer(assessment, answer)
        total_score += score
        classifications.extend(answer_classifications)
        recommendations.extend(answer_recommendations)

    if assessment.use_score:
        user_assessment.score = total_score
    user_assessment.evaluated_at = now()
    user_assessment.save(update_fields=["score", "evaluated_at"])

    if assessment.use_classifications:
        filtered = [c for c in classifications if c is not None]
        if filtered:
            counts = Counter(c.id for c in filtered)
            sorted_classifications = sorted(set(filtered), key=lambda c: counts[c.id])
            user_assessment.usersurveyclassification_set.all().delete()
            for classification in sorted_classifications:
                UserSurveyClassification.objects.create(
                    user_survey=user_assessment,
                    classification=classification,
                    count=counts[classification.id],
                )

    if assessment.use_recommendations:
        filtered = [r for r in recommendations if r is not None]
        if filtered:
            counts = Counter(r.id for r in filtered)
            sorted_recommendations = sorted(set(filtered), key=lambda r: counts[r.id])
            user_assessment.usersurveyrecommendation_set.all().delete()
            for recommendation in sorted_recommendations:
                UserSurveyRecommendation.objects.create(
                    user_survey=user_assessment,
                    recommendation=recommendation,
                    count=counts[recommendation.id],
                )


def finish_assessment(user_assessment: UserSurvey) -> None:
    assessment = user_assessment.survey
    if not assessment:
        raise ValueError("Assessment not found.")

    required_questions = assessment.questions.filter(is_required=True, section__isnull=False)
    if required_questions.exists():
        required_ids = set(required_questions.values_list("id", flat=True))
        answered_ids = set(
            user_assessment.useranswer_set.filter(question_id__in=required_ids)
            .exclude(answer__isnull=True, selected_options__isnull=True)
            .values_list("question_id", flat=True)
        )
        missing = required_ids - answered_ids
        if missing:
            raise ValueError("You must answer all required questions before finishing the assessment.")

    user_assessment.last_question = None
    user_assessment.submitted_at = now()
    user_assessment.save(update_fields=["last_question", "submitted_at"])

    if assessment.evaluation_type == Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION:
        evaluate_assessment(user_assessment)
