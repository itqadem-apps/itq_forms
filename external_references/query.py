"""Helpers for applying ``ExternalReferenceFilterInput`` to a queryset."""

from __future__ import annotations

from django.db.models import QuerySet

from external_references.inputs import ExternalReferenceFilterInput


def apply_external_reference_filter(
    qs: QuerySet,
    filt: ExternalReferenceFilterInput | None,
    *,
    related_name: str = "external_references",
) -> QuerySet:
    """Filter ``qs`` by an external reference. Caller is responsible for ``.distinct()``.

    Returns the queryset unchanged when ``filt`` is None or all fields are unset.
    """
    if filt is None:
        return qs
    lookups = {}
    if filt.source_service is not None:
        lookups[f"{related_name}__source_service"] = filt.source_service
    if filt.source_model is not None:
        lookups[f"{related_name}__source_model"] = filt.source_model
    if filt.source_id is not None:
        lookups[f"{related_name}__source_id"] = filt.source_id
    if not lookups:
        return qs
    return qs.filter(**lookups)


def has_external_reference_filter(filt: ExternalReferenceFilterInput | None) -> bool:
    if filt is None:
        return False
    return any(
        getattr(filt, name, None) is not None
        for name in ("source_service", "source_model", "source_id")
    )
