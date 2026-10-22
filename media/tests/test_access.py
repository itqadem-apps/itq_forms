"""`can_access`: who may open which forms asset through the resolve endpoints.

Runs on sqlite by default and on Postgres with `DATABASE_URL` set; the rule is
one UNION statement, so both backends must agree.
"""
from __future__ import annotations

import uuid

import pytest
from django.utils.timezone import now
from pkg_auth.authorization import MissingPermission, OrgId

from accounts.models import Child, ChildGuardian
from app.permissions import Permission
from media.access import Viewer, can_access
from surveys.models import AnswerSchemaOption, Question, Survey
from user_surveys.services import enroll_user_in_assessment

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _AuthContext:
    def __init__(self, organization_id, *permissions):
        self.organization_id = OrgId(organization_id)
        self._permissions = {p.value for p in permissions}

    def require(self, key):
        if key not in self._permissions:
            raise MissingPermission(key)


def _id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def assets(survey, section, question, options):
    ids = {name: _id() for name in ("thumb", "cover", "section", "question", "option", "foreign")}
    Survey.objects.filter(pk=survey.pk).update(thumb_id=ids["thumb"], cover_id=ids["cover"], is_for_child=False)
    section.cover_asset_id = ids["section"]
    section.save()
    Question.all_objects.filter(pk=question.pk).update(cover_asset_id=ids["question"])
    AnswerSchemaOption.all_objects.filter(pk=options[0].pk).update(image_asset_id=ids["option"])
    return ids


ITEMS = ("section", "question", "option")


def _items(assets):
    return {assets[k] for k in ITEMS}


def _publish(survey):
    Survey.objects.filter(pk=survey.pk).update(status=Survey.STATUS_PUBLISHED)


def test_anonymous_opens_artwork_but_not_a_drafts_items(assets):
    allowed = can_access(None, assets.values())

    assert allowed == {assets["thumb"], assets["cover"]}


def test_anonymous_opens_a_published_surveys_items(survey, assets):
    _publish(survey)

    assert can_access(None, assets.values()) == {assets[k] for k in ("thumb", "cover", *ITEMS)}


def test_an_id_forms_does_not_store_is_refused_to_everyone(survey, assets, user):
    _publish(survey)
    staff = Viewer(user.pk, _AuthContext(ORG, Permission.SURVEY_READ, Permission.SUBMISSION_READ))

    assert can_access(None, [assets["foreign"]]) == set()
    assert can_access(staff, [assets["foreign"]]) == set()


def test_a_deleted_survey_holds_nothing(survey, assets):
    _publish(survey)
    Survey.objects.filter(pk=survey.pk).update(deleted_at=now())

    assert can_access(None, assets.values()) == set()


def test_a_soft_deleted_question_is_not_public(survey, question, assets):
    _publish(survey)
    Question.all_objects.filter(pk=question.pk).update(deleted_at=now())

    assert assets["question"] not in can_access(None, assets.values())


def test_staff_open_their_organizations_drafts(assets, user):
    staff = Viewer(user.pk, _AuthContext(ORG, Permission.SURVEY_READ))

    assert _items(assets) <= can_access(staff, assets.values())


def test_staff_of_another_organization_do_not(assets, user):
    staff = Viewer(user.pk, _AuthContext(OTHER_ORG, Permission.SURVEY_READ))

    assert can_access(staff, assets.values()) & _items(assets) == set()


def test_staff_without_the_kinds_read_permission_do_not(assets, user):
    staff = Viewer(user.pk, _AuthContext(ORG, Permission.EXAM_READ))

    assert can_access(staff, assets.values()) & _items(assets) == set()


def test_a_signed_in_member_without_org_context_reads_as_the_public(assets, user):
    assert can_access(Viewer(user.pk), assets.values()) == {assets["thumb"], assets["cover"]}


def test_learner_keeps_their_snapshot_after_unpublish(survey, assets, user):
    _publish(survey)
    enroll_user_in_assessment(user, survey.id)
    Survey.objects.filter(pk=survey.pk).update(status=Survey.STATUS_DRAFT)

    assert _items(assets) <= can_access(Viewer(user.pk), assets.values())


def test_another_learners_snapshot_is_refused(survey, assets, user, user2):
    _publish(survey)
    enroll_user_in_assessment(user, survey.id)
    Survey.objects.filter(pk=survey.pk).update(status=Survey.STATUS_DRAFT)

    assert can_access(Viewer(user2.pk), assets.values()) & _items(assets) == set()


def _child_submission(survey, user, org):
    child = Child.objects.create(id=f"child-{uuid.uuid4().hex[:8]}", name="kid")
    ChildGuardian.objects.create(
        id=f"rel-{child.id}", child=child, user_id="staff-1", role="supervisor", status="active",
        organization_id=str(org),
    )
    Survey.objects.filter(pk=survey.pk).update(is_for_child=True)
    survey.refresh_from_db()
    enroll_user_in_assessment(user, survey.id, child=child)
    Survey.objects.filter(pk=survey.pk).update(status=Survey.STATUS_DRAFT, is_for_child=False)


def test_reviewers_open_snapshots_of_children_their_org_supervises(survey, assets, user, user2):
    _publish(survey)
    _child_submission(survey, user, ORG)
    # Another org's reviewer: no supervisor relation, no survey of theirs.
    outsider = Viewer(user2.pk, _AuthContext(OTHER_ORG, Permission.SUBMISSION_READ))
    reviewer = Viewer(user2.pk, _AuthContext(ORG, Permission.SUBMISSION_READ))

    assert can_access(outsider, assets.values()) & _items(assets) == set()
    assert _items(assets) <= can_access(reviewer, assets.values())


def test_ids_match_whatever_case_was_stored(survey, section, assets):
    _publish(survey)
    upper = _id().upper()
    section.cover_asset_id = upper
    section.save()

    assert can_access(None, [upper.lower()]) == {upper.lower()}
