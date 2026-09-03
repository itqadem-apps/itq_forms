"""Declarative permission catalog for itq_forms.

Reconciled into the ACL ``permissions`` + ``services`` tables at deploy
time by the k8s init containers, which run::

    pkg-auth-sync-catalog --service forms \\
        --catalog app.permission_catalog:CATALOG \\
        --service-manifest app.permission_catalog:SERVICE \\
        --db-url "$ACL_DATABASE_URL"

    pkg-auth-sync-services --services app.permission_catalog:SERVICES \\
        --db-url "$ACL_DATABASE_URL"

``SERVICE`` self-registers the service identity (name + localized
``display_label``); ``SERVICES`` overlays the vendor flags
(``auto_provision`` / ``saas_available``) — the only path that flips
those flags. Both syncs are non-pruning.

This file is purely declarative — the runtime process never writes to
``permissions`` (the runtime Vault role is SELECT-only on ACL).
"""
from __future__ import annotations

from pkg_auth.authorization import (
    CatalogEntry,
    PermissionKey,
    ServiceManifest,
    ServiceSpec,
)

from app.permissions import Permission

SERVICE_NAME = "forms"

SERVICE = ServiceManifest.make(
    SERVICE_NAME,
    {"en": "Forms", "ar": "النماذج"},
)

SERVICES: list[ServiceSpec] = [
    ServiceSpec.make(
        SERVICE_NAME,
        SERVICE.display_label,
        auto_provision=True,
        saas_available=True,
    ),
]


def _entry(perm: Permission, description: str) -> CatalogEntry:
    return CatalogEntry(key=PermissionKey(perm.value), description=description)


CATALOG: list[CatalogEntry] = [
    _entry(Permission.SURVEY_CREATE, "Create surveys"),
    _entry(Permission.SURVEY_READ, "Read surveys"),
    _entry(Permission.SURVEY_UPDATE, "Update surveys"),
    _entry(Permission.SURVEY_DELETE, "Delete surveys"),
    _entry(Permission.ASSESSMENT_CREATE, "Create assessments"),
    _entry(Permission.ASSESSMENT_READ, "Read assessments"),
    _entry(Permission.ASSESSMENT_UPDATE, "Update assessments"),
    _entry(Permission.ASSESSMENT_DELETE, "Delete assessments"),
    _entry(Permission.CURRICULUM_CREATE, "Create curriculums"),
    _entry(Permission.CURRICULUM_READ, "Read curriculums"),
    _entry(Permission.CURRICULUM_UPDATE, "Update curriculums"),
    _entry(Permission.CURRICULUM_DELETE, "Delete curriculums"),
    _entry(Permission.EXAM_CREATE, "Create exams"),
    _entry(Permission.EXAM_READ, "Read exams"),
    _entry(Permission.EXAM_UPDATE, "Update exams"),
    _entry(Permission.EXAM_DELETE, "Delete exams"),
    _entry(Permission.FORM_CREATE, "Create forms"),
    _entry(Permission.FORM_READ, "Read forms"),
    _entry(Permission.FORM_UPDATE, "Update forms"),
    _entry(Permission.FORM_DELETE, "Delete forms"),
    _entry(Permission.COLLECTION_CREATE, "Create collections"),
    _entry(Permission.COLLECTION_READ, "Read collections"),
    _entry(Permission.COLLECTION_UPDATE, "Update collections"),
    _entry(Permission.COLLECTION_DELETE, "Delete collections"),
    # Cross-cutting, and the only key here that is not tied to one
    # assessment kind. Granting it to a tenant role lets that role read
    # the submissions of the children its organization actively
    # supervises — and nothing else; the scoping lives in
    # ``user_surveys.schemas.queries.user_surveys._submissions_visible_to``.
    _entry(Permission.SUBMISSION_READ, "Read submissions"),
]
