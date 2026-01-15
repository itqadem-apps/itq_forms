from django.core.management.base import BaseCommand

from django.conf import settings
from app.permissions import Permission
from pkg_auth.admin import ensure_keycloak_client_from_env
class Command(BaseCommand):
    help = 'Prints the current date and time'
    
    def handle(self, *args, **options):
        permissions = [p.value for p in Permission]

        # Run the env-based helper (reads KEYCLOAK_* and APP_NAME/SERVICE_NAME)
        summary = ensure_keycloak_client_from_env(
            permissions=permissions,
            frontend_client_ids=["frontend-admin", "frontend-web"],
            strict_roles=True,
            strict_audience=True,
            client_id=settings.KEYCLOAK_CLIENT_ID
        )
