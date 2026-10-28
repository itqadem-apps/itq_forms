"""Asset claims: which forms records use which media assets (pkg_media v2,
`docs/api/asset-claims.md` in the media library).

Not to be confused with `media.claims` (claim-on-attach of an upload record).
Here forms tells media, after a write commits, which assets a record uses
(`client.assets.claim`) and which it stopped using (`client.assets.release`),
so media can list forms' assets and report what nobody uses.

Refs are `forms:<record>/<id>`:

| ref | columns | collection label |
|---|---|---|
| `forms:survey/<id>` | `Survey.thumb_id`, `cover_id` | `survey-thumb`, `survey-cover` |
| `forms:collection/<id>` | `SurveyCollection.thumb_id`, `cover_id` | `collection-thumb`, `collection-cover` |
| `forms:section/<id>` | `Section.cover_asset_id` | `section-cover` |
| `forms:question/<id>` | `Question.cover_asset_id` | `question-cover` |
| `forms:option/<id>` | `AnswerSchemaOption.image_asset_id` | `option-image` |
| `forms:attempt/<id>` | a `UserSurvey` snapshot's copies of the above | the template column's label |
| `forms:answer/<id>` | `UserAnswer.file_asset_id` | `answer-file` |

`org` is the survey's (or collection's) `organization_id`, None when it has
none. `user` is set only on an answer file: the respondent's Keycloak subject
(`User.id`). Forms records no author for templates, and an attempt's copies of
template artwork must not relabel the template's asset with a learner.

Live path: model signals (`register`) for the rows written with `save()` and
`delete()`; `soft_delete` releases the group it stamps; `create_survey_snapshot`
claims the attempt. A snapshot never changes after enrolment, so an attempt is
claimed once and released when it is deleted. Every call runs after commit and
is best effort: a failure is logged and never fails the request. The backfill
(`manage.py backfill_media_claims`) is idempotent and repairs anything missed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save

from media.client import build_client

logger = logging.getLogger(__name__)

PREFIX = "forms"

#: `(asset_id, ref, org, user, collection)`, as `pkg_media.backfill_claims` takes.
Row = Tuple[str, str, Optional[str], Optional[str], Optional[str]]


def asset_key(value: Any) -> Optional[str]:
    """The id as a lower-case UUID string, or None for an empty or malformed
    column (they are client-written strings)."""
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError:
        return None


def ref(record: str, pk: Any) -> str:
    return f"{PREFIX}:{record}/{pk}"


def _org(value: Any) -> Optional[str]:
    return str(value) if value else None


# ── Sending ─────────────────────────────────────────────────────────────


def _send(
    ref_: str,
    claim: Mapping[str, str],
    release: Iterable[str],
    org: Optional[str],
    user: Optional[str],
) -> None:
    """Claim `claim` (asset id -> collection) and release `release` under
    `ref_`, now. Best effort: nothing raises."""
    release = sorted(set(release) - set(claim))
    if not claim and not release:
        return
    client = build_client()
    if client is None:
        return
    by_collection: Dict[str, List[str]] = {}
    for asset_id, collection in claim.items():
        by_collection.setdefault(collection, []).append(asset_id)
    try:
        for collection, ids in sorted(by_collection.items()):
            client.assets.claim(ids, ref=ref_, org=org, user=user, collection=collection)
        if release:
            client.assets.release(release, ref=ref_)
    except Exception as exc:  # noqa: BLE001 — never fail the user's request
        logger.warning(
            "Media claims for %s failed (the backfill repairs it): %s: %s", ref_, type(exc).__name__, exc
        )


def _after_commit(
    ref_: str,
    claim: Mapping[str, str],
    release: Iterable[str] = (),
    org: Optional[str] = None,
    user: Optional[str] = None,
) -> None:
    claim, release = dict(claim), list(release)
    if not claim and not release:
        return
    transaction.on_commit(lambda: _send(ref_, claim, release, org, user), robust=True)


# ── Records ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Slot:
    """One kind of record that holds asset ids in `fields` (column ->
    collection label)."""

    record: str
    fields: Mapping[str, str]
    org: Callable[[Any], Optional[str]]
    user: Callable[[Any], Optional[str]] = lambda instance: None

    def assets(self, values: Mapping[str, Any]) -> Dict[str, str]:
        """asset id -> collection, for a live row's `values`."""
        if values.get("deleted_at") is not None:
            return {}
        out: Dict[str, str] = {}
        for field, collection in self.fields.items():
            key = asset_key(values.get(field))
            if key is not None:
                out.setdefault(key, collection)
        return out


def _survey_org(survey_id: Any) -> Optional[str]:
    from surveys.models import Survey

    if survey_id is None:
        return None
    return _org(Survey._base_manager.filter(pk=survey_id).values_list("organization_id", flat=True).first())


def _question_survey_id(question: Any) -> Any:
    from surveys.models import Section

    if question.survey_id is not None:
        return question.survey_id
    if question.section_id is None:
        return None
    return Section._base_manager.filter(pk=question.section_id).values_list("survey_id", flat=True).first()


def _attempt_org(user_survey_id: Any) -> Optional[str]:
    from user_surveys.models import UserSurvey

    if user_survey_id is None:
        return None
    return _org(
        UserSurvey.objects.filter(pk=user_survey_id).values_list("survey__organization_id", flat=True).first()
    )


def _answer_user(answer: Any) -> Optional[str]:
    from user_surveys.models import UserSurvey

    if answer.user_id:
        return str(answer.user_id)
    if answer.user_survey_id is None:
        return None
    user = UserSurvey.objects.filter(pk=answer.user_survey_id).values_list("user_id", flat=True).first()
    return str(user) if user else None


SURVEY_SLOT = Slot("survey", {"thumb_id": "survey-thumb", "cover_id": "survey-cover"}, lambda s: _org(s.organization_id))
COLLECTION_SLOT = Slot(
    "collection", {"thumb_id": "collection-thumb", "cover_id": "collection-cover"}, lambda c: _org(c.organization_id)
)
SECTION_SLOT = Slot("section", {"cover_asset_id": "section-cover"}, lambda s: _survey_org(s.survey_id))
QUESTION_SLOT = Slot("question", {"cover_asset_id": "question-cover"}, lambda q: _survey_org(_question_survey_id(q)))
OPTION_SLOT = Slot("option", {"image_asset_id": "option-image"}, lambda o: _survey_org(o.survey_id))
ANSWER_SLOT = Slot("answer", {"file_asset_id": "answer-file"}, lambda a: _attempt_org(a.user_survey_id), _answer_user)


def _slots() -> Dict[type, Slot]:
    from survey_collections.models import SurveyCollection
    from surveys.models import AnswerSchemaOption, Question, Section, Survey
    from user_surveys.models import UserAnswer

    return {
        Survey: SURVEY_SLOT,
        SurveyCollection: COLLECTION_SLOT,
        Section: SECTION_SLOT,
        Question: QUESTION_SLOT,
        AnswerSchemaOption: OPTION_SLOT,
        UserAnswer: ANSWER_SLOT,
    }


def _columns(model: type, slot: Slot) -> List[str]:
    names = {f.name for f in model._meta.concrete_fields}
    return [*slot.fields, *(["deleted_at"] if "deleted_at" in names else [])]


def _values(instance: Any, columns: Sequence[str]) -> Dict[str, Any]:
    return {c: getattr(instance, c, None) for c in columns}


_BEFORE = "_media_claims_before"


def _pre_save(slot: Slot):
    def handler(sender, instance, raw=False, update_fields=None, **kwargs):
        columns = _columns(sender, slot)
        if raw or (update_fields is not None and not set(update_fields) & set(columns)):
            setattr(instance, _BEFORE, None)
            return
        before: Dict[str, str] = {}
        if instance.pk is not None:
            row = sender._base_manager.filter(pk=instance.pk).values(*columns).first()
            if row is not None:
                before = slot.assets(row)
        setattr(instance, _BEFORE, before)

    return handler


def _post_save(slot: Slot):
    def handler(sender, instance, raw=False, **kwargs):
        before = getattr(instance, _BEFORE, None)
        if raw or before is None:
            return
        setattr(instance, _BEFORE, None)
        now = slot.assets(_values(instance, _columns(sender, slot)))
        added = {k: v for k, v in now.items() if k not in before}
        dropped = [k for k in before if k not in now]
        if not added and not dropped:
            return
        org = slot.org(instance) if added else None
        user = slot.user(instance) if added else None
        _after_commit(ref(slot.record, instance.pk), added, dropped, org, user)

    return handler


def _post_delete(slot: Slot):
    def handler(sender, instance, **kwargs):
        held = slot.assets(_values(instance, _columns(sender, slot)))
        if held:
            _after_commit(ref(slot.record, instance.pk), {}, held)

    return handler


# ── Attempts (snapshots) ────────────────────────────────────────────────


def attempt_assets(user_survey_id: Any) -> Dict[str, str]:
    """asset id -> collection of one attempt's snapshot: its artwork and its
    copies of section and question covers and option images (answer files are
    their own records)."""
    from user_surveys.models import UserAnswerOption, UserQuestion, UserSection, UserSurvey

    out: Dict[str, str] = {}

    def add(values: Iterable[Any], collection: str) -> None:
        for value in values:
            key = asset_key(value)
            if key is not None:
                out.setdefault(key, collection)

    for thumb, cover in UserSurvey.objects.filter(pk=user_survey_id).values_list("thumb_id", "cover_id"):
        add([thumb], SURVEY_SLOT.fields["thumb_id"])
        add([cover], SURVEY_SLOT.fields["cover_id"])
    add(UserSection.objects.filter(user_survey_id=user_survey_id).values_list("cover_asset_id", flat=True), SECTION_SLOT.fields["cover_asset_id"])
    add(UserQuestion.objects.filter(user_survey_id=user_survey_id).values_list("cover_asset_id", flat=True), QUESTION_SLOT.fields["cover_asset_id"])
    add(UserAnswerOption.objects.filter(user_survey_id=user_survey_id).values_list("image_asset_id", flat=True), OPTION_SLOT.fields["image_asset_id"])
    return out


def claim_attempt(user_survey: Any) -> None:
    """After commit, claim a snapshot just written (`create_survey_snapshot`)."""
    held = attempt_assets(user_survey.pk)
    if held:
        _after_commit(ref("attempt", user_survey.pk), held, (), _attempt_org(user_survey.pk))


def _attempt_pre_delete(sender, instance, **kwargs):
    # Before the cascade removes the snapshot rows; released only on commit.
    held = attempt_assets(instance.pk)
    if held:
        _after_commit(ref("attempt", instance.pk), {}, held)


# ── Soft delete ─────────────────────────────────────────────────────────


def release_soft_deleted(model: type, pks: Iterable[Any]) -> None:
    """After commit, release what the rows `pks` of `model` held. `soft_delete`
    calls it for the group it stamps with `update()` (no signal fires)."""
    slot = _slots()[model]
    pks = list(pks)
    if not pks:
        return
    for row in model._base_manager.filter(pk__in=pks).values("pk", *slot.fields):
        held = slot.assets(row)
        if held:
            _after_commit(ref(slot.record, row["pk"]), {}, held)


# ── Backfill ────────────────────────────────────────────────────────────


def backfill_rows() -> Iterator[Row]:
    """`(asset_id, ref, org, user, collection)` for every asset id a live
    forms record holds. A row of a soft-deleted survey, collection, section,
    question or option is skipped, and so is a builder row under a deleted
    survey or section."""
    from survey_collections.models import SurveyCollection
    from surveys.models import AnswerSchemaOption, Question, Section, Survey
    from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSection, UserSurvey

    def rows(slot: Slot, record_ref: str, org: Any, user: Any, values: Mapping[str, Any]) -> Iterator[Row]:
        for key, collection in slot.assets(values).items():
            yield key, record_ref, _org(org), (str(user) if user else None), collection

    for pk, org, thumb, cover in (
        Survey.objects.filter(deleted_at__isnull=True)
        .values_list("pk", "organization_id", "thumb_id", "cover_id").order_by("pk").iterator()
    ):
        yield from rows(SURVEY_SLOT, ref("survey", pk), org, None, {"thumb_id": thumb, "cover_id": cover})

    for pk, org, thumb, cover in (
        SurveyCollection.objects.filter(deleted_at__isnull=True)
        .values_list("pk", "organization_id", "thumb_id", "cover_id").order_by("pk").iterator()
    ):
        yield from rows(COLLECTION_SLOT, ref("collection", pk), org, None, {"thumb_id": thumb, "cover_id": cover})

    with_cover = ~Q(cover_asset_id__isnull=True) & ~Q(cover_asset_id="")
    for pk, org, cover in (
        Section.objects.filter(with_cover, survey__deleted_at__isnull=True)
        .values_list("pk", "survey__organization_id", "cover_asset_id").order_by("pk").iterator()
    ):
        yield from rows(SECTION_SLOT, ref("section", pk), org, None, {"cover_asset_id": cover})

    for pk, org, legacy_org, cover in (
        Question.objects.filter(with_cover)
        .filter(Q(survey__isnull=False, survey__deleted_at__isnull=True)
                | Q(survey__isnull=True, section__deleted_at__isnull=True, section__survey__deleted_at__isnull=True))
        .values_list("pk", "survey__organization_id", "section__survey__organization_id", "cover_asset_id")
        .order_by("pk").iterator()
    ):
        yield from rows(QUESTION_SLOT, ref("question", pk), org or legacy_org, None, {"cover_asset_id": cover})

    for pk, org, image in (
        AnswerSchemaOption.objects
        .filter(survey__deleted_at__isnull=True, question__deleted_at__isnull=True)
        .exclude(image_asset_id__isnull=True).exclude(image_asset_id="")
        .values_list("pk", "survey__organization_id", "image_asset_id").order_by("pk").iterator()
    ):
        yield from rows(OPTION_SLOT, ref("option", pk), org, None, {"image_asset_id": image})

    # Attempts: the snapshot's copies, under the attempt's ref, each with its
    # template column's label (`attempt_assets`).
    for pk, org, thumb, cover in (
        UserSurvey.objects.values_list("pk", "survey__organization_id", "thumb_id", "cover_id").order_by("pk").iterator()
    ):
        yield from rows(SURVEY_SLOT, ref("attempt", pk), org, None, {"thumb_id": thumb, "cover_id": cover})
    for model, column, slot in (
        (UserSection, "cover_asset_id", SECTION_SLOT),
        (UserQuestion, "cover_asset_id", QUESTION_SLOT),
        (UserAnswerOption, "image_asset_id", OPTION_SLOT),
    ):
        for attempt, org, value in (
            model.objects.filter(user_survey__isnull=False)
            .exclude(**{f"{column}__isnull": True}).exclude(**{column: ""})
            .values_list("user_survey_id", "user_survey__survey__organization_id", column)
            .order_by("user_survey_id", "pk").iterator()
        ):
            yield from rows(slot, ref("attempt", attempt), org, None, {column: value})

    for pk, org, user, attempt_user, value in (
        UserAnswer.objects.exclude(file_asset_id__isnull=True).exclude(file_asset_id="")
        .values_list("pk", "user_survey__survey__organization_id", "user_id", "user_survey__user_id", "file_asset_id")
        .order_by("pk").iterator()
    ):
        yield from rows(ANSWER_SLOT, ref("answer", pk), org, user or attempt_user, {"file_asset_id": value})


# ── Wiring ──────────────────────────────────────────────────────────────

_registered = False


def register() -> None:
    """Connect the live path (`MediaConfig.ready`). Idempotent."""
    global _registered
    if _registered:
        return
    _registered = True
    from user_surveys.models import UserSurvey

    for model, slot in _slots().items():
        uid = f"media.asset_claims.{model.__name__}"
        pre_save.connect(_pre_save(slot), sender=model, weak=False, dispatch_uid=uid)
        post_save.connect(_post_save(slot), sender=model, weak=False, dispatch_uid=uid)
        post_delete.connect(_post_delete(slot), sender=model, weak=False, dispatch_uid=uid)
    pre_delete.connect(_attempt_pre_delete, sender=UserSurvey, weak=False, dispatch_uid="media.asset_claims.UserSurvey")
