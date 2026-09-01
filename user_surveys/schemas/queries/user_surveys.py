from dataclasses import fields as dc_fields

import strawberry
from strawberry.types import Info
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
from user_surveys.inputs import UserSurveyFilters, UserSurveyFiltersInput, UserSurveysListInput
from user_surveys.types import UserSurveysResultsGQL
from user_surveys.models import UserSurvey
from ..common import RequireAuth
from app.graphql_ids import as_pk


def _caller_has_submissions_read(info: Info) -> bool:
    auth_ctx = getattr(info.context, "auth_context", None)
    if auth_ctx is None:
        return False
    if is_platform_context(auth_ctx):
        return True
    try:
        auth_ctx.require(Permission.SUBMISSION_READ.value)
    except MissingPermission:
        return False
    return True


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
        is_admin = _caller_has_submissions_read(info)
        qs = UserSurvey.objects.all() if is_admin else UserSurvey.objects.filter(user=django_user)
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
