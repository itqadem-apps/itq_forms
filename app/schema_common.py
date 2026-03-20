from __future__ import annotations

import strawberry
from typing import List, Optional

from app.auth import strawberry_auth

RequireAuth = strawberry_auth.require_authenticated()


@strawberry.type
class OperationResult:
    success: bool
    message: Optional[str] = None


@strawberry.type
class FacetValueGQL:
    value: str
    count: int


@strawberry.type
class FacetGQL:
    name: str
    values: List[FacetValueGQL]


@strawberry.type
class PriceRangeFacetGQL:
    min: int
    max: int


@strawberry.type
class CategoryTranslationFacetGQL:
    language: str
    name: Optional[str]
    slug: Optional[str]


@strawberry.type
class CategoryFacetNodeGQL:
    id: str
    name: Optional[str]
    count: int
    path_text: Optional[str]
    translations: List[CategoryTranslationFacetGQL]
    children: List[CategoryFacetNodeGQL]
