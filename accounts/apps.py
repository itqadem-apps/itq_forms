import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:
        from django.conf import settings

        from pkg_auth.authorization.adapters.django_orm.repositories.membership import (
            DjangoMembershipRepository,
        )
        from pkg_auth.authorization.adapters.django_orm.repositories.organization import (
            DjangoOrganizationRepository,
        )
        from pkg_auth.authorization.adapters.django_orm.repositories.user import (
            DjangoUserRepository,
        )
        from pkg_auth.authorization.application.use_cases.resolve_auth_context import (
            ResolveAuthContextUseCase,
        )
        from pkg_auth.authorization.application.use_cases.resolve_user_from_jwt import (
            ResolveUserFromJwtUseCase,
        )
        from pkg_auth.integrations.django import install_pkg_auth

        from app.platform import init_platform_org_id_sync

        if not settings.KEYCLOAK_BASE_URL or not settings.KEYCLOAK_REALM:
            # Local/dev bootstrap without Keycloak config — skip wiring so
            # migrations and unit tests can still run. Requests will 401.
            return

        user_repo = DjangoUserRepository()
        org_repo = DjangoOrganizationRepository()
        membership_repo = DjangoMembershipRepository()

        install_pkg_auth(
            keycloak_base_url=settings.KEYCLOAK_BASE_URL,
            realm=settings.KEYCLOAK_REALM,
            audience=settings.KEYCLOAK_AUDIENCE,
            resolve_user_use_case=ResolveUserFromJwtUseCase(user_repo=user_repo),
            resolve_use_case=ResolveAuthContextUseCase(membership_repo=membership_repo),
            organization_repo=org_repo,
        )

        try:
            init_platform_org_id_sync(org_repo)
        except Exception as exc:
            # ACL DB may not be reachable at import time (e.g. collectstatic,
            # migrate). The platform-org cache stays None and the helper
            # returns False; services that need it can re-init lazily.
            # Log so misconfiguration (missing 'platform' org row, ACL DB
            # unreachable) doesn't silently disable the platform-admin path.
            logger.warning(
                "pkg_auth: platform org bootstrap failed (%s): %s",
                type(exc).__name__,
                exc,
            )
