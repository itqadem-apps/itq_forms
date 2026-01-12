from dataclasses import fields as dc_fields
from typing import List

import strawberry
import strawberry_django
from django.db.models import Count
from django.contrib.auth import get_user_model
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths
from strawberry_django.optimizer import DjangoOptimizerExtension

from app.auth import strawberry_auth
from .filters import pipeline, survey_sort_input_to_spec, SurveyProjection, SurveySpec
from .inputs import SurveyFilters, SurveyFiltersInput, SurveysListInput
from .models import Survey
from .types import FacetGQL, FacetValueGQL, SurveyResultsGQL, SurveyType, UserAssessmentType
from user_surveys.models import UserAssessment
from user_surveys.services import enroll_user_in_assessment
from strawberry.types import Info

RequireAuth = strawberry_auth.require_authenticated()
UserModel = get_user_model()


@strawberry.type
class Query:
    @strawberry.field()
    def surveys(
            self,
            info,
            surveys_list_input: SurveysListInput,
    ) -> SurveyResultsGQL:
        paths = get_root_field_paths(info, "surveys")
        qs = Survey.objects.all()
        if has_any_under_prefix(paths, ("items", "contentType")):
            qs = qs.select_related("content_type")
        # Prefetching is delegated to strawberry_django optimizer to avoid
        # conflicting lookups when it applies its own Prefetch querysets.

        filters_input: SurveyFiltersInput | None = surveys_list_input.filters
        filters_data = {}
        for field in dc_fields(SurveyFilters):
            name = field.name
            if name in {"created_at", "updated_at"}:
                value = getattr(filters_input, name, None) if filters_input else None
                filters_data[name] = value.to_vo() if value else None
                continue
            filters_data[name] = getattr(filters_input, name, None) if filters_input else None

        spec = SurveySpec(
            limit=surveys_list_input.limit,
            offset=surveys_list_input.offset,
            projection=SurveyProjection(),
            filters=SurveyFilters(**filters_data),
            sort=survey_sort_input_to_spec(surveys_list_input.sort),
        )
        base_qs = pipeline.run(DjangoQueryContext(qs, spec)).stmt

        total = base_qs.count()
        items = base_qs[surveys_list_input.offset: surveys_list_input.offset + surveys_list_input.limit]

        facets: List[FacetGQL] = []
        if has_any_under_prefix(paths, ("facets",)):
            status_values = [
                FacetValueGQL(value=row["status__status"], count=row["count"])
                for row in base_qs.values("status__status")
                .annotate(count=Count("id"))
                .order_by("status__status")
            ]
            facets.append(FacetGQL(name="status", values=status_values))

            assessment_type_values = [
                FacetValueGQL(value=row["assessment_type"], count=row["count"])
                for row in base_qs.values("assessment_type")
                .annotate(count=Count("id"))
                .order_by("assessment_type")
            ]
            facets.append(FacetGQL(name="assessment_type", values=assessment_type_values))

            language_values = [
                FacetValueGQL(value=row["language"], count=row["count"])
                for row in base_qs.values("language").annotate(count=Count("id")).order_by("language")
            ]
            facets.append(FacetGQL(name="language", values=language_values))

        return SurveyResultsGQL(items=items, total=total, facets=facets)

    @strawberry.field()
    def survey(self, info: Info, id: int) -> SurveyType | None:
        try:
            return Survey.objects.get(pk=id)
        except Survey.DoesNotExist:
            return None

    @strawberry.field(permission_classes=[RequireAuth])
    def user_assessments(self, info: Info, limit: int = 20, offset: int = 0) -> list[UserAssessmentType]:
        ctx_user = getattr(info.context, "user", None)
        identity = getattr(ctx_user, "identity", None) if ctx_user else None
        subject = getattr(getattr(identity, "subject", None), "value", None)
        preferred_username = getattr(identity, "preferred_username", None) if identity else None
        email_val = getattr(getattr(identity, "email", None), "value", None)
        first_name = getattr(identity, "first_name", "") if identity else ""
        last_name = getattr(identity, "last_name", "") if identity else ""

        django_user, _created = UserModel.objects.get_or_create(
            id=subject,
            defaults={
                "username": preferred_username or subject,
                "email": email_val or "",
                "first_name": first_name or "",
                "last_name": last_name or "",
            },
        )

        qs = UserAssessment.objects.filter(user=django_user).order_by("-submitted_at")
        return list(qs[offset : offset + limit])


@strawberry.type
class Mutation:
    @strawberry.mutation(permission_classes=[RequireAuth])
    def enroll_assessment(self, info: Info, survey_id: int, child_id: str | None = None) -> UserAssessmentType:
        try:
            survey = Survey.objects.get(pk=survey_id)
        except Survey.DoesNotExist:
            raise ValueError(f"Survey not found: {survey_id}")

        ctx_user = getattr(info.context, "user", None)
        identity = getattr(ctx_user, "identity", None) if ctx_user else None
        subject = getattr(getattr(identity, "subject", None), "value", None)
        preferred_username = getattr(identity, "preferred_username", None) if identity else None
        email_val = getattr(getattr(identity, "email", None), "value", None)
        first_name = getattr(identity, "first_name", "") if identity else ""
        last_name = getattr(identity, "last_name", "") if identity else ""

        if not subject:
            raise ValueError("Authentication required to enroll in an assessment.")

        django_user, _created = UserModel.objects.get_or_create(
            id=subject,
            defaults={
                "username": preferred_username or subject,
                "email": email_val or "",
                "first_name": first_name or "",
                "last_name": last_name or "",
            },
        )

        user_assessment, _created = enroll_user_in_assessment(
            request_user=django_user,
            survey_id=survey.id,
            child_id=child_id,
        )
        return user_assessment

    @strawberry.field(permission_classes=[RequireAuth])
    def me(self, info: Info) -> str:
        return info.context.user.identity.preferred_username



schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
    ],
)
