from django.db import migrations, models
from django.utils.text import slugify


def _build_unique_slug(base_slug, existing, fallback_suffix):
    if not base_slug:
        return None
    slug = base_slug
    if slug not in existing:
        existing.add(slug)
        return slug
    slug = f"{base_slug}-{fallback_suffix}"
    existing.add(slug)
    return slug


def populate_survey_slugs(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    existing = set(
        Survey.objects.exclude(slug__isnull=True).exclude(slug="").values_list("slug", flat=True)
    )
    for survey in Survey.objects.all().only("id", "title", "slug"):
        if survey.slug:
            continue
        base = slugify(survey.title) if survey.title else None
        slug = _build_unique_slug(base, existing, survey.id)
        if slug:
            Survey.objects.filter(id=survey.id).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0002_section_submit_action_section_submit_action_target"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="slug",
            field=models.SlugField(blank=True, max_length=255, null=True),
        ),
        migrations.RunPython(populate_survey_slugs, migrations.RunPython.noop),
    ]
