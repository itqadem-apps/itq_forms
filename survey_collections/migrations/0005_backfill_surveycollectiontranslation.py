from django.db import migrations


def forwards(apps, schema_editor):
    SurveyCollection = apps.get_model("survey_collections", "SurveyCollection")
    SurveyCollectionTranslation = apps.get_model(
        "survey_collections", "SurveyCollectionTranslation"
    )

    translations = []
    for collection in SurveyCollection.objects.all():
        translations.append(
            SurveyCollectionTranslation(
                collection_id=collection.id,
                language=collection.language,
                title=collection.title,
                description=collection.description,
                short_description=collection.short_description,
                slug=collection.slug,
            )
        )

    if translations:
        SurveyCollectionTranslation.objects.bulk_create(translations)


def backwards(apps, schema_editor):
    SurveyCollectionTranslation = apps.get_model(
        "survey_collections", "SurveyCollectionTranslation"
    )
    SurveyCollectionTranslation.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("survey_collections", "0004_surveycollectiontranslation"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
