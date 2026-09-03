from dataclasses import fields as dc_fields

import strawberry
from strawberry.types import Info
from django.db.models import Q, QuerySet
from django.contrib.auth.base_user import AbstractBaseUser
from pkg_auth.authorization import MissingPermission
from pkg_filters.integrations.django import DjangoQueryContext

from app.auth_utils import with_django_user
from app.permissions import Permission
from app.platform import is_platform_context
from user_surveys.filters import (
    UserSurveyProjection,
    UserSurveySpec,
    user_surveys_pipeline,
    user_survey_sort_input_to_spec,
)
from user_surveys.child_projection import supervised_child_ids_for_org
from user_surveys.inputs import UserSurveyFilters, UserSurveyFiltersInput, UserSurveysListInput
from user_surveys.types import UserSurveysResultsGQL
from user_surveys.models import UserSurvey
from ..common import RequireAuth
from app.graphql_ids import as_pk


def _holds_submissions_read(auth_ctx) -> bool:
    try:
        auth_ctx.require(Permission.SUBMISSION_READ.value)
    except MissingPermission:
        return False
    return True


def _submissions_visible_to(info: Info, django_user) -> QuerySet:
    """The submissions this caller is allowed to read.

    Submitting has no organization: a parent can take a screening survey at
    home weeks before contacting any clinic, and ``UserSurvey`` accordingly
    carries no organization column. Organization access is therefore *derived*
    from the child's active supervisor relation at read time — the same
    consent path the rest of the system uses for children, and the reason
    revoking a clinic's relation revokes its access to the history too.

    - a platform context reads everything;
    - a ``submissions:read`` holder in a tenant context reads the submissions
      of the children its organization actively supervises;
    - adult self-submissions have no child and so no relation to derive from:
      they stay private to their submitter and platform admins;
    - everyone reads their own, whatever else they hold.

    The supervisor relation is read through ``accounts.ChildGuardian``, a
    read-only projection of ``itq_users``' ``child_guardians`` table fed by
    NATS (``accounts/messaging.py``). It is eventually consistent: a revoked
    relation stops granting access only once ``GuardianRelationEnded`` has
    been consumed.
    """
    own = Q(user=django_user)

    auth_ctx = getattr(info.context, "auth_context", None)
    if auth_ctx is None:
        return UserSurvey.objects.filter(own)
    if is_platform_context(auth_ctx):
        return UserSurvey.objects.all()
    if not _holds_submissions_read(auth_ctx):
        return UserSurvey.objects.filter(own)

    organization_id = getattr(auth_ctx, "organization_id", None)
    if not organization_id:
        return UserSurvey.objects.filter(own)

    supervised = Q(child_id__in=supervised_child_ids_for_org(organization_id))
    return UserSurvey.objects.filter(own | supervised)


@strawberry.type
class UserSurveyQuery:
    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def user_survey(
        self,
        info: Info,
        user_surveys_list_input: UserSurveysListInput | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserSurveysResultsGQL:
        qs = _submissions_visible_to(info, django_user)
        if user_surveys_list_input is None:
            user_surveys_list_input = UserSurveysListInput()
        filters_input = user_surveys_list_input.filters or UserSurveyFiltersInput()
        filters_data = {}
        for field in dc_fields(UserSurveyFilters):
            name = field.name
            if name in {"submitted_at", "evaluated_at"}:
                value = getattr(filters_input, name, None)
                filters_data[name] = value.to_vo() if value else None
                continue
            # Id filters arrive as ``ID`` — strings. The specs and the ORM
            # comparisons downstream expect the integer pk.
            if name == "id" or name.endswith("_id"):
                filters_data[name] = as_pk(getattr(filters_input, name, None))
                continue
            filters_data[name] = getattr(filters_input, name, None)

        spec = UserSurveySpec(
            limit=user_surveys_list_input.limit,
            offset=user_surveys_list_input.offset,
            projection=UserSurveyProjection(),
            filters=UserSurveyFilters(**filters_data),
            sort=user_survey_sort_input_to_spec(user_surveys_list_input.sort),
        )
        base_qs = user_surveys_pipeline.run(DjangoQueryContext(qs, spec)).stmt
        if filters_input.submitted is True:
            base_qs = base_qs.filter(submitted_at__isnull=False)
        elif filters_input.submitted is False:
            base_qs = base_qs.filter(submitted_at__isnull=True)
        if user_surveys_list_input.sort is None:
            base_qs = base_qs.order_by("-submitted_at")

        total = base_qs.count()
        items = list(
            base_qs[
                user_surveys_list_input.offset : user_surveys_list_input.offset
                + user_surveys_list_input.limit
            ]
        )
        return UserSurveysResultsGQL(items=items, total=total)
