"""Provision the Keycloak client and audience mappers for itq_forms.

In pkg_auth v1+, Keycloak handles authentication only. This command
ensures the service's Keycloak client exists with the correct audience
configuration. It does NOT provision roles or permissions — those live
in the ACL database (managed by the deploy-time
``pkg-auth-sync-catalog`` step).

Usage::

    python manage.py provision_keycloak
"""
import json

from django.core.management.base import BaseCommand
from pkg_auth.admin import ensure_keycloak_client_from_env


class Command(BaseCommand):
    help = "Provision the Keycloak client + audience mappers for this service."

    def handle(self, *args, **options):
        summary = ensure_keycloak_client_from_env(
            permissions=[],
            frontend_client_ids=["frontend-admin", "frontend-web"],
            strict_roles=False,
            strict_audience=True,
        )
        self.stdout.write(json.dumps({"ok": True, **summary}, indent=2))
