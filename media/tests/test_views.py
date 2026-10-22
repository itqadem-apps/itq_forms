"""The resolve and upload endpoints: the contract of
`pkg_media.integrations.fastapi`, served by hand on Django.

Views are called through `RequestFactory`; `request.identity` and
`request.auth_context` stand in for pkg_auth's middleware (not installed under
pytest), except in the stale-token test, which runs the real identity middleware.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from pkg_auth.authorization import MissingPermission, OrgId
from pkg_media import (
    DeliveryBatchResolveResult,
    MediaLibraryError,
    NotFoundError,
    UploadRejected,
)

from app.permissions import Permission
from media import views
from media.models import UploadRecord
from surveys.models import Survey

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _AuthContext:
    def __init__(self, organization_id, *permissions):
        self.organization_id = OrgId(organization_id)
        self._permissions = {p.value for p in permissions}

    def require(self, key):
        if key not in self._permissions:
            raise MissingPermission(key)


def _delivered(asset_id: uuid.UUID) -> DeliveryBatchResolveResult:
    return DeliveryBatchResolveResult.model_validate({
        "assetId": str(asset_id),
        "status": "ok",
        "thumbnailUrl": None,
        "asset": {
            "id": str(asset_id), "kind": "image", "status": "ready", "visibility": "restricted",
            "mimeType": "image/png", "downloadType": "presigned", "downloadUrl": f"https://cdn/{asset_id}",
        },
    })


class FakeMedia:
    tenant_id = None

    def __init__(self):
        self.existing: set[uuid.UUID] = set()
        self.resolved: list[list[uuid.UUID]] = []
        self.fail: Exception | None = None
        self.verify_error: Exception | None = None
        self.aborted: list = []
        self.opened: list[dict] = []
        self.delivery = SimpleNamespace(resolve=self._resolve)
        self.uploads = SimpleNamespace(
            open_session=self._open_session, verify_upload=self._verify, abort=self.aborted.append,
        )
        self.grants = SimpleNamespace(issue=self._issue)

    def _resolve(self, asset_ids, cache=None):
        if self.fail is not None:
            raise self.fail
        self.resolved.append(list(asset_ids))
        return [
            _delivered(a) if a in self.existing
            else DeliveryBatchResolveResult.model_validate({"assetId": str(a), "status": "not_found"})
            for a in asset_ids
        ]

    def _grant(self):
        return SimpleNamespace(to_payload=lambda: {
            "grant": "mlg_x", "grantId": "g1", "scopes": ["upload"], "expiresIn": 600, "expiresAt": "later",
        })

    def _open_session(self, **kwargs):
        if self.fail is not None:
            raise self.fail
        self.opened.append(kwargs)
        return SimpleNamespace(session=SimpleNamespace(id=uuid.uuid4(), part_size_bytes=8_388_608), grant=self._grant())

    def _issue(self, scopes, **kwargs):
        return self._grant()

    def _verify(self, session_id, asset_id, profile):
        if self.verify_error is not None:
            raise self.verify_error
        return SimpleNamespace(id=asset_id)


@pytest.fixture
def media(monkeypatch):
    fake = FakeMedia()
    monkeypatch.setattr(views, "build_client", lambda: fake)
    monkeypatch.setattr(views, "build_grpc_client", lambda: fake)
    return fake


rf = RequestFactory()


def _call(view, method, path="/", body=None, *, user=None, auth=None, raw=None, **kwargs):
    if method == "get":
        request = rf.get(path)
    else:
        data = raw if raw is not None else json.dumps(body or {})
        request = rf.post(path, data=data, content_type="application/json")
    request.identity = SimpleNamespace(subject_str=user) if user else None
    request.auth_context = auth
    response = view(request, **kwargs)
    return response.status_code, json.loads(response.content)


@pytest.fixture
def published(survey, section):
    asset = uuid.uuid4()
    section.cover_asset_id = str(asset)
    section.save()
    Survey.objects.filter(pk=survey.pk).update(status=Survey.STATUS_PUBLISHED)
    return asset


@pytest.fixture
def draft_item(survey):
    """A section cover of a second survey of ORG, left in draft."""
    from surveys.models import Section

    draft = Survey.objects.create(
        organization_id=ORG, primary_language="en", survey_type=survey.survey_type,
        display_option=survey.display_option, evaluation_type=survey.evaluation_type,
    )
    asset = uuid.uuid4()
    Section.objects.create(survey=draft, title="Draft", cover_asset_id=str(asset))
    return asset


# ── POST media/resolve ──────────────────────────────────────────────────


def test_resolve_answers_media_shape_for_an_allowed_id(media, published):
    media.existing.add(published)

    status, body = _call(views.resolve_assets, "post", body={"assetIds": [str(published)]})

    assert status == 200
    assert body["total"] == 1
    (item,) = body["items"]
    assert item["assetId"] == str(published)
    assert item["status"] == "ok"
    assert item["asset"]["downloadUrl"] == f"https://cdn/{published}"


def test_a_denied_id_is_forbidden_and_never_sent_to_media(media, draft_item, published):
    media.existing.update({draft_item, published})

    status, body = _call(views.resolve_assets, "post", body={"assetIds": [str(draft_item), str(published)]})

    assert status == 200
    assert [i["status"] for i in body["items"]] == ["forbidden", "ok"]
    assert body["items"][0]["asset"] is None
    assert media.resolved == [[published]]


def test_a_foreign_id_is_forbidden_not_missing(media):
    foreign = uuid.uuid4()
    media.existing.add(foreign)

    _, body = _call(views.resolve_assets, "post", body={"assetIds": [str(foreign)]})

    assert body["items"][0]["status"] == "forbidden"
    assert media.resolved == []


def test_staff_resolve_their_draft(media, draft_item, user):
    media.existing.add(draft_item)

    _, body = _call(
        views.resolve_assets, "post", body={"assetIds": [str(draft_item)]},
        user=user.pk, auth=_AuthContext(ORG, Permission.SURVEY_READ),
    )

    assert body["items"][0]["status"] == "ok"


@pytest.mark.parametrize("payload", [
    {"assetIds": []},
    {"assetIds": [str(uuid.uuid4()) for _ in range(101)]},
    {"assetIds": ["asset-112"]},
    {},
])
def test_resolve_refuses_a_bad_body(media, payload):
    status, body = _call(views.resolve_assets, "post", body=payload)

    assert status == 422
    assert body["detail"]


def test_resolve_refuses_non_json(media):
    status, _ = _call(views.resolve_assets, "post", raw="not json")

    assert status == 422


def test_resolve_is_post_only(media):
    status, _ = _call(views.resolve_assets, "get")

    assert status == 405


def test_media_failure_is_502_not_the_callers_fault(media, published):
    media.fail = MediaLibraryError("token rejected")

    status, body = _call(views.resolve_assets, "post", body={"assetIds": [str(published)]})

    assert status == 502
    assert body == {"detail": "Media library request failed"}


def test_unconfigured_media_is_503(monkeypatch, published):
    monkeypatch.setattr(views, "build_grpc_client", lambda: None)

    status, _ = _call(views.resolve_assets, "post", body={"assetIds": [str(published)]})

    assert status == 503


def test_a_stale_token_reads_as_anonymous(media, published, draft_item, monkeypatch):
    """The real identity middleware turns a rejected token into no identity;
    the endpoint then answers as for a guest, never 401."""
    from pkg_auth.authentication import TokenExpiredError

    from app import auth

    def reject(token):
        raise TokenExpiredError("expired")

    registry = SimpleNamespace(cookie_name="access_token", authenticate=SimpleNamespace(execute=reject))
    monkeypatch.setattr(auth, "get_registry", lambda: registry)
    media.existing.update({published, draft_item})

    request = rf.post(
        "/", data=json.dumps({"assetIds": [str(published), str(draft_item)]}),
        content_type="application/json", HTTP_AUTHORIZATION="Bearer stale",
    )
    request.auth_context = None
    response = auth.LoggingIdentityMiddleware(views.resolve_assets)(request)

    assert request.identity is None
    assert response.status_code == 200
    assert [i["status"] for i in json.loads(response.content)["items"]] == ["ok", "forbidden"]


# ── GET media/<id> ──────────────────────────────────────────────────────


def test_get_asset_returns_the_asset(media, published):
    media.existing.add(published)

    status, body = _call(views.get_asset, "get", asset_id=published)

    assert status == 200
    assert body["id"] == str(published)


def test_get_asset_denied_is_403(media, draft_item):
    media.existing.add(draft_item)

    status, body = _call(views.get_asset, "get", asset_id=draft_item)

    assert status == 403
    assert body == {"detail": "Access denied", "thumbnailUrl": None}


def test_get_asset_allowed_but_missing_in_media_is_404(media, published):
    status, _ = _call(views.get_asset, "get", asset_id=published)

    assert status == 404


def test_get_asset_media_failure_is_502(media, published):
    media.fail = MediaLibraryError("down")

    status, _ = _call(views.get_asset, "get", asset_id=published)

    assert status == 502


# ── POST uploads ────────────────────────────────────────────────────────

EDITOR = (Permission.SURVEY_READ, Permission.SURVEY_UPDATE)


def _start(user, survey, *, profile="forms-item-image", auth=None, **overrides):
    body = {
        "mimeType": "image/png", "sizeBytes": 1000, "filename": "a.png", "profile": profile,
        "context": {"surveyId": survey.pk},
        **overrides,
    }
    return _call(
        views.start_upload, "post", body=body, user=user.pk if user else None,
        auth=auth if auth is not None else _AuthContext(ORG, *EDITOR),
    )


def test_start_upload_needs_a_caller(media, survey):
    status, _ = _start(None, survey)

    assert status == 401


def test_start_upload_opens_a_session_and_records_it(media, survey, user):
    status, body = _start(user, survey)

    assert status == 201
    assert body["grant"] == "mlg_x"
    assert body["partSizeBytes"] == 8_388_608
    assert "tenant" not in body and "uploadBaseUrl" not in body
    record = UploadRecord.objects.get(pk=body["sessionId"])
    assert (record.owner, record.profile, record.context) == (user.pk, "forms-item-image", {"surveyId": survey.pk})
    assert record.attached_asset_id is None
    (opened,) = media.opened
    assert opened["profile"].name == "forms-item-image"
    assert opened["subject"] == user.pk


@pytest.mark.parametrize("profile,status", [(None, 422), ("forms-answer-file", 422), ("nope", 422)])
def test_start_upload_needs_a_known_profile(media, survey, user, profile, status):
    assert _start(user, survey, profile=profile)[0] == status


@pytest.mark.parametrize("overrides,status,reason", [
    ({"mimeType": "application/pdf"}, 415, UploadRejected.MIME_TYPE),
    ({"sizeBytes": 3_000_000}, 413, UploadRejected.TOO_LARGE),
])
def test_start_upload_checks_the_file(media, survey, user, overrides, status, reason):
    code, body = _start(user, survey, profile="forms-thumb", **overrides)

    assert code == status
    assert body["reason"] == reason


@pytest.mark.parametrize("auth", [
    None,
    _AuthContext(OTHER_ORG, *EDITOR),
    _AuthContext(ORG, Permission.SURVEY_READ),
])
def test_start_upload_refuses_who_may_not_edit_the_survey(media, survey, user, auth):
    status, _ = _call(
        views.start_upload, "post", user=user.pk, auth=auth,
        body={"mimeType": "image/png", "sizeBytes": 10, "profile": "forms-item-image", "context": {"surveyId": survey.pk}},
    )

    assert status == 403
    assert media.opened == []


def test_an_item_image_needs_its_survey(media, survey, user):
    assert _start(user, survey, context={})[0] == 403


def test_artwork_for_a_new_survey_needs_only_an_org(media, survey, user):
    assert _start(user, survey, profile="forms-cover", context={})[0] == 201


def test_a_failed_record_aborts_the_session(media, survey, user, monkeypatch):
    def boom(record):
        raise RuntimeError("db down")

    monkeypatch.setattr(views.store, "save", boom)

    with pytest.raises(RuntimeError):
        _start(user, survey)
    assert len(media.aborted) == 1


def test_media_down_on_start_is_502(media, survey, user):
    media.fail = MediaLibraryError("down")

    assert _start(user, survey)[0] == 502


# ── grant refresh and attach ────────────────────────────────────────────


@pytest.fixture
def session(media, survey, user):
    _, body = _start(user, survey)
    return uuid.UUID(body["sessionId"])


def _attach(session_id, user, asset_id=None, **body):
    return _call(
        views.attach_upload, "post", body={"assetId": str(asset_id or uuid.uuid4()), **body},
        user=user.pk, auth=_AuthContext(ORG, *EDITOR), session_id=session_id,
    )


def test_grant_refresh_for_the_owner(session, user):
    status, body = _call(views.refresh_grant, "post", user=user.pk, session_id=session)

    assert status == 200
    assert body["sessionId"] == str(session)
    assert body["grant"] == "mlg_x"


def test_grant_refresh_hides_another_users_session(session, user2):
    status, _ = _call(views.refresh_grant, "post", user=user2.pk, session_id=session)

    assert status == 404


def test_attach_claims_once(session, user):
    asset = uuid.uuid4()

    status, body = _attach(session, user, asset)

    assert status == 200
    assert body == {"sessionId": str(session), "assetId": str(asset)}
    assert UploadRecord.objects.get(pk=session).attached_asset_id == asset
    assert _attach(session, user)[0] == 409
    assert _call(views.refresh_grant, "post", user=user.pk, session_id=session)[0] == 409


def test_attach_hides_another_users_session(session, user2):
    assert _attach(session, user2)[0] == 404
    assert UploadRecord.objects.get(pk=session).attached_asset_id is None


def test_attach_with_another_profile_is_409(session, user):
    status, body = _attach(session, user, profile="forms-thumb")

    assert status == 409
    assert body["reason"] == UploadRejected.PROFILE_MISMATCH


def test_attach_when_the_survey_left_the_org_is_403(session, user, survey):
    Survey.objects.filter(pk=survey.pk).update(organization_id=OTHER_ORG)

    status, body = _attach(session, user)

    assert status == 403
    assert body["reason"] == UploadRejected.CONTEXT_MISMATCH


def test_attach_of_an_unfinished_upload_is_422(media, session, user):
    media.verify_error = UploadRejected("not finalized", reason=UploadRejected.NOT_FINALIZED)

    status, body = _attach(session, user)

    assert status == 422
    assert body["reason"] == UploadRejected.NOT_FINALIZED
    assert UploadRecord.objects.get(pk=session).attached_asset_id is None


def test_attach_of_an_asset_media_does_not_have_is_404(media, session, user):
    media.verify_error = NotFoundError("gone")

    assert _attach(session, user)[0] == 404
