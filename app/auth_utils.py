from __future__ import annotations

from functools import wraps
from inspect import signature

from django.contrib.auth import get_user_model


def get_django_user(info):
    ctx_user = getattr(info.context, "user", None)
    identity = getattr(ctx_user, "identity", None) if ctx_user else None
    subject = getattr(ctx_user, "keycloak_sub", None) or getattr(
        getattr(identity, "subject", None), "value", None
    )
    if not subject:
        raise ValueError("Authentication required.")

    preferred_username = getattr(identity, "preferred_username", None) if identity else None
    email_val = getattr(getattr(identity, "email", None), "value", None)
    first_name = getattr(identity, "first_name", "") if identity else ""
    last_name = getattr(identity, "last_name", "") if identity else ""

    UserModel = get_user_model()
    django_user, _created = UserModel.objects.get_or_create(
        id=subject,
        defaults={
            "username": preferred_username or subject,
            "email": email_val or "",
            "first_name": first_name or "",
            "last_name": last_name or "",
        },
    )
    return django_user


def with_django_user(fn):
    @wraps(fn)
    def wrapper(self, info, *args, **kwargs):
        kwargs["django_user"] = get_django_user(info)
        return fn(self, info, *args, **kwargs)

    orig_signature = signature(fn)
    params = [p for p in orig_signature.parameters.values() if p.name != "django_user"]
    wrapper.__signature__ = orig_signature.replace(parameters=params)
    wrapper.__annotations__ = {k: v for k, v in fn.__annotations__.items() if k != "django_user"}
    return wrapper
