import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from external_references.consumer import (
    handle_external_enrollment_event,
    handle_external_reference_event,
)
from external_references.models import ExternalReference
from surveys.models import Usage


User = get_user_model()


def test_external_reference_requires_local_target():
    reference = ExternalReference(
        source_service="courses",
        source_model="lesson",
        source_id="lesson-1",
    )

    with pytest.raises(ValidationError):
        reference.full_clean()


def test_external_reference_create_with_survey(survey):
    reference = ExternalReference.objects.create(
        source_service="courses",
        source_model="lesson",
        source_id="lesson-1",
        survey=survey,
    )

    assert reference.pk is not None
    assert str(reference) == "courses:lesson:lesson-1"


def test_external_reference_create_with_collection(collection):
    reference = ExternalReference.objects.create(
        source_service="courses",
        source_model="course",
        source_id="course-1",
        collection=collection,
    )

    assert reference.collection == collection
    assert reference.survey is None


def test_handle_external_reference_event_creates_reference_from_subject(survey, collection):
    async_to_sync(handle_external_reference_event)(
        {
            "source_model": "lesson",
            "source_id": "lesson-1",
            "collection_id": collection.id,
            "survey_id": survey.id,
            "data": {"title": "Quiz lesson"},
        },
        "courses.external_reference",
    )

    reference = ExternalReference.objects.get(
        source_service="courses",
        source_model="lesson",
        source_id="lesson-1",
        survey=survey,
        collection=collection,
    )
    assert reference.data == {"title": "Quiz lesson"}


def test_handle_external_reference_event_updates_existing_reference(survey):
    ExternalReference.objects.create(
        source_service="courses",
        source_model="lesson",
        source_id="lesson-1",
        survey=survey,
        data={"title": "Old"},
    )

    async_to_sync(handle_external_reference_event)(
        {
            "source_model": "lesson",
            "source_id": "lesson-1",
            "survey_id": survey.id,
            "data": {"title": "New"},
        },
        "courses.external_reference",
    )

    assert ExternalReference.objects.count() == 1
    assert ExternalReference.objects.get().data == {"title": "New"}


def test_handle_external_reference_event_skips_missing_source_identity(survey):
    async_to_sync(handle_external_reference_event)(
        {"source_id": "lesson-1", "survey_id": survey.id},
        "courses.external_reference",
    )

    assert ExternalReference.objects.count() == 0


def test_handle_external_reference_event_skips_missing_local_target():
    async_to_sync(handle_external_reference_event)(
        {"source_model": "lesson", "source_id": "lesson-1"},
        "courses.external_reference",
    )

    assert ExternalReference.objects.count() == 0


def test_handle_external_reference_event_skips_missing_local_survey():
    async_to_sync(handle_external_reference_event)(
        {"source_model": "lesson", "source_id": "lesson-1", "survey_id": 999999},
        "courses.external_reference",
    )

    assert ExternalReference.objects.count() == 0


def test_handle_external_enrollment_event_grants_usage_from_reference(survey, collection):
    ExternalReference.objects.create(
        source_service="courses",
        source_model="lesson",
        source_id="lesson-1",
        survey=survey,
        collection=collection,
    )

    async_to_sync(handle_external_enrollment_event)(
        {
            "source_model": "lesson",
            "source_id": "lesson-1",
            "user_id": "kc-external-user",
            "usage_limit": 2,
            "enrollment_id": "enrollment-1",
        },
        "courses.external_enrollment",
    )

    usage = Usage.objects.get(
        user_id="kc-external-user",
        survey=survey,
        collection=collection,
        order_id="courses:enrollment-1",
    )
    assert usage.usage_limit == 2
    assert usage.used_count == 0
    assert User.objects.filter(id="kc-external-user").exists()


def test_handle_external_enrollment_event_updates_repeated_grant(survey):
    ExternalReference.objects.create(
        source_service="courses",
        source_model="lesson",
        source_id="lesson-1",
        survey=survey,
    )

    event = {
        "source_model": "lesson",
        "source_id": "lesson-1",
        "user_id": "kc-external-user",
        "usage_limit": 1,
        "enrollment_id": "enrollment-1",
    }
    async_to_sync(handle_external_enrollment_event)(event, "courses.external_enrollment")
    event["usage_limit"] = 3
    async_to_sync(handle_external_enrollment_event)(event, "courses.external_enrollment")

    assert Usage.objects.count() == 1
    assert Usage.objects.get().usage_limit == 3


def test_handle_external_enrollment_event_skips_without_reference():
    async_to_sync(handle_external_enrollment_event)(
        {
            "source_model": "lesson",
            "source_id": "missing",
            "user_id": "kc-external-user",
        },
        "courses.external_enrollment",
    )

    assert Usage.objects.count() == 0


def test_handle_external_enrollment_event_skips_collection_only_reference(collection):
    ExternalReference.objects.create(
        source_service="courses",
        source_model="course",
        source_id="course-1",
        collection=collection,
    )

    async_to_sync(handle_external_enrollment_event)(
        {
            "source_model": "course",
            "source_id": "course-1",
            "user_id": "kc-external-user",
        },
        "courses.external_enrollment",
    )

    assert Usage.objects.count() == 0


