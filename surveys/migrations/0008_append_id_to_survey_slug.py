from django.db import migrations
from django.utils.text import slugify


def append_id_to_survey_slug(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    for survey in Survey.objects.all().only("id", "title", "slug"):
        if not survey.title:
            continue
        base = slugify(survey.title, allow_unicode=True)
        if not base:
            continue
        slug = f"{base}-{survey.id}"
        Survey.objects.filter(id=survey.id).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0007_remove_survey_assessment_type_survey_survey_type"),
    ]

    operations = [
        migrations.RunPython(append_id_to_survey_slug, migrations.RunPython.noop),
    ]
