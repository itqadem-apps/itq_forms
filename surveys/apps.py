from django.apps import AppConfig


class SurveysConfig(AppConfig):
    name = 'surveys'

    def ready(self) -> None:
        from surveys import subjects  # noqa: F401  -- registers event subjects
