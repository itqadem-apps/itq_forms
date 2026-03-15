"""
Move name from Classification to ClassificationTranslation.
Backfill translations from existing Classification data, then drop the field.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Classification = apps.get_model("classifications", "Classification")
    ClassificationTranslation = apps.get_model("classifications", "ClassificationTranslation")

    for c in Classification.objects.all():
        if c.name:
            ClassificationTranslation.objects.update_or_create(
                classification=c,
                language="default",
                defaults={"name": c.name},
            )


def backwards(apps, schema_editor):
    Classification = apps.get_model("classifications", "Classification")
    ClassificationTranslation = apps.get_model("classifications", "ClassificationTranslation")

    for c in Classification.objects.all():
        translation = ClassificationTranslation.objects.filter(classification=c).first()
        if translation:
            c.name = translation.name
            c.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("classifications", "0002_rename_tables"),
    ]

    operations = [
        # 1. Backfill translations
        migrations.RunPython(forwards, backwards),
        # 2. Remove field from Classification
        migrations.RemoveField(model_name="classification", name="name"),
    ]
