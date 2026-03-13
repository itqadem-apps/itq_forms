import strawberry
from typing import Optional

from app.auth import strawberry_auth

RequireAuth = strawberry_auth.require_authenticated()


@strawberry.type
class OperationResult:
    success: bool
    message: Optional[str] = None
