"""
Move title, description, short_description, slug, language from Survey to SurveyTranslation.
Backfill translations from existing Survey data, then drop the fields.
"""
from django.db import migrations, models


def forwards(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    SurveyTranslation = apps.get_model("surveys", "SurveyTranslation")

    for survey in Survey.objects.all():
        lang = survey.language or "default"
        SurveyTranslation.objects.update_or_create(
            survey=survey,
            language=lang,
            defaults={
                "title": survey.title,
                "description": survey.description,
                "short_description": survey.short_description,
                "slug": survey.slug,
            },
        )


def backwards(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    SurveyTranslation = apps.get_model("surveys", "SurveyTranslation")

    for survey in Survey.objects.all():
        translation = SurveyTranslation.objects.filter(survey=survey).first()
        if translation:
            survey.title = translation.title
            survey.description = translation.description
            survey.short_description = translation.short_description
            survey.slug = translation.slug
            survey.language = translation.language
            survey.save(update_fields=["title", "description", "short_description", "slug", "language"])


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0025_survey_cover_thumb_remove_media_asset"),
    ]

    operations = [
        # 1. Backfill translations
        migrations.RunPython(forwards, backwards),
        # 2. Remove fields from Survey
        migrations.RemoveField(model_name="survey", name="title"),
        migrations.RemoveField(model_name="survey", name="description"),
        migrations.RemoveField(model_name="survey", name="short_description"),
        migrations.RemoveField(model_name="survey", name="slug"),
        migrations.RemoveField(model_name="survey", name="language"),
    ]
