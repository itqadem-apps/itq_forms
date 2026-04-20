from __future__ import annotations

from functools import wraps
from inspect import signature

from django.contrib.auth import get_user_model


def get_django_user(info):
    identity = getattr(info.context, "identity", None)
    if identity is None:
        raise ValueError("Authentication required.")

    subject = identity.subject_str
    email = identity.email_str or ""
    preferred_username = identity.preferred_username or subject
    first_name = identity.first_name or ""
    last_name = identity.last_name or ""

    UserModel = get_user_model()
    django_user, _created = UserModel.objects.get_or_create(
        id=subject,
        defaults={
            "username": preferred_username,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
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
