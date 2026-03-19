from __future__ import annotations

from typing import List, Optional

import strawberry

from app.schema_common import CategoryFacetNodeGQL, FacetValueGQL
from .collection import SurveyCollectionType


@strawberry.type
class CollectionsFacetsGQL:
    status: List[FacetValueGQL]
    language: List[FacetValueGQL]
    type: List[FacetValueGQL]
    categories: List[CategoryFacetNodeGQL]


@strawberry.type
class SurveyCollectionsResultsGQL:
    items: List[SurveyCollectionType]
    total: int
    facets: Optional[CollectionsFacetsGQL] = None
