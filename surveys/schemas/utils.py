import dataclasses
import datetime
from typing import Any

import strawberry
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.dateparse import parse_duration


def input_to_dict(input_obj: Any, exclude: list[str] | None = None) -> dict[str, Any]:
    """
    Extract non-UNSET fields from a strawberry input dataclass into a plain dict.

    Iterates over all dataclass fields, skips any whose value is strawberry.UNSET,
    and skips any field name listed in `exclude`.
    """
    exclude = exclude or []
    return {
        f.name: getattr(input_obj, f.name)
        for f in dataclasses.fields(input_obj)
        if f.name not in exclude and getattr(input_obj, f.name) is not strawberry.UNSET
    }


def clone_instance(instance: models.Model, **overrides) -> models.Model:
    """
    Clone a Django model instance by copying its concrete fields into a new row.

    Skips primary key fields and auto_now fields (e.g. updated_at).
    Any keyword overrides replace the copied field values before saving.
    """
    data = {
        field.name: getattr(instance, field.name)
        for field in instance._meta.concrete_fields
        if not field.primary_key and not getattr(field, 'auto_now', False)
    }
    data.update(overrides)
    return instance.__class__.objects.create(**data)


def coerce_duration(value: Any) -> datetime.timedelta | None:
    """
    Turn a client duration string into a timedelta, or None for "no limit".

    `Survey.time_limit` is a DurationField, which GraphQL cannot express, so the
    input declares it as a plain `"H:MM:SS"` string. Postgres has a native
    interval column and would cast such a string itself, which is why the raw
    value reached the column unconverted for as long as it did -- but the same
    assignment raises on sqlite (the test database), and nothing validated the
    string, so a typo was stored as a silent cast error rather than a field
    error the admin could see.
    """
    if value in (None, ''):
        return None
    if isinstance(value, datetime.timedelta):
        return value
    parsed = parse_duration(value)
    if parsed is None:
        raise ValidationError({'time_limit': f'Not a duration: {value!r}. Expected "H:MM:SS".'})
    return parsed
