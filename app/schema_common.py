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
