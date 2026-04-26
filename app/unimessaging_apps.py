import importlib

from django.apps import AppConfig


class UnimessagingOutboxConfig(AppConfig):
    name = "unimessaging.outbox_django"
    label = "unimessaging"
    verbose_name = "Unimessaging Outbox"

    def import_models(self):
        self.models_module = importlib.import_module(
            "unimessaging.outbox_django.models"
        )
