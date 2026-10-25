"""Forms assets embedded in GraphQL responses (pkg_media `EmbeddedMedia`), so
browsers never resolve an asset id (`embedded-media.md`, ruling 1).

The schema is served by Django's sync `GraphQLView`, where pkg_media's async
`StrawberryMedia` dataloader cannot run. Each request keeps one map of embedded
ids on the Django request instead. A miss embeds the record's whole scope in one
`MediaEmbedder.embed` call: the page a list resolver primed (`prime_records`), or
every asset of the record's survey or attempt (`survey_asset_ids`,
`attempt_asset_ids`), the way `prime_max_scores` batches `maxScore`.

Access is `media.access.can_access`, the rule of forms' resolve endpoints, and
the link cache is theirs (`MEDIA_LINK_CACHE`). `thumbnails=False`: an id the
caller may not open gets no link at all, as from the endpoints. Forms has no
paywalled artwork that would want a teaser, and an answer file must not leak one.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional
from uuid import UUID

import httpx
from pkg_media import AssetUrlCache, MediaEmbedder, MediaLibraryError
from pkg_media.integrations.strawberry import EmbeddedMediaType

from media.access import can_access, viewer_for
from media.client import build_client

logger = logging.getLogger(__name__)

#: One link cache per process, shared with `media.views`' gate.
MEDIA_LINK_CACHE = AssetUrlCache()

PRIVATE = "private, no-store"

_lock = threading.Lock()
_embedder: Optional[MediaEmbedder] = None
_embedder_client: Any = None


def get_embedder() -> Optional[MediaEmbedder]:
    """The process-wide embedder, rebuilt if the client changes. None when
    forms runs without media."""
    global _embedder, _embedder_client
    client = build_client()
    if client is None:
        return None
    with _lock:
        if _embedder is None or _embedder_client is not client:
            _embedder = MediaEmbedder(client, can_access, cache=MEDIA_LINK_CACHE, thumbnails=False)
            _embedder_client = client
        return _embedder


@dataclass
class _State:
    media: Dict[str, Optional[EmbeddedMediaType]] = field(default_factory=dict)
    tokened: bool = False


def _state(info: Any) -> _State:
    # The Django request, or the context itself where there is none (tests).
    holder = getattr(info.context, "request", None) or info.context
    state = getattr(holder, "_forms_embedded_media", None)
    if state is None:
        state = _State()
        holder._forms_embedded_media = state
    return state


def _key(asset_id: Any) -> Optional[str]:
    """The id as a lower-case UUID string, or None for an empty or malformed
    column (they are client-written strings)."""
    if not asset_id:
        return None
    try:
        return str(UUID(str(asset_id)))
    except ValueError:
        return None


def tokened(info: Any) -> bool:
    """Whether this request embedded a tokened link so far."""
    return _state(info).tokened


def prime(info: Any, asset_ids: Iterable[Any]) -> None:
    """Embed every id of `asset_ids` not embedded yet in this request, in one
    call. A failure talking to media leaves those ids without media (logged)
    rather than failing the query."""
    state = _state(info)
    wanted = list(dict.fromkeys(k for k in map(_key, asset_ids) if k and k not in state.media))
    if not wanted:
        return
    embedder = get_embedder()
    embeds = None
    if embedder is not None:
        try:
            embeds = embedder.embed(viewer_for(info.context), wanted)
        except (MediaLibraryError, httpx.HTTPError) as exc:
            logger.warning("Embedding media failed: %s: %s", type(exc).__name__, exc)
    for key in wanted:
        found = embeds.get(key) if embeds is not None else None
        state.media[key] = EmbeddedMediaType.from_model(found) if found is not None else None
    if embeds is not None and embeds.tokened and not state.tokened:
        state.tokened = True
        response = getattr(info.context, "response", None)
        if response is not None:
            response["Cache-Control"] = PRIVATE


def embedded(
    info: Any,
    asset_id: Any,
    scope: Optional[Callable[[], Iterable[Any]]] = None,
) -> Optional[EmbeddedMediaType]:
    """The embedded asset, or None. On a miss, `scope()` names the ids to
    embed with it (its record's siblings), so the rest of the request hits."""
    key = _key(asset_id)
    if key is None:
        return None
    state = _state(info)
    if key not in state.media:
        prime(info, [key, *(scope() if scope is not None else ())])
    return state.media.get(key)


# ── Pick rules (ruling 3) ───────────────────────────────────────────────


def thumb_id(record: Any) -> Optional[str]:
    """Cards, order lines, the admin list: the thumb, else the cover."""
    return record.thumb_id or record.cover_id


def cover_id(record: Any) -> Optional[str]:
    """Heroes, the start step, the share image: the cover, else the thumb."""
    return record.cover_id or record.thumb_id


def prime_records(info: Any, records: Iterable[Any], prefix: tuple[str, ...] = ()) -> None:
    """When the request selects `thumb` or `cover` at `prefix` under the
    resolver's own field, embed the artwork of a page of surveys, collections
    or attempts (each with `thumb_id` / `cover_id`) in one call."""
    from user_surveys.types.max_score_priming import _selects

    if not any(
        _selects(f.selections, (*prefix, name)) for f in info.selected_fields for name in ("thumb", "cover")
    ):
        return
    ids = []
    for record in records:
        ids.extend((record.thumb_id, record.cover_id))
    prime(info, ids)


# ── Scopes ──────────────────────────────────────────────────────────────


def survey_asset_ids(survey_id: Optional[int]) -> list[str]:
    """Every item image of a survey: section and question covers, option
    images. A legacy question belongs through its section (`forms:AD-23`)."""
    if survey_id is None:
        return []
    from django.db.models import Q

    from surveys.models import AnswerSchemaOption, Question, Section

    ids = list(Section.objects.filter(survey_id=survey_id).values_list("cover_asset_id", flat=True))
    ids += Question.objects.filter(
        Q(survey_id=survey_id) | Q(survey__isnull=True, section__survey_id=survey_id)
    ).values_list("cover_asset_id", flat=True)
    ids += AnswerSchemaOption.objects.filter(survey_id=survey_id).values_list("image_asset_id", flat=True)
    return [i for i in ids if i]


def attempt_asset_ids(user_survey_id: Optional[int]) -> list[str]:
    """Every asset of one attempt's snapshot: its artwork, section and question
    covers, option images and answer files."""
    if user_survey_id is None:
        return []
    from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSection, UserSurvey

    ids: list[Any] = []
    for thumb, cover in UserSurvey.objects.filter(pk=user_survey_id).values_list("thumb_id", "cover_id"):
        ids += [thumb, cover]
    ids += UserSection.objects.filter(user_survey_id=user_survey_id).values_list("cover_asset_id", flat=True)
    ids += UserQuestion.objects.filter(user_survey_id=user_survey_id).values_list("cover_asset_id", flat=True)
    ids += UserAnswerOption.objects.filter(user_survey_id=user_survey_id).values_list("image_asset_id", flat=True)
    ids += UserAnswer.objects.filter(user_survey_id=user_survey_id).values_list("file_asset_id", flat=True)
    return [i for i in ids if i]
