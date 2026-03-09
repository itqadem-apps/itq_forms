import dataclasses
from typing import Any

import strawberry
from django.db import models


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
