from django.db import migrations
from django.utils.text import slugify


def backfill_survey_slugs(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    existing = set(
        Survey.objects.exclude(slug__isnull=True).exclude(slug="").values_list("slug", flat=True)
    )
    qs = Survey.objects.filter(slug__isnull=True) | Survey.objects.filter(slug="")
    for survey in qs.only("id", "title", "slug"):
        base = slugify(survey.title) if survey.title else f"survey-{survey.id}"
        slug = base
        if slug in existing:
            slug = f"{base}-{survey.id}"
        existing.add(slug)
        Survey.objects.filter(id=survey.id).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0003_survey_slug"),
    ]

    operations = [
        migrations.RunPython(backfill_survey_slugs, migrations.RunPython.noop),
    ]
