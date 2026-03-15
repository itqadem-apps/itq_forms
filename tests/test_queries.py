"""Tests for GraphQL queries via Django test client (POST to /api/v1/forms/graphql)."""
import json
import uuid

import pytest
from django.test import Client, RequestFactory

from surveys.models import (
    AnswerSchema,
    AnswerSchemaOption,
    Classification,
    Question,
    Section,
    Survey,
)
from survey_collections.models import SurveyCollection
from user_surveys.models import UserAnswer, UserSurvey
from user_surveys.services import enroll_user_in_assessment


def _gql(client, query, variables=None):
    """Helper: POST a GraphQL query and return parsed JSON."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = client.post(
        "/api/v1/forms/graphql",
        data=json.dumps(payload),
        content_type="application/json",
    )
    return resp.status_code, resp.json()


# ── surveys query ──────────────────────────────────────────────
class TestSurveysQuery:
    def test_surveys_empty(self):
        client = Client()
        status, data = _gql(client, """
            query {
                surveys(surveysListInput: { limit: 10, offset: 0 }) {
                    total
                    items { id }
                }
            }
        """)
        assert status == 200
        assert data["data"]["surveys"]["total"] == 0
        assert data["data"]["surveys"]["items"] == []

    def test_surveys_returns_created(self, survey):
        client = Client()
        status, data = _gql(client, """
            query {
                surveys(surveysListInput: { limit: 10, offset: 0 }) {
                    total
                    items { id surveyType translations { title } }
                }
            }
        """)
        assert status == 200
        result = data["data"]["surveys"]
        assert result["total"] >= 1
        titles = [item["translations"][0]["title"] if item["translations"] else None for item in result["items"]]
        assert "Test Survey" in titles

    def test_surveys_pagination(self):
        for i in range(5):
            Survey.objects.create()

        client = Client()
        status, data = _gql(client, """
            query {
                surveys(surveysListInput: { limit: 2, offset: 0 }) {
                    total
                    items { id }
                }
            }
        """)
        assert status == 200
        result = data["data"]["surveys"]
        assert result["total"] == 5
        assert len(result["items"]) == 2

    def test_surveys_offset(self):
        for i in range(5):
            Survey.objects.create()

        client = Client()
        status, data = _gql(client, """
            query {
                surveys(surveysListInput: { limit: 10, offset: 3 }) {
                    total
                    items { id }
                }
            }
        """)
        assert status == 200
        assert len(data["data"]["surveys"]["items"]) == 2

    def test_surveys_with_facets(self):
        s = Survey.objects.create(survey_type="survey", status="published")

        client = Client()
        status, data = _gql(client, """
            query {
                surveys(surveysListInput: { limit: 10, offset: 0 }) {
                    total
                    facets { name values { value count } }
                }
            }
        """)
        assert status == 200
        facets = data["data"]["surveys"]["facets"]
        facet_names = [f["name"] for f in facets]
        assert "survey_type" in facet_names
        assert "status" in facet_names

    def test_surveys_filter_by_type(self):
        Survey.objects.create(survey_type="survey")
        Survey.objects.create(survey_type="exam")
        client = Client()
        status, data = _gql(client, """
            query {
                surveys(surveysListInput: {
                    limit: 10, offset: 0,
                    filters: { surveyType: "exam" }
                }) {
                    total
                    items { surveyType }
                }
            }
        """)
        assert status == 200
        items = data["data"]["surveys"]["items"]
        assert all(item["surveyType"] == "exam" for item in items)


# ── survey (single) query ──────────────────────────────────────
class TestSurveyQuery:
    def test_survey_by_id(self, survey):
        client = Client()
        status, data = _gql(client, """
            query($id: Int!) {
                survey(id: $id) {
                    id
                    surveyType
                    displayOption
                    translations { title description }
                }
            }
        """, {"id": survey.pk})
        assert status == 200
        result = data["data"]["survey"]
        assert result["translations"][0]["title"] == "Test Survey"
        assert result["surveyType"] == "survey"

    def test_survey_not_found(self):
        client = Client()
        status, data = _gql(client, """
            query { survey(id: 999999) { id } }
        """)
        assert status == 200
        assert data["data"]["survey"] is None

    def test_survey_with_sections(self, survey, section):
        client = Client()
        status, data = _gql(client, """
            query($id: Int!) {
                survey(id: $id) {
                    id
                    sections { id title order }
                }
            }
        """, {"id": survey.pk})
        assert status == 200
        sections = data["data"]["survey"]["sections"]
        assert len(sections) == 1
        assert sections[0]["title"] == "Section 1"


# ── question/questions queries (require auth, tested via unauthenticated rejection) ──
class TestQuestionQuery:
    def test_question_requires_auth(self):
        """The question query requires authentication."""
        client = Client()
        status, data = _gql(client, """
            query {
                question(userSurveyId: 1) {
                    id
                    title
                }
            }
        """)
        assert status == 200
        # Should have an error (auth required)
        assert data.get("errors") is not None or data["data"]["question"] is None

    def test_questions_requires_auth(self):
        """The questions query requires authentication."""
        client = Client()
        status, data = _gql(client, """
            query {
                questions(userSurveyId: 1) {
                    total
                    items { id }
                }
            }
        """)
        assert status == 200
        assert data.get("errors") is not None


# ── collections query ──────────────────────────────────────────
class TestCollectionsQuery:
    def test_collections_empty(self):
        client = Client()
        status, data = _gql(client, """
            query {
                collections(collectionsListInput: { limit: 10, offset: 0 }) {
                    total
                    items { id title }
                }
            }
        """)
        assert status == 200
        assert data["data"]["collections"]["total"] == 0

    def test_collections_returns_created(self, collection):
        client = Client()
        status, data = _gql(client, """
            query {
                collections(collectionsListInput: { limit: 10, offset: 0 }) {
                    total
                    items { id title status }
                }
            }
        """)
        assert status == 200
        result = data["data"]["collections"]
        assert result["total"] >= 1

    def test_collections_pagination(self):
        for i in range(5):
            SurveyCollection.objects.create(title=f"Collection {i}")
        client = Client()
        status, data = _gql(client, """
            query {
                collections(collectionsListInput: { limit: 2, offset: 0 }) {
                    total
                    items { id }
                }
            }
        """)
        assert status == 200
        assert data["data"]["collections"]["total"] == 5
        assert len(data["data"]["collections"]["items"]) == 2


# ── Health endpoints ────────────────────────────────────────────
class TestHealthEndpoints:
    def test_healthz(self):
        client = Client()
        resp = client.get("/healthz/")
        assert resp.status_code == 200

    def test_readyz(self):
        client = Client()
        resp = client.get("/readyz/")
        assert resp.status_code == 200

    def test_startupz(self):
        client = Client()
        resp = client.get("/startupz/")
        assert resp.status_code == 200


# ── Schema introspection ───────────────────────────────────────
class TestSchemaIntrospection:
    def test_introspection_query(self):
        client = Client()
        status, data = _gql(client, """
            query {
                __schema {
                    queryType { name }
                    mutationType { name }
                }
            }
        """)
        assert status == 200
        schema = data["data"]["__schema"]
        assert schema["queryType"]["name"] == "Query"
        assert schema["mutationType"]["name"] == "Mutation"

    def test_surveys_type_exists(self):
        client = Client()
        status, data = _gql(client, """
            query {
                __type(name: "SurveyType") {
                    name
                    fields { name }
                }
            }
        """)
        assert status == 200
        survey_type = data["data"]["__type"]
        assert survey_type is not None
        field_names = [f["name"] for f in survey_type["fields"]]
        assert "translations" in field_names
        assert "surveyType" in field_names
