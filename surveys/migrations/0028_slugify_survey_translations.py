"""
Populate slug from title for each SurveyTranslation that has a title but no slug.
Uses Django's slugify with allow_unicode=True to support Arabic and other scripts.
"""
from django.db import migrations
from django.utils.text import slugify


def forwards(apps, schema_editor):
    SurveyTranslation = apps.get_model("surveys", "SurveyTranslation")

    for translation in SurveyTranslation.objects.filter(slug__isnull=True).exclude(title__isnull=True):
        base_slug = slugify(translation.title, allow_unicode=True)
        if not base_slug:
            continue

        slug = base_slug
        counter = 1
        while SurveyTranslation.objects.filter(
            slug=slug, language=translation.language,
        ).exclude(pk=translation.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        translation.slug = slug
        translation.save(update_fields=["slug"])

    # Also fill empty-string slugs
    for translation in SurveyTranslation.objects.filter(slug="").exclude(title__isnull=True):
        base_slug = slugify(translation.title, allow_unicode=True)
        if not base_slug:
            continue

        slug = base_slug
        counter = 1
        while SurveyTranslation.objects.filter(
            slug=slug, language=translation.language,
        ).exclude(pk=translation.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        translation.slug = slug
        translation.save(update_fields=["slug"])


def backwards(apps, schema_editor):
    pass  # No need to undo slug generation


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0027_remove_survey_price"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
