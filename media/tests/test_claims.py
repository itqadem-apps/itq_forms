"""Claim-on-attach: a GraphQL input takes a new asset id only when the caller
uploaded it through forms with the slot's profile and claimed it.

The resolvers are called with their decorators unwrapped, as in
tests/test_question_mutations.py: what is under test is the write.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import strawberry
from django.core.exceptions import ValidationError
from pkg_auth.authorization import AuthContext, OrgId, UserId

import surveys.schemas.schema  # noqa: F401  (resolves the mutation import cycle)
from media.models import UploadRecord
from survey_collections.inputs import SurveyCollectionInput
from survey_collections.schemas.mutations.collections import SurveyCollectionMutations
from surveys.inputs import AnswerSchemaOptionInput, QuestionInput, SectionInput, SurveyUpdateInput
from surveys.models import AnswerSchemaOption, Question, Section, Survey
from surveys.schemas.mutations.answer_schemas import AnswerSchemaMutations
from surveys.schemas.mutations.questions import QuestionMutations
from surveys.schemas.mutations.sections import SectionMutations
from surveys.schemas.mutations.surveys import SurveyMutations

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _resolver(cls, name):
    fn = getattr(cls, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _info(user):
    return SimpleNamespace(context=SimpleNamespace(
        identity=SimpleNamespace(subject_str=user.pk),
        auth_context=SimpleNamespace(organization_id=OrgId(ORG)),
    ))


def _claimed(user, profile="forms-item-image") -> str:
    asset = uuid.uuid4()
    UploadRecord.objects.create(session_id=uuid.uuid4(), owner=user.pk, profile=profile, attached_asset_id=asset)
    return str(asset)


def _update_question(user, question, value):
    return _resolver(QuestionMutations, "update_question")(
        QuestionMutations(), _info(user), id=question.pk, input=QuestionInput(cover_asset_id=value), django_user=None,
    )


def test_an_unclaimed_id_is_refused(user, question):
    with pytest.raises(ValidationError) as exc:
        _update_question(user, question, str(uuid.uuid4()))

    assert "cover_asset_id" in exc.value.message_dict
    assert Question.objects.get(pk=question.pk).cover_asset_id is None


def test_a_claimed_id_is_stored(user, question):
    asset = _claimed(user)

    _update_question(user, question, asset)

    assert Question.objects.get(pk=question.pk).cover_asset_id == asset


def test_an_id_another_user_claimed_is_refused(user, user2, question):
    asset = _claimed(user2)

    with pytest.raises(ValidationError):
        _update_question(user, question, asset)


def test_an_upload_started_but_never_attached_is_refused(user, question):
    UploadRecord.objects.create(session_id=uuid.uuid4(), owner=user.pk, profile="forms-item-image")

    with pytest.raises(ValidationError):
        _update_question(user, question, str(uuid.uuid4()))


def test_an_id_claimed_for_another_slot_is_refused(user, question):
    asset = _claimed(user, profile="forms-thumb")

    with pytest.raises(ValidationError):
        _update_question(user, question, asset)


def test_the_stored_id_is_grandfathered(user, question):
    Question.all_objects.filter(pk=question.pk).update(cover_asset_id="asset-legacy")
    question.refresh_from_db()

    _update_question(user, question, "asset-legacy")

    assert Question.objects.get(pk=question.pk).cover_asset_id == "asset-legacy"


def test_null_clears(user, question):
    Question.all_objects.filter(pk=question.pk).update(cover_asset_id="asset-legacy")
    question.refresh_from_db()

    _update_question(user, question, None)

    assert Question.objects.get(pk=question.pk).cover_asset_id is None


def test_create_question_refuses_an_unclaimed_id(user, section):
    with pytest.raises(ValidationError):
        _resolver(QuestionMutations, "create_question")(
            QuestionMutations(), _info(user), input=QuestionInput(title="Q", cover_asset_id=str(uuid.uuid4())),
            section_id=section.pk, django_user=None,
        )


def test_section_cover(user, survey, section):
    update = _resolver(SectionMutations, "update_section")
    with pytest.raises(ValidationError):
        update(SectionMutations(), _info(user), id=section.pk, input=SectionInput(cover_asset_id=str(uuid.uuid4())))
    with pytest.raises(ValidationError):
        _resolver(SectionMutations, "create_section")(
            SectionMutations(), _info(user), survey_id=survey.pk, input=SectionInput(cover_asset_id=str(uuid.uuid4())),
        )

    asset = _claimed(user)
    update(SectionMutations(), _info(user), id=section.pk, input=SectionInput(cover_asset_id=asset))
    assert Section.objects.get(pk=section.pk).cover_asset_id == asset


def test_option_image(user, options, answer_schema):
    update = _resolver(AnswerSchemaMutations, "update_answer_schema_option")
    with pytest.raises(ValidationError):
        update(AnswerSchemaMutations(), _info(user), id=options[0].pk,
               input=AnswerSchemaOptionInput(image_asset_id=str(uuid.uuid4())))
    with pytest.raises(ValidationError):
        _resolver(AnswerSchemaMutations, "create_answer_schema_option")(
            AnswerSchemaMutations(), _info(user), schema_id=answer_schema.pk,
            input=AnswerSchemaOptionInput(text="x", image_asset_id=str(uuid.uuid4())),
        )

    asset = _claimed(user)
    update(AnswerSchemaMutations(), _info(user), id=options[0].pk, input=AnswerSchemaOptionInput(image_asset_id=asset))
    assert AnswerSchemaOption.objects.get(pk=options[0].pk).image_asset_id == asset


def test_survey_artwork(user, survey, monkeypatch):
    from surveys.schemas.mutations import surveys as module

    monkeypatch.setattr(module, "ensure_in_org", lambda *a, **k: None)
    monkeypatch.setattr(module, "build_survey_payload_or_log", lambda *a, **k: None)
    update = _resolver(SurveyMutations, "update_survey")

    with pytest.raises(ValidationError) as exc:
        update(SurveyMutations(), _info(user), input=SurveyUpdateInput(id=survey.pk, thumb_id=str(uuid.uuid4())))
    assert "thumb_id" in exc.value.message_dict

    # A cover claimed as a thumb is not a cover.
    thumb = _claimed(user, profile="forms-thumb")
    with pytest.raises(ValidationError):
        update(SurveyMutations(), _info(user), input=SurveyUpdateInput(id=survey.pk, cover_id=thumb))

    update(SurveyMutations(), _info(user), input=SurveyUpdateInput(id=survey.pk, thumb_id=thumb))
    assert Survey.objects.get(pk=survey.pk).thumb_id == thumb


def test_collection_artwork(user, collection):
    update = _resolver(SurveyCollectionMutations, "update_survey_collection")

    with pytest.raises(ValidationError):
        update(SurveyCollectionMutations(), _info(user), id=collection.pk,
               input=SurveyCollectionInput(cover_id=str(uuid.uuid4())))
    # Create checks collections:create before claims, so this caller holds it.
    creator = SimpleNamespace(context=SimpleNamespace(
        identity=SimpleNamespace(subject_str=user.pk),
        auth_context=AuthContext(
            user_id=UserId(user.pk), organization_id=OrgId(ORG),
            role_names=frozenset(), perms=frozenset({"collections:create"}),
        ),
    ))
    with pytest.raises(ValidationError):
        _resolver(SurveyCollectionMutations, "create_survey_collection")(
            SurveyCollectionMutations(), creator, input=SurveyCollectionInput(thumb_id=str(uuid.uuid4())),
        )

    cover = _claimed(user, profile="forms-cover")
    update(SurveyCollectionMutations(), _info(user), id=collection.pk, input=SurveyCollectionInput(cover_id=cover))
    collection.refresh_from_db()
    assert collection.cover_id == cover


def test_input_types_still_take_bare_ids():
    """The GraphQL inputs are unchanged: the check is server-side."""
    assert QuestionInput(cover_asset_id="x").cover_asset_id == "x"
    assert SectionInput().cover_asset_id is strawberry.UNSET
