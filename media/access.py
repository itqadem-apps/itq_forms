"""Who may open which forms asset: forms' own rule behind its resolve
endpoints (`media.views`, `pkg_media.gate.AccessGate`).

One statement, a UNION over the columns that hold asset ids. Only ids forms
stores are ever allowed, so the endpoints never serve another service's asset.

- Survey and collection artwork (thumb, cover) of a live row: anyone.
- Section and question covers and option images of a live row of a published,
  live survey: anyone, as `Query.survey` hands that survey to anyone.
- The same, of any survey of the caller's organization (or any, for the
  platform org), when the caller holds that survey kind's read permission.
- Learner snapshot copies (`UserSurvey`, `UserSection`, `UserQuestion`,
  `UserAnswerOption`): the submissions the caller may read, which are their
  own plus, for `submissions:read`, those of children their organization
  supervises (`visible_submissions`, the `userSurvey` query's rule).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Set
from uuid import UUID

from django.db.models import Q, QuerySet
from pkg_auth.authorization import MissingPermission

from app.platform import PUBLIC_STATUS, is_platform_context
from app.permissions import PERMISSION_MAP
from survey_collections.models import SurveyCollection
from surveys.models import AnswerSchemaOption, Question, Section, Survey
from user_surveys.models import UserAnswerOption, UserQuestion, UserSection, UserSurvey


@dataclass(frozen=True)
class Viewer:
    """The signed-in caller: the Keycloak subject (`User.id`) and the
    organization context, which is None without a resolvable org header."""

    user_id: str
    auth_context: Any = None


def _readable_kinds(auth_ctx) -> list[str]:
    kinds = []
    for kind, actions in PERMISSION_MAP.items():
        try:
            auth_ctx.require(actions["read"].value)
        except MissingPermission:
            continue
        kinds.append(kind)
    return kinds


def _survey_scope(prefix: str, *, published: bool, org=None, kinds=None) -> Q:
    """Live surveys reached through `prefix` (`survey__`, `section__survey__`…)."""
    q = Q(**{f"{prefix}deleted_at__isnull": True})
    if published:
        q &= Q(**{f"{prefix}status": PUBLIC_STATUS})
    if org is not None:
        q &= Q(**{f"{prefix}organization_id": org})
    if kinds is not None:
        q &= Q(**{f"{prefix}survey_type__in": kinds})
    return q


def _item_arms(candidates: list[str], **scope) -> list[QuerySet]:
    """Section/question covers and option images of live rows of the surveys
    `scope` selects. A legacy question has no `survey_id` and belongs through
    its section (`forms:AD-23`)."""
    return [
        Section.objects.filter(cover_asset_id__in=candidates)
        .filter(_survey_scope("survey__", **scope))
        .values_list("cover_asset_id", flat=True),
        Question.objects.filter(cover_asset_id__in=candidates)
        .filter(
            _survey_scope("survey__", **scope)
            | (Q(survey__isnull=True) & _survey_scope("section__survey__", **scope))
        )
        .values_list("cover_asset_id", flat=True),
        AnswerSchemaOption.objects.filter(image_asset_id__in=candidates)
        .filter(_survey_scope("survey__", **scope))
        .values_list("image_asset_id", flat=True),
    ]


def _staff_arms(candidates: list[str], auth_ctx) -> list[QuerySet]:
    kinds = _readable_kinds(auth_ctx)
    if not kinds:
        return []
    if is_platform_context(auth_ctx):
        return _item_arms(candidates, published=False, kinds=kinds)
    organization_id = getattr(auth_ctx, "organization_id", None)
    if organization_id is None:
        return []
    return _item_arms(candidates, published=False, org=organization_id.value, kinds=kinds)


def _snapshot_arms(candidates: list[str], viewer: Viewer) -> list[QuerySet]:
    from user_surveys.schemas.queries.user_surveys import visible_submissions

    visible = visible_submissions(viewer.auth_context, viewer.user_id).values("pk")
    return [
        UserSurvey.objects.filter(pk__in=visible, cover_id__in=candidates).values_list("cover_id", flat=True),
        UserSurvey.objects.filter(pk__in=visible, thumb_id__in=candidates).values_list("thumb_id", flat=True),
        UserSection.objects.filter(user_survey__in=visible, cover_asset_id__in=candidates)
        .values_list("cover_asset_id", flat=True),
        UserQuestion.objects.filter(user_survey__in=visible, cover_asset_id__in=candidates)
        .values_list("cover_asset_id", flat=True),
        UserAnswerOption.objects.filter(user_survey__in=visible, image_asset_id__in=candidates)
        .values_list("image_asset_id", flat=True),
    ]


def can_access(viewer: Optional[Viewer], asset_ids: Iterable[UUID | str]) -> Set[str]:
    """The ids in `asset_ids` `viewer` may open, lower-cased. `viewer` is None
    for an anonymous caller (or a stale token)."""
    wanted = {str(a).lower() for a in asset_ids}
    if not wanted:
        return set()
    # The columns are strings written by clients; match either case.
    candidates = sorted(wanted | {a.upper() for a in wanted})

    arms: list[QuerySet] = [
        Survey.objects.filter(deleted_at__isnull=True, cover_id__in=candidates).values_list("cover_id", flat=True),
        Survey.objects.filter(deleted_at__isnull=True, thumb_id__in=candidates).values_list("thumb_id", flat=True),
        SurveyCollection.objects.filter(deleted_at__isnull=True, cover_id__in=candidates)
        .values_list("cover_id", flat=True),
        SurveyCollection.objects.filter(deleted_at__isnull=True, thumb_id__in=candidates)
        .values_list("thumb_id", flat=True),
        *_item_arms(candidates, published=True),
    ]
    if viewer is not None:
        if viewer.auth_context is not None:
            arms.extend(_staff_arms(candidates, viewer.auth_context))
        arms.extend(_snapshot_arms(candidates, viewer))

    # Model orderings (`-created_at`) are not allowed inside a compound statement.
    first, *rest = (arm.order_by() for arm in arms)
    found = first.union(*rest)
    return {a.lower() for a in found if a} & wanted
