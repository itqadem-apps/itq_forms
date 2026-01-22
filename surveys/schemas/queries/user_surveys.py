from dataclasses import fields as dc_fields

import strawberry
from django.contrib.auth.base_user import AbstractBaseUser
from pkg_filters.integrations.django import DjangoQueryContext

from app.auth_utils import with_django_user
from surveys.filters import (
    UserSurveyProjection,
    UserSurveySpec,
    user_surveys_pipeline,
    user_survey_sort_input_to_spec,
)
from surveys.inputs import UserSurveyFilters, UserSurveyFiltersInput, UserSurveysListInput
from surveys.types import UserSurveysResultsGQL
from user_surveys.models import UserSurvey
from ..common import RequireAuth


@strawberry.type
class UserSurveysQuery:
    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def user_surveys(
        self,
        info,
        user_surveys_list_input: UserSurveysListInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserSurveysResultsGQL:
        qs = UserSurvey.objects.filter(user=django_user)
        filters_input = user_surveys_list_input.filters or UserSurveyFiltersInput()
        filters_data = {}
        for field in dc_fields(UserSurveyFilters):
            name = field.name
            if name in {"submitted_at", "evaluated_at"}:
                value = getattr(filters_input, name, None)
                filters_data[name] = value.to_vo() if value else None
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
