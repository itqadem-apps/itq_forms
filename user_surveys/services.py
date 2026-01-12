from django.shortcuts import get_object_or_404

from .models import UserAssessment
from surveys.models import Survey
from user_surveys.models import UserAssessment as AssessmentModel  # alias if needed for clarity


def enroll_user_in_assessment(request_user, survey_id, child_id=None):
    """
    Enroll the given user into a survey (assessment).
    Returns (user_assessment, created) where created is False if an open enrollment already exists.
    """
    survey = get_object_or_404(Survey, id=survey_id)

    if getattr(survey, "assignable_to_user", False):
        if not child_id:
            raise ValueError("child_id is required for this survey.")

        # In this codebase we store child_id as a string on UserAssessment; no Child model present.
        child = str(child_id)

        existing = UserAssessment.objects.filter(
            user=request_user,
            survey=survey,
            child_id=child,
            submitted_at__isnull=True,
        ).first()
        if existing:
            return existing, False

        user_assessment = UserAssessment.objects.create(
            user=request_user,
            survey=survey,
            child_id=child,
        )
        return user_assessment, True

    existing = UserAssessment.objects.filter(
        user=request_user,
        survey=survey,
        child_id__isnull=True,
        submitted_at__isnull=True,
    ).first()
    if existing:
        return existing, False

    user_assessment = UserAssessment.objects.create(
        user=request_user,
        survey=survey,
    )
    return user_assessment, True
