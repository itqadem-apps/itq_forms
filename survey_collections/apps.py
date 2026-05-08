from django.apps import AppConfig


class SurveyCollectionsConfig(AppConfig):
    name = 'survey_collections'

    def ready(self) -> None:
        from survey_collections import subjects  # noqa: F401  -- registers event subjects
