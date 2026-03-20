from __future__ import annotations

from typing import List, Optional

import strawberry

from app.schema_common import CategoryFacetNodeGQL, PriceRangeFacetGQL
from .collection import SurveyCollectionType


@strawberry.type
class CollectionsFacetsGQL:
    categories: List[CategoryFacetNodeGQL]
    price: PriceRangeFacetGQL


@strawberry.type
class SurveyCollectionsResultsGQL:
    items: List[SurveyCollectionType]
    total: int
    facets: Optional[CollectionsFacetsGQL] = None
