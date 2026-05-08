"""Declarative permission catalog for itq_forms.

Reconciled into the ACL ``permissions`` table at deploy time by the k8s
init container, which runs::

    pkg-auth-sync-catalog --service forms \\
        --catalog app.permission_catalog:CATALOG \\
        --db-url "$ACL_DATABASE_URL"

This file is purely declarative — the runtime process never writes to
``permissions`` (the runtime Vault role is SELECT-only on ACL).
"""
from __future__ import annotations

from pkg_auth.authorization import CatalogEntry, PermissionKey

from app.permissions import Permission

SERVICE_NAME = "forms"


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
]
