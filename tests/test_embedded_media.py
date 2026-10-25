"""Embedded media (`media.embedding`): forms puts each record's asset in its own
GraphQL response, decided by `media.access.can_access`, one embed call per scope.

The embedder is faked: it applies the real `can_access` to the viewer it is
given and records every call, so these tests see what forms asks and for whom.
"""
from __future__ import annotations

import uuid

import pytest

from media import embedding
from media.access import can_access
from media.models import UploadRecord
from media.profiles import FORMS_ANSWER_FILE
from media.views import may_answer_with_file
from pkg_media import EmbeddedMedia, MediaEmbedder, MediaLibraryError
from pkg_media.embed import EmbedResult
from surveys.models import AnswerSchemaOption, Question, Section, Survey
from survey_collections.models import SurveyCollection
from user_surveys.models import UserAnswer, UserQuestion, UserSurvey
from user_surveys.services import enroll_user_in_assessment


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Response(dict):
    pass


class _Context:
    def __init__(self, user=None):
        self.request = None
        self.identity = _Identity(user) if user else None
        self.auth_context = None
        self.currency = None
        self.response = _Response()


class _Embedder:
    """`MediaEmbedder.embed` over the real rule: allowed ids get a url,
    tokened unless `public`."""

    def __init__(self, public=False, fail=False):
        self.calls = []
        self.public = public
        self.fail = fail

    def embed(self, user, ids):
        ids = [str(i) for i in ids]
        self.calls.append((user, ids))
        if self.fail:
            raise MediaLibraryError("media is down")
        allowed = can_access(user, ids)
        return EmbedResult({
            uuid.UUID(i): EmbeddedMedia(
                asset_id=i,
                kind="image",
                url=f"https://cdn/{i}" if i in allowed else None,
                poster=f"https://cdn/{i}/thumb" if i in allowed else None,
                expires_in=None if self.public or i not in allowed else 3600,
                public=self.public and i in allowed,
            )
            for i in ids
        })


@pytest.fixture
def fake(monkeypatch):
    embedder = _Embedder()
    monkeypatch.setattr(embedding, "get_embedder", lambda: embedder)
    return embedder


def _id() -> str:
    return str(uuid.uuid4())


def _execute(query, variables=None, user=None, context=None):
    from surveys import schema as schema_module

    context = context or _Context(user)
    result = schema_module.schema.execute_sync(query, variable_values=variables, context_value=context)
    assert result.errors is None, result.errors
    return result.data, context


def _publish(survey):
    Survey.objects.filter(pk=survey.pk).update(status=Survey.STATUS_PUBLISHED)


MEDIA = "{ assetId url poster expiresIn public }"

SURVEYS = f"""
query {{
  surveys(surveysListInput: {{limit: 10, offset: 0}}) {{
    items {{ id thumb {MEDIA} cover {MEDIA} }}
  }}
}}
"""

SURVEY = f"""
query One($id: ID!) {{
  survey(id: $id) {{
    cover {MEDIA}
    sections {{ media {MEDIA} questions {{ media {MEDIA} answerSchema {{ options {{ media {MEDIA} }} }} }} }}
  }}
}}
"""

ATTEMPT = f"""
query Attempt($input: UserSurveysListInput!) {{
  userSurvey(userSurveysListInput: $input) {{
    items {{
      cover {MEDIA}
      sections {{ media {MEDIA} }}
      questions {{ media {MEDIA} answerSchema {{ options {{ media {MEDIA} }} }} answers {{ file {MEDIA} }} }}
    }}
  }}
}}
"""


def _attempt_input(user_survey):
    return {"input": {"limit": 1, "offset": 0, "filters": {"id": user_survey.id}, "sort": None}}


@pytest.fixture
def items(survey, section, question, options):
    ids = {k: _id() for k in ("thumb", "cover", "section", "question", "option")}
    Survey.objects.filter(pk=survey.pk).update(thumb_id=ids["thumb"], cover_id=ids["cover"], is_for_child=False)
    Section.objects.filter(pk=section.pk).update(cover_asset_id=ids["section"])
    Question.all_objects.filter(pk=question.pk).update(cover_asset_id=ids["question"])
    AnswerSchemaOption.all_objects.filter(pk=options[0].pk).update(image_asset_id=ids["option"])
    return ids


# ── Pick rule ────────────────────────────────────────────────────────────


def test_thumb_falls_back_to_the_cover_and_cover_to_the_thumb():
    class R:
        thumb_id, cover_id = None, "c"

    assert embedding.thumb_id(R) == "c"
    R.thumb_id, R.cover_id = "t", None
    assert embedding.cover_id(R) == "t"


# ── Lists: one call per page ─────────────────────────────────────────────


def test_a_page_of_surveys_is_one_embed_call(fake, survey):
    for _ in range(3):
        Survey.objects.create(
            organization_id=survey.organization_id, primary_language="en",
            survey_type=survey.survey_type, status=Survey.STATUS_PUBLISHED, cover_id=_id(),
        )
    _publish(survey)

    data, _ = _execute(SURVEYS)

    rows = data["surveys"]["items"]
    assert len(rows) >= 4
    assert len(fake.calls) == 1
    covered = [r for r in rows if r["cover"]]
    assert covered and all(r["thumb"] == r["cover"] for r in covered)  # no thumb: the cover


def test_not_selecting_the_artwork_calls_nothing(fake, survey):
    Survey.objects.filter(pk=survey.pk).update(cover_id=_id(), status=Survey.STATUS_PUBLISHED)

    _execute("query { surveys(surveysListInput: {limit: 10, offset: 0}) { items { id } } }")

    assert fake.calls == []


def test_a_page_of_collections_is_one_embed_call(fake):
    for _ in range(2):
        SurveyCollection.objects.create(organization_id=uuid.uuid4(), thumb_id=_id(), status="published")

    data, _ = _execute(
        f"query {{ collections(collectionsListInput: {{limit: 10, offset: 0}}) {{ items {{ thumb {MEDIA} }} }} }}"
    )

    assert len(fake.calls) == 1
    assert all(r["thumb"]["url"] for r in data["collections"]["items"])


# ── A survey's items: one call for the whole survey ──────────────────────


def test_a_published_surveys_items_embed_in_one_call(fake, survey, items):
    _publish(survey)

    data, _ = _execute(SURVEY, {"id": survey.id})

    body = data["survey"]
    section = body["sections"][0]
    question = section["questions"][0]
    assert body["cover"]["url"]
    assert section["media"]["assetId"] == items["section"]
    assert question["media"]["url"].endswith(items["question"])
    assert {o["media"]["assetId"] for o in question["answerSchema"]["options"] if o["media"]} == {items["option"]}
    assert len(fake.calls) == 2  # the artwork, then every item of the survey


# ── An attempt: one call, the submission's own rule ──────────────────────


def test_an_attempt_embeds_its_snapshot_and_answer_files_in_one_call(fake, survey, items, user, question):
    _publish(survey)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    snapshot_q = UserQuestion.objects.filter(user_survey=user_survey).first()
    file_id = _id()
    UserAnswer.objects.create(user_survey=user_survey, question=snapshot_q, user=user, file_asset_id=file_id)

    data, context = _execute(ATTEMPT, _attempt_input(user_survey), user=user)

    row = data["userSurvey"]["items"][0]
    assert row["cover"]["assetId"] == items["cover"]
    files = [a["file"] for q in row["questions"] for a in q["answers"] if a["file"]]
    assert [f["url"] for f in files] == [f"https://cdn/{file_id}"]
    assert any(q["media"] for q in row["questions"])
    assert len(fake.calls) == 2  # the page's artwork, then every asset of the attempt
    assert all(viewer.user_id == user.id for viewer, _ in fake.calls)
    assert context.response["Cache-Control"] == "private, no-store"


def test_another_learner_never_gets_a_link_to_the_answer_file(survey, items, user, user2):
    _publish(survey)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    snapshot_q = UserQuestion.objects.filter(user_survey=user_survey).first()
    file_id = _id()
    UserAnswer.objects.create(user_survey=user_survey, question=snapshot_q, user=user, file_asset_id=file_id)
    from media.access import Viewer

    assert file_id in can_access(Viewer(user.pk), [file_id])
    assert can_access(Viewer(user2.pk), [file_id]) == set()
    assert can_access(None, [file_id]) == set()


# ── Cache-Control, empty and broken ids, media down ──────────────────────


def test_tokenless_responses_keep_their_cache_control(monkeypatch, survey):
    monkeypatch.setattr(embedding, "get_embedder", lambda: _Embedder(public=True))
    Survey.objects.filter(pk=survey.pk).update(cover_id=_id(), status=Survey.STATUS_PUBLISHED)

    _, context = _execute(SURVEYS)

    assert "Cache-Control" not in context.response


def test_no_ids_and_malformed_ids_call_nothing(fake, survey):
    Survey.objects.filter(pk=survey.pk).update(thumb_id="photo-123", cover_id=None, status=Survey.STATUS_PUBLISHED)

    data, _ = _execute(SURVEYS)

    assert all(r["thumb"] is None and r["cover"] is None for r in data["surveys"]["items"])
    assert fake.calls == []


def test_media_down_leaves_the_media_null_and_the_query_whole(monkeypatch, survey):
    monkeypatch.setattr(embedding, "get_embedder", lambda: _Embedder(fail=True))
    Survey.objects.filter(pk=survey.pk).update(cover_id=_id(), status=Survey.STATUS_PUBLISHED)

    data, _ = _execute(SURVEYS)

    assert data["surveys"]["items"] and all(r["cover"] is None for r in data["surveys"]["items"])


def test_without_media_configured_everything_is_null(monkeypatch, survey):
    monkeypatch.setattr(embedding, "get_embedder", lambda: None)
    Survey.objects.filter(pk=survey.pk).update(cover_id=_id(), status=Survey.STATUS_PUBLISHED)

    data, _ = _execute(SURVEYS)

    assert all(r["cover"] is None for r in data["surveys"]["items"])


def test_the_embedder_uses_the_resolve_rule_and_its_cache(monkeypatch):
    client = object()
    monkeypatch.setattr(embedding, "build_client", lambda: client)
    monkeypatch.setattr(embedding, "_embedder", None)

    embedder = embedding.get_embedder()

    assert isinstance(embedder, MediaEmbedder)
    assert embedder.cache is embedding.MEDIA_LINK_CACHE
    assert embedding.get_embedder() is embedder


# ── Answer-file uploads ──────────────────────────────────────────────────


@pytest.fixture
def file_attempt(survey, question, user):
    Question.all_objects.filter(pk=question.pk).update(type=Question.QUESTION_TYPE_FILE)
    _publish(survey)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    snapshot_q = UserQuestion.objects.get(user_survey=user_survey, type=UserQuestion.TYPE_FILE)
    return user_survey, snapshot_q


def _context_of(user_survey, question):
    return {"userSurveyId": user_survey.id, "questionId": question.id}


def test_a_respondent_may_upload_to_their_own_open_file_question(file_attempt, user, user2):
    user_survey, question = file_attempt

    assert may_answer_with_file(user.id, _context_of(user_survey, question))
    assert not may_answer_with_file(user2.id, _context_of(user_survey, question))
    assert not may_answer_with_file(user.id, {"userSurveyId": user_survey.id})
    UserSurvey.objects.filter(pk=user_survey.pk).update(submitted_at="2026-10-25T00:00:00Z")
    assert not may_answer_with_file(user.id, _context_of(user_survey, question))


ANSWER = """
mutation Answer($us: ID!, $q: ID!, $file: String) {
  answerQuestion(userSurveyId: $us, questionId: $q, answer: ["scan.pdf"], fileAssetId: $file) {
    ... on UserAnswerType { answer }
    ... on OperationInfo { messages { message } }
  }
}
"""


def _claim(user, user_survey, question, asset_id):
    UploadRecord.objects.create(
        session_id=uuid.uuid4(), owner=user.id, profile=FORMS_ANSWER_FILE.name,
        context=_context_of(user_survey, question), attached_asset_id=asset_id,
    )


def _answer(user, user_survey, question, **variables):
    data, _ = _execute(ANSWER, {"us": user_survey.id, "q": question.id, **variables}, user=user)
    return data["answerQuestion"]


def test_a_claimed_answer_file_is_stored(file_attempt, user):
    user_survey, question = file_attempt
    asset = _id()
    _claim(user, user_survey, question, asset)

    out = _answer(user, user_survey, question, file=asset)

    assert out.get("answer") == "scan.pdf"
    assert UserAnswer.objects.get(user_survey=user_survey, question=question).file_asset_id == asset


def test_an_unclaimed_or_misplaced_file_is_refused(file_attempt, user, user2):
    user_survey, question = file_attempt
    stranger = _id()
    _claim(user2, user_survey, question, stranger)

    out = _answer(user, user_survey, question, file=stranger)

    assert "messages" in out
    assert not UserAnswer.objects.filter(user_survey=user_survey, file_asset_id=stranger).exists()


def test_leaving_the_file_out_keeps_it_and_null_clears_it(file_attempt, user):
    user_survey, question = file_attempt
    asset = _id()
    _claim(user, user_survey, question, asset)
    _answer(user, user_survey, question, file=asset)

    _execute(
        'mutation($us: ID!, $q: ID!) { answerQuestion(userSurveyId: $us, questionId: $q, answer: ["scan.pdf"]) '
        "{ ... on UserAnswerType { answer } } }",
        {"us": user_survey.id, "q": question.id}, user=user,
    )
    assert UserAnswer.objects.get(user_survey=user_survey, question=question).file_asset_id == asset

    _answer(user, user_survey, question, file=None)
    assert UserAnswer.objects.get(user_survey=user_survey, question=question).file_asset_id is None


def test_a_respondent_opens_their_own_claimed_upload_before_answering(file_attempt, user, user2):
    from media.access import Viewer

    user_survey, question = file_attempt
    asset = _id()
    _claim(user, user_survey, question, asset)

    assert can_access(Viewer(user.pk), [asset]) == {asset}
    assert can_access(Viewer(user2.pk), [asset]) == set()
    assert can_access(None, [asset]) == set()
