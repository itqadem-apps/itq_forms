from app.auth import strawberry_auth

RequireAuth = strawberry_auth.require_authenticated()
