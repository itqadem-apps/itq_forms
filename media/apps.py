from django.apps import AppConfig


class MediaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "media"

    def ready(self):
        from media import asset_claims

        asset_claims.register()
