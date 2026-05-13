from django.apps import AppConfig


class UserSurveysConfig(AppConfig):
    name = 'user_surveys'

    def ready(self) -> None:
        from user_surveys import subjects  # noqa: F401  -- registers event subjects
