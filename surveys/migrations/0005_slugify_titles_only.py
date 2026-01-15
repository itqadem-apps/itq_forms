from django.db import migrations
from django.utils.text import slugify


def slugify_titles_only(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    for survey in Survey.objects.all().only("id", "title", "slug"):
        if not survey.title:
            continue
        slug = slugify(survey.title, allow_unicode=True)
        Survey.objects.filter(id=survey.id).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0004_backfill_survey_slug"),
    ]

    operations = [
        migrations.RunPython(slugify_titles_only, migrations.RunPython.noop),
    ]
