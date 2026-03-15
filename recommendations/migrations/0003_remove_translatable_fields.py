"""
Move description from Recommendation, and title+description from Action
to their respective Translation models.
Backfill translations, then drop the fields.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Recommendation = apps.get_model("recommendations", "Recommendation")
    RecommendationTranslation = apps.get_model("recommendations", "RecommendationTranslation")

    for r in Recommendation.objects.all():
        if r.description:
            RecommendationTranslation.objects.update_or_create(
                recommendation=r,
                language="default",
                defaults={"description": r.description},
            )

    Action = apps.get_model("recommendations", "Action")
    ActionTranslation = apps.get_model("recommendations", "ActionTranslation")

    for a in Action.objects.all():
        if a.title or a.description:
            ActionTranslation.objects.update_or_create(
                action=a,
                language="default",
                defaults={
                    "title": a.title,
                    "description": a.description,
                },
            )


def backwards(apps, schema_editor):
    Recommendation = apps.get_model("recommendations", "Recommendation")
    RecommendationTranslation = apps.get_model("recommendations", "RecommendationTranslation")

    for r in Recommendation.objects.all():
        t = RecommendationTranslation.objects.filter(recommendation=r).first()
        if t:
            r.description = t.description
            r.save(update_fields=["description"])

    Action = apps.get_model("recommendations", "Action")
    ActionTranslation = apps.get_model("recommendations", "ActionTranslation")

    for a in Action.objects.all():
        t = ActionTranslation.objects.filter(action=a).first()
        if t:
            a.title = t.title
            a.description = t.description
            a.save(update_fields=["title", "description"])


class Migration(migrations.Migration):

    dependencies = [
        ("recommendations", "0002_rename_tables"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="recommendation", name="description"),
        migrations.RemoveField(model_name="action", name="title"),
        migrations.RemoveField(model_name="action", name="description"),
    ]
