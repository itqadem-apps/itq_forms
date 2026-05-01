from asgiref.sync import async_to_sync

from app.messaging.handlers.courses_events import handle_courses_event
from external_references.courses import (
    handle_course_created,
    handle_course_deleted,
    handle_course_updated,
)
from external_references.models import ExternalReference
from survey_collections.models import SurveyCollection


def _payload(course_id="course-1", *, title="Algebra 101", **extra):
    """Build a courses-service event envelope (matches the service contract)."""
    payload = {
        "event": "CourseCreated",
        "aggregate_type": "course",
        "aggregate_id": course_id,
        "course": {
            "id": course_id,
            "title": title,
            "language": "en",
            "description": "Intro algebra course",
            "summary": "Algebra short",
        },
    }
    payload.update(extra)
    return payload


def test_course_created_creates_collection_and_reference():
    handle_course_created(_payload())

    ref = ExternalReference.objects.get(
        source_service="courses", source_model="course", source_id="course-1"
    )
    assert ref.collection is not None
    assert ref.collection.type == "exam"
    assert ref.collection.status == SurveyCollection.STATUS_DRAFT
    assert ref.data["aggregate_id"] == "course-1"
    assert ref.data["course"]["title"] == "Algebra 101"
    translation = ref.collection.translations.get(language="en")
    assert translation.title == "Algebra 101"


def test_course_created_accepts_flat_payload_without_envelope():
    handle_course_created({"id": "flat-1", "title": "Flat Course"})

    ref = ExternalReference.objects.get(source_id="flat-1")
    assert ref.collection.translations.get(language="en").title == "Flat Course"


def test_course_created_is_idempotent():
    handle_course_created(_payload())
    handle_course_created(_payload())

    assert ExternalReference.objects.count() == 1
    assert SurveyCollection.objects.count() == 1


def test_course_created_refreshes_data_on_repeat():
    handle_course_created(_payload(title="Old"))
    handle_course_created(_payload(title="New"))

    ref = ExternalReference.objects.get(source_id="course-1")
    assert ref.data["course"]["title"] == "New"
    assert ref.collection.translations.get(language="en").title == "New"


def test_course_updated_updates_existing_reference():
    handle_course_created(_payload(title="Initial"))
    handle_course_updated(_payload(title="Renamed"))

    ref = ExternalReference.objects.get(source_id="course-1")
    assert ref.data["course"]["title"] == "Renamed"
    assert ref.collection.translations.get(language="en").title == "Renamed"


def test_course_updated_creates_when_missing():
    handle_course_updated(_payload())

    assert ExternalReference.objects.filter(source_id="course-1").exists()
    assert SurveyCollection.objects.count() == 1


def test_course_deleted_drops_collection_and_reference():
    handle_course_created(_payload())
    handle_course_deleted(_payload())

    assert not ExternalReference.objects.filter(source_id="course-1").exists()
    assert SurveyCollection.objects.count() == 0


def test_course_deleted_is_safe_when_missing():
    handle_course_deleted(_payload())  # should not raise

    assert SurveyCollection.objects.count() == 0


def test_dispatch_routes_subject_to_correct_handler():
    async_to_sync(handle_courses_event)(_payload(), "courses.course.created")
    assert ExternalReference.objects.count() == 1

    async_to_sync(handle_courses_event)(_payload(title="Updated"), "courses.course.updated")
    ref = ExternalReference.objects.get(source_id="course-1")
    assert ref.data["course"]["title"] == "Updated"

    async_to_sync(handle_courses_event)(_payload(), "courses.course.deleted")
    assert ExternalReference.objects.count() == 0


def test_dispatch_ignores_unrelated_subject():
    async_to_sync(handle_courses_event)(_payload(), "courses.lesson.created")
    assert ExternalReference.objects.count() == 0


def test_missing_id_is_skipped():
    handle_course_created({"course": {"title": "no id"}})
    assert ExternalReference.objects.count() == 0
