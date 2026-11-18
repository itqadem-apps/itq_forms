"""The server refuses members that break the rules in curriculum collections; course collections
keep their course exams (intake report #128, story curricula-order 2.2)."""

import uuid

import pytest
from django.utils.timezone import now

from conftest import ORG
from external_references.models import ExternalReference
from pkg_auth.authorization import AuthContext, OrgId, UserId
from survey_collections import rule_report
from survey_collections.models import CollectionMembership, SurveyCollection
from surveys.models import Survey
from tests.test_action_materials import _Context

pytestmark = pytest.mark.django_db

ONLY_CURRICULA = "Only curricula can be added to a collection."
ALREADY_ELSEWHERE = "This curriculum is already in another collection."

ADD = """
mutation ($collectionId: ID!, $surveyId: ID!) {
  addSurveyToCollection(collectionId: $collectionId, surveyId: $surveyId) {
    __typename
    ... on SurveyCollectionType { id }
    ... on OperationInfo { messages { message } }
  }
}
"""

CREATE = """
mutation ($input: SurveyCreateInput!) {
  createSurvey(input: $input) {
    __typename
    ... on SurveyPayload { survey { id } }
    ... on OperationInfo { messages { message } }
  }
}
"""

PERMS = frozenset({
    "surveys:update", "assessments:update", "curriculums:update", "exams:update", "forms:update",
    "exams:create",
})


class _AdminContext(_Context):
    def __init__(self, user):
        super().__init__(user)
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(ORG),
            role_names=frozenset({"org-admin"}),
            perms=PERMS,
        )


def _execute(user, document, variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(document, variable_values=variables, context_value=_AdminContext(user))
    assert result.errors is None, result.errors
    return result.data


def _add(user, collection, survey):
    return _execute(user, ADD, {"collectionId": str(collection.id), "surveyId": str(survey.id)})["addSurveyToCollection"]


def _survey(survey_type="curriculum"):
    return Survey.objects.create(organization_id=ORG, survey_type=survey_type)


def _collection(*members, deleted=False, course=None, type=None):
    collection = SurveyCollection.objects.create(
        organization_id=ORG, type=type, deleted_at=now() if deleted else None
    )
    for survey in members:
        collection.append_member(survey)
    if course is not None:
        ExternalReference.objects.create(
            source_service="courses", source_model="course", source_id=str(course), collection=collection
        )
    return collection


def _course_collection(*members):
    return _collection(*members, course=uuid.uuid4().hex, type="exam")


def _members():
    return sorted(CollectionMembership._base_manager.values_list("id", "surveycollection_id", "survey_id", "order"))


def _refused_with(result, message):
    assert result["__typename"] == "OperationInfo"
    assert result["messages"][0]["message"] == message


@pytest.mark.parametrize("survey_type", ["exam", "form", "assessment", "survey", ""])
def test_a_non_curriculum_is_refused_and_nothing_stored(user, survey_type):
    collection = _collection(_survey())
    survey = _survey(survey_type)
    before = _members()

    if survey_type:
        _refused_with(_add(user, collection, survey), ONLY_CURRICULA)
    else:
        # A blank type has no permission key, so the existing permission check refuses it first.
        from surveys import schema as schema_module

        result = schema_module.schema.execute_sync(
            ADD,
            variable_values={"collectionId": str(collection.id), "surveyId": str(survey.id)},
            context_value=_AdminContext(user),
        )
        assert result.errors

    assert _members() == before


def test_a_curriculum_in_another_live_collection_is_refused_and_nothing_stored(user):
    shared = _survey()
    _collection(shared)
    second = _collection(_survey())
    before = _members()

    _refused_with(_add(user, second, shared), ALREADY_ELSEWHERE)

    assert _members() == before


def test_a_curriculum_in_no_collection_is_appended_last(user):
    first = _survey()
    collection = _collection(first)
    new = _survey()

    assert _add(user, collection, new)["__typename"] == "SurveyCollectionType"

    assert list(
        CollectionMembership.objects.filter(surveycollection=collection).order_by("order").values_list("survey_id", "order")
    ) == [(first.id, 0), (new.id, 1)]


@pytest.mark.parametrize("elsewhere", ["deleted", "course"])
def test_links_to_deleted_or_course_collections_do_not_count(user, elsewhere):
    curriculum = _survey()
    if elsewhere == "deleted":
        _collection(curriculum, deleted=True)
    else:
        _course_collection(curriculum)
    collection = _collection()

    assert _add(user, collection, curriculum)["__typename"] == "SurveyCollectionType"

    assert CollectionMembership.objects.filter(surveycollection=collection, survey=curriculum).exists()


@pytest.mark.parametrize("survey_type", ["exam", "curriculum"])
def test_re_adding_a_member_is_a_no_op_not_a_refusal(user, survey_type):
    # An existing rule-breaker (an exam, or a curriculum also in another collection) stays and is not refused.
    member = _survey(survey_type)
    _collection(member)
    collection = _collection(_survey())
    CollectionMembership.objects.create(surveycollection=collection, survey=member, order=1)
    before = _members()

    assert _add(user, collection, member)["__typename"] == "SurveyCollectionType"

    assert _members() == before


@pytest.mark.parametrize("survey_type", ["exam", "form", "curriculum"])
def test_a_course_collection_takes_any_survey(user, survey_type):
    survey = _survey(survey_type)
    if survey_type == "curriculum":
        _collection(survey)
    collection = _course_collection(_survey("exam"))

    assert _add(user, collection, survey)["__typename"] == "SurveyCollectionType"

    assert CollectionMembership.objects.filter(surveycollection=collection, survey=survey).exists()


def test_an_exam_type_collection_without_a_courses_reference_is_not_a_course_collection(user):
    collection = _collection(type="exam")
    other = _collection(_survey(), type="exam")
    ExternalReference.objects.create(source_service="articles", source_model="course", source_id="1", collection=other)
    exam = _survey("exam")

    _refused_with(_add(user, collection, exam), ONLY_CURRICULA)
    _refused_with(_add(user, other, exam), ONLY_CURRICULA)

    assert not CollectionMembership.objects.filter(survey=exam).exists()


def test_create_survey_adds_the_course_exam_to_its_course_collection(user):
    collection = _collection(_survey("exam"), course="course-1", type="exam")

    created = _execute(user, CREATE, {"input": {
        "surveyType": "exam",
        "externalReference": {"sourceService": "courses", "sourceModel": "course", "sourceId": "course-1"},
    }})["createSurvey"]

    assert created["__typename"] == "SurveyPayload", created
    assert CollectionMembership.objects.filter(
        surveycollection=collection, survey_id=int(created["survey"]["id"])
    ).exists()


def test_existing_rule_breakers_stay_listed(user):
    exam = _survey("exam")
    collection = _collection(_survey(), exam)

    curriculum = collection.assessments.exclude(pk=exam.pk).get()

    _refused_with(_add(user, collection, _survey("form")), ONLY_CURRICULA)

    assert set(collection.assessments.values_list("id", flat=True)) == {curriculum.id, exam.id}


def test_the_readers_skip_course_collection_members():
    shared = _survey()
    course = _course_collection(_survey("exam"), _survey("form"), shared)
    _collection(shared)
    breaker = _survey("exam")
    plain = _collection(breaker)

    found = rule_report.find()
    for scope in (found.all, found.shown):
        assert scope.not_curricula == {"exam": 1}
        assert scope.shared_curricula == []
    assert [(b.collection_id, b.survey_id) for b in rule_report.find_not_curricula()] == [(plain.id, breaker.id)]

    lines = rule_report.apply()

    assert "removed: 1" in lines
    assert CollectionMembership.objects.filter(surveycollection=course).count() == 3


def test_the_readers_count_a_curriculum_shared_by_two_curriculum_collections():
    # The scope narrows the rule; it does not drop it.
    shared = _survey()
    _collection(shared)
    _collection(shared)

    assert rule_report.find().all.shared_curricula == [shared.id]


def test_course_collection_ids_need_a_courses_reference_with_a_collection():
    course = _course_collection()
    _collection(type="exam")
    ExternalReference.objects.create(source_service="courses", source_model="exam", source_id="9", survey=_survey("exam"))

    assert rule_report.course_collection_ids() == {course.id}


@pytest.mark.parametrize("name", ["0017_report_rule_breaking_members", "0018_remove_non_curriculum_members"])
def test_the_rule_migrations_read_the_historical_references(name):
    from django.db.migrations.loader import MigrationLoader
    from django.test import override_settings

    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)

    assert ("external_references", "0001_initial") in loader.get_migration("survey_collections", name).dependencies


def test_refusal_names_a_blank_type_not_a_curriculum():
    # The GraphQL path stops a blank type at the permission check; the rule itself still refuses it.
    assert rule_report.refusal(_collection(_survey()), _survey("")) == ONLY_CURRICULA


def test_the_rule_migrations_leave_course_collections_alone(capsys):
    import importlib

    from django.apps import apps as django_apps

    course_exam, plain_exam = _survey("exam"), _survey("exam")
    course = _course_collection(_survey(), course_exam)
    plain = _collection(_survey(), plain_exam)

    importlib.import_module("survey_collections.migrations.0017_report_rule_breaking_members").forwards(django_apps, None)
    report = capsys.readouterr().out
    importlib.import_module("survey_collections.migrations.0018_remove_non_curriculum_members").forwards(django_apps, None)
    applied = capsys.readouterr().out

    for scope in ("all", "shown"):
        assert f"collection-rules: {scope}: not curricula: 1\n" in report
        assert f"collection-rules: {scope}: exam: 1\n" in report
    assert f"collection-rules: removed: collection {plain.id} survey {plain_exam.id} order 1 (exam)" in applied
    assert "collection-rules: removed: 1\n" in applied
    assert CollectionMembership.objects.filter(surveycollection=course, survey=course_exam).exists()
    assert not CollectionMembership.objects.filter(surveycollection=plain, survey=plain_exam).exists()
