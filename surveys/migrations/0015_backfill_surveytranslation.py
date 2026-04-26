from django.db import migrations


def backfill_survey_translations(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    SurveyTranslation = apps.get_model("surveys", "SurveyTranslation")

    translations = []
    for survey in Survey.objects.all().iterator():
        if not survey.language:
            continue
        translations.append(
            SurveyTranslation(
                survey_id=survey.id,
                language=survey.language,
                title=survey.title,
                description=survey.description,
                short_description=survey.short_description,
                slug=survey.slug,
            )
        )

    if translations:
        SurveyTranslation.objects.bulk_create(translations, ignore_conflicts=True, batch_size=500)


def reverse_backfill(apps, schema_editor):
    SurveyTranslation = apps.get_model("surveys", "SurveyTranslation")
    SurveyTranslation.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0014_surveytranslation"),
    ]

    operations = [
        migrations.RunPython(backfill_survey_translations, reverse_backfill),
    ]
