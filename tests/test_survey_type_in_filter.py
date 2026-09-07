"""`surveyTypeIn` matches several kinds at once.

A curriculum holds surveys, assessments and forms, so its member picker needs one
query spanning all three; the single-valued `surveyType` filter cannot say that.

Driven through the filter pipeline rather than the HTTP endpoint for the same
reason as `test_status_sort`: the GraphQL view needs pkg_auth installed, which
this environment does not have.
"""
from dataclasses import fields as dc_fields

import pytest

from pkg_filters.integrations.django import DjangoQueryContext
from surveys.filters import SurveyProjection, SurveySpec, pipeline
from surveys.inputs import SurveyFilters
from surveys.models import Survey

pytestmark = pytest.mark.django_db


def _filtered_survey_types(**filter_overrides):
    """Run the surveys pipeline with only the named filters set.

    `SurveyFilters` declares every field required, so a listing filtering on one
    thing still has to name them all.
    """
    filters = SurveyFilters(
        **{**{f.name: None for f in dc_fields(SurveyFilters)}, **filter_overrides}
    )
    spec = SurveySpec(
        limit=50,
        offset=0,
        projection=SurveyProjection(),
        filters=filters,
        sort=None,
    )
    qs = Survey.objects.filter(deleted_at__isnull=True)
    return sorted(s.survey_type for s in pipeline.run(DjangoQueryContext(qs, spec)).stmt)


def test_survey_type_in_matches_several_kinds():
    for kind in ("survey", "assessment", "form", "exam", "curriculum"):
        Survey.objects.create(survey_type=kind, status="published")

    assert _filtered_survey_types(survey_type_in=["survey", "assessment", "form"]) == [
        "assessment",
        "form",
        "survey",
    ]


def test_survey_type_in_absent_leaves_the_listing_unfiltered():
    for kind in ("survey", "exam"):
        Survey.objects.create(survey_type=kind, status="published")

    assert _filtered_survey_types() == ["exam", "survey"]
