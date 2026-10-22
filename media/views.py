"""Forms' media endpoints for browsers, by hand on Django with the contract of
`pkg_media.integrations.fastapi` (which needs FastAPI):

- `POST media/resolve`, `GET media/<id>`: `create_media_router(...,
  thumbnails=False)` over `AccessGate` and `media.access.can_access`.
- `POST uploads`, `POST uploads/<id>/grant`, `POST uploads/<id>/attach`:
  `create_upload_router` with `media.profiles.UPLOAD_PROFILES`, the
  `UploadRecord` store and `claim_upload`.

Bodies are camelCase JSON; errors are `{"detail": ...}`. Every failure talking
to media is 502 with a generic detail, so an expired service credential is not
mistaken for the caller's own 401. Served by the web role only (app/urls.py).
"""
from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional
from uuid import UUID

import httpx
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pkg_auth.authorization import MissingPermission
from pkg_media import (
    AccessGate,
    AssetUrlCache,
    GrantScope,
    MediaLibraryError,
    NotFoundError,
    ResolveStatus,
    UploadProfile,
    UploadRejected,
    claim_upload,
)
from pkg_media.service_uploads import UploadRecord as Record
from pydantic import BaseModel, Field
from pydantic import ValidationError as BodyError

from app.permissions import get_permission_for_kind
from app.platform import ensure_in_org
from media.access import Viewer, can_access
from media.client import build_client
from media.models import DjangoUploadStore
from media.profiles import FORMS_ITEM_IMAGE, UPLOAD_PROFILES
from survey_collections.models import SurveyCollection
from surveys.models import Survey

logger = logging.getLogger(__name__)

# Same limit as media's POST /delivery/assets/resolve.
MAX_RESOLVE_IDS = 100

_REJECTED_STATUS = {UploadRejected.MIME_TYPE: 415, UploadRejected.TOO_LARGE: 413}
_ATTACH_REJECTED_STATUS = {
    UploadRejected.UNKNOWN_SESSION: 404,
    UploadRejected.CONTEXT_MISMATCH: 403,
    UploadRejected.PROFILE_MISMATCH: 409,
    UploadRejected.ALREADY_ATTACHED: 409,
}

store = DjangoUploadStore()


class ResolveRequest(BaseModel):
    asset_ids: List[UUID] = Field(..., alias="assetIds", min_length=1, max_length=MAX_RESOLVE_IDS)

    model_config = {"populate_by_name": True}


class StartUploadRequest(BaseModel):
    mime_type: str = Field(..., alias="mimeType", min_length=1, max_length=255)
    size_bytes: int = Field(..., alias="sizeBytes", ge=0)
    filename: Optional[str] = Field(None, max_length=255)
    profile: Optional[str] = Field(None, max_length=255)
    context: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class AttachUploadRequest(BaseModel):
    asset_id: UUID = Field(..., alias="assetId")
    profile: Optional[str] = Field(None, max_length=255)

    model_config = {"populate_by_name": True}


class _Failed(Exception):
    def __init__(self, status: int, detail: Any, **extra: Any):
        self.response = JsonResponse({"detail": detail, **extra}, status=status)


# ── Shared pieces ───────────────────────────────────────────────────────

_gate_lock = threading.Lock()
_gate: Optional[AccessGate] = None
_gate_client: Any = None


def _get_gate() -> AccessGate:
    """One gate (and link cache) per process, rebuilt if the client changes."""
    global _gate, _gate_client
    client = _client()
    with _gate_lock:
        if _gate is None or _gate_client is not client:
            # resolve_denied=False: an id can_access refuses never reaches
            # media, so no other service's asset is resolved with forms' token.
            _gate = AccessGate(client, can_access, cache=AssetUrlCache(), hide_missing=True, resolve_denied=False)
            _gate_client = client
        return _gate


def _client():
    client = build_client()
    if client is None:
        raise _Failed(503, "Media library is not configured")
    return client


def _viewer(request: HttpRequest) -> Optional[Viewer]:
    """The caller, or None. `LoggingIdentityMiddleware` already turned a stale
    or invalid token into None (and logged it), and
    `OptionalAuthContextMiddleware` an unresolvable org into no context."""
    identity = getattr(request, "identity", None)
    if identity is None:
        return None
    return Viewer(user_id=identity.subject_str, auth_context=getattr(request, "auth_context", None))


def _signed_in(request: HttpRequest) -> Viewer:
    viewer = _viewer(request)
    if viewer is None:
        raise _Failed(401, "Authentication required")
    return viewer


def _body(request: HttpRequest, model: type[BaseModel]) -> Any:
    try:
        raw = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise _Failed(422, "Body is not valid JSON")
    try:
        return model.model_validate(raw)
    except BodyError as exc:
        raise _Failed(422, json.loads(exc.json(include_url=False)))


@contextmanager
def _media_errors() -> Iterator[None]:
    try:
        yield
    except (MediaLibraryError, httpx.HTTPError) as exc:
        logger.warning("Media library request failed: %s: %s", type(exc).__name__, exc)
        raise _Failed(502, "Media library request failed") from exc


def _endpoint(method: str):
    def wrap(view):
        def handler(request: HttpRequest, *args, **kwargs):
            if request.method != method:
                return JsonResponse({"detail": "Method Not Allowed"}, status=405, headers={"Allow": method})
            try:
                return view(request, *args, **kwargs)
            except _Failed as failed:
                return failed.response

        return csrf_exempt(handler)

    return wrap


# ── Resolve ─────────────────────────────────────────────────────────────


@_endpoint("POST")
def resolve_assets(request: HttpRequest) -> JsonResponse:
    payload = _body(request, ResolveRequest)
    viewer = _viewer(request)
    gate = _get_gate()
    with _media_errors():
        results = gate.resolve(viewer, payload.asset_ids)
    return JsonResponse(AccessGate.to_payload(results))


@_endpoint("GET")
def get_asset(request: HttpRequest, asset_id: UUID) -> JsonResponse:
    viewer = _viewer(request)
    gate = _get_gate()
    with _media_errors():
        result = gate.resolve_one(viewer, asset_id)

    if result.status == ResolveStatus.OK and result.asset is not None:
        return JsonResponse(result.asset.model_dump(mode="json", by_alias=True))
    if result.status == ResolveStatus.NOT_FOUND:
        return JsonResponse({"detail": f"Asset {asset_id} not found"}, status=404)
    if result.status == ResolveStatus.FORBIDDEN:
        status, detail = 403, result.error or AccessGate.DENIED_ERROR
    else:
        status, detail = 502, result.error or "Could not resolve the asset's link"
    return JsonResponse({"detail": detail, "thumbnailUrl": result.thumbnail_url}, status=status)


# ── Uploads ─────────────────────────────────────────────────────────────


def _may_edit(viewer: Viewer, context: Dict[str, Any], profile: UploadProfile) -> bool:
    """Forms' rule for starting (and attaching) an upload: a member of an
    organization; for a survey named in `context["surveyId"]`, one of that
    organization holding the survey kind's update permission; for a
    collection (`collectionId`), one of its organization. Item images belong
    to a survey, so they need `surveyId`."""
    auth_ctx = viewer.auth_context
    if auth_ctx is None:
        return False
    survey_id = context.get("surveyId")
    collection_id = context.get("collectionId")
    if profile.name == FORMS_ITEM_IMAGE.name and survey_id is None:
        return False
    try:
        if survey_id is not None:
            survey = Survey.objects.filter(pk=int(survey_id), deleted_at__isnull=True).first()
            if survey is None:
                return False
            ensure_in_org(survey, auth_ctx)
            auth_ctx.require(get_permission_for_kind(survey.survey_type, "update").value)
        if collection_id is not None:
            collection = SurveyCollection.objects.filter(pk=int(collection_id), deleted_at__isnull=True).first()
            if collection is None:
                return False
            ensure_in_org(collection, auth_ctx)
    except (TypeError, ValueError, PermissionError, MissingPermission) as exc:
        logger.info("Upload refused for %s: %s: %s", viewer.user_id, type(exc).__name__, exc)
        return False
    return True


def _profile_named(name: Optional[str]) -> UploadProfile:
    if name is None:
        raise _Failed(422, "profile is required")
    profile = UPLOAD_PROFILES.get(name)
    if profile is None:
        raise _Failed(422, f"Unknown upload profile {name!r}")
    return profile


def _abort_quietly(client: Any, session_id: Any) -> None:
    try:
        client.uploads.abort(session_id)
    except Exception as exc:
        logger.warning("Could not abort upload session %s: %s", session_id, exc)


@_endpoint("POST")
def start_upload(request: HttpRequest) -> JsonResponse:
    viewer = _signed_in(request)
    payload = _body(request, StartUploadRequest)
    profile = _profile_named(payload.profile)
    try:
        profile.validate_file(payload.mime_type, payload.size_bytes)
    except UploadRejected as exc:
        raise _Failed(_REJECTED_STATUS.get(exc.reason, 422), str(exc), reason=exc.reason)
    if not _may_edit(viewer, payload.context, profile):
        raise _Failed(403, "Not allowed")

    client = _client()
    with _media_errors():
        opened = client.uploads.open_session(
            mime_type=payload.mime_type,
            profile=profile,
            original_filename=payload.filename,
            expected_size_bytes=payload.size_bytes,
            subject=viewer.user_id,
            validate=False,
        )
    session = opened.session
    try:
        store.save(Record(
            session_id=session.id,
            owner=viewer.user_id,
            profile=profile.name,
            context=dict(payload.context),
        ))
    except Exception:
        _abort_quietly(client, session.id)
        raise
    return JsonResponse(
        {
            "sessionId": str(session.id),
            **opened.grant.to_payload(),
            "partSizeBytes": session.part_size_bytes,
        },
        status=201,
    )


def _own_record(viewer: Viewer, session_id: UUID) -> Record:
    record = store.get(session_id)
    if record is None or record.owner != viewer.user_id:
        raise _Failed(404, f"Upload session {session_id} not found")
    return record


@_endpoint("POST")
def refresh_grant(request: HttpRequest, session_id: UUID) -> JsonResponse:
    viewer = _signed_in(request)
    record = _own_record(viewer, session_id)
    if record.attached_asset_id is not None:
        raise _Failed(409, "Upload session is already attached")
    client = _client()
    with _media_errors():
        grant = client.grants.issue([GrantScope.UPLOAD], session_ids=[session_id], subject=viewer.user_id)
    return JsonResponse({"sessionId": str(session_id), **grant.to_payload()})


@_endpoint("POST")
def attach_upload(request: HttpRequest, session_id: UUID) -> JsonResponse:
    """Claim a finalized upload so its asset id may be written to a forms
    row (`media.claims`). The GraphQL mutation then takes the id."""
    viewer = _signed_in(request)
    payload = _body(request, AttachUploadRequest)
    record = _own_record(viewer, session_id)
    profile = UPLOAD_PROFILES.get(payload.profile or record.profile)
    if profile is None:
        raise _Failed(422, f"Unknown upload profile {payload.profile!r}")
    client = _client()
    with _media_errors():
        try:
            with transaction.atomic():
                claimed = claim_upload(
                    client, store, session_id, payload.asset_id,
                    owner=viewer.user_id,
                    profile=profile,
                    check_record=lambda r: _may_edit(viewer, r.context, profile),
                )
        except UploadRejected as exc:
            raise _Failed(_ATTACH_REJECTED_STATUS.get(exc.reason, 422), str(exc), reason=exc.reason)
        except NotFoundError:
            raise _Failed(404, "Upload session or asset not found")
    return JsonResponse({"sessionId": str(session_id), "assetId": str(claimed.asset.id)})
