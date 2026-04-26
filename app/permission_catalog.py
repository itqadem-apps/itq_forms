"""Permission catalog for itq_forms, registered against the shared ACL DB on boot.

The keys mirror :class:`app.permissions.Permission`. Registration is
idempotent (UPSERT by key), so calling :func:`register_catalog_sync` on
every startup is safe.
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
]


def register_catalog_sync() -> None:
    from asgiref.sync import async_to_sync
    from pkg_auth.authorization.adapters.django_orm.repositories.permission_catalog import (
        DjangoPermissionCatalogRepository,
    )
    from pkg_auth.authorization.application.use_cases.register_permission_catalog import (
        RegisterPermissionCatalogUseCase,
    )

    repo = DjangoPermissionCatalogRepository()
    uc = RegisterPermissionCatalogUseCase(catalog_repo=repo)
    async_to_sync(uc.execute)(service_name=SERVICE_NAME, entries=CATALOG)
