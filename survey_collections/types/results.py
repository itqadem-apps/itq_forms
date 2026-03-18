from __future__ import annotations

from typing import List

import strawberry

from app.schema_common import FacetGQL, FacetValueGQL
from .collection import SurveyCollectionType


@strawberry.type
class SurveyCollectionsResultsGQL:
    items: List[SurveyCollectionType]
    total: int
    facets: List[FacetGQL]
