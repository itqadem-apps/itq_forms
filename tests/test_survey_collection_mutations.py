"""Tests for the survey collection create/update mutation resolvers.

The category branch is the point of interest: an omitted `category_id` must
leave the FK untouched, while an explicit `null` must clear it — the same
contract `update_survey` already honours.
"""
import os
import uuid

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

import surveys.schemas.schema  # noqa: F401  (resolves the mutation import cycle)
from django.core.exceptions import ObjectDoesNotExist

from survey_collections.inputs import SurveyCollectionInput
from survey_collections.models import SurveyCollection
from survey_collections.schemas.mutations.collections import SurveyCollectionMutations


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user):
        self.identity = _Identity(user)


class _Info:
    def __init__(self, user):
        self.context = _Context(user)


def _resolver(name):
    for field in SurveyCollectionMutations.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _create(user, **kwargs):
    return _resolver("create_survey_collection")(
        SurveyCollectionMutations(), _Info(user), input=SurveyCollectionInput(**kwargs)
    )


def _update(user, collection_id, **kwargs):
    return _resolver("update_survey_collection")(
        SurveyCollectionMutations(),
        _Info(user),
        id=collection_id,
        input=SurveyCollectionInput(**kwargs),
    )


class TestSurveyCollectionCategory:
    def test_create_with_category(self, user, category):
        collection = _create(user, status="draft", category_id=str(category.category_id))
        assert collection.category_id == category.category_id

    def test_create_with_explicit_null_category(self, user):
        collection = _create(user, status="draft", category_id=None)
        assert collection.category_id is None

    def test_create_with_unknown_category_raises(self, user):
        with pytest.raises(ObjectDoesNotExist):
            _create(user, status="draft", category_id=str(uuid.uuid4()))

    def test_update_explicit_null_clears_category(self, user, collection, category):
        collection.category = category
        collection.save()

        _update(user, collection.id, category_id=None)

        collection.refresh_from_db()
        assert collection.category_id is None

    def test_update_omitted_category_leaves_it_unchanged(self, user, collection, category):
        collection.category = category
        collection.save()

        _update(user, collection.id, status=SurveyCollection.STATUS_DRAFT)

        collection.refresh_from_db()
        assert collection.category_id == category.category_id
        assert collection.status == SurveyCollection.STATUS_DRAFT

    def test_update_sets_category(self, user, collection, category):
        _update(user, collection.id, category_id=str(category.category_id))

        collection.refresh_from_db()
        assert collection.category_id == category.category_id

    def test_update_unknown_category_raises(self, user, collection):
        with pytest.raises(ObjectDoesNotExist):
            _update(user, collection.id, category_id=str(uuid.uuid4()))
