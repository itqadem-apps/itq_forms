"""A survey or collection cannot be stored without an owning organization.

`SPEC-forms-organization-required` CAP-1 (#168). Rows created before CAP-1 of
the permission gates bound the owner from the caller were null-owned: refused
to every tenant and never published. They were assigned by hand on 2026-10-04,
and the column is NOT NULL from then on — the database refuses the next one
instead of a fallback quietly picking an owner.
"""
import uuid

import pytest
from django.db import IntegrityError, transaction

from survey_collections.models import SurveyCollection
from surveys.models import Survey

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.parametrize("model", [Survey, SurveyCollection])
def test_a_row_with_no_organization_is_refused(model):
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(organization_id=None)

    assert not model.objects.exists()


@pytest.mark.parametrize("model", [Survey, SurveyCollection])
def test_a_row_with_an_organization_is_stored(model):
    assert model.objects.create(organization_id=ORG).organization_id == ORG
