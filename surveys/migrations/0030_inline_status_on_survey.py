"""
Replace Status FK with a CharField on Survey.
Backfill status from the related Status row, then drop the FK and delete the Status table.
"""
from django.db import migrations, models


def forwards(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    for survey in Survey.objects.select_related("status").filter(status__isnull=False):
        Survey.objects.filter(pk=survey.pk).update(status_char=survey.status.status)


def backwards(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    Status = apps.get_model("surveys", "Status")
    for survey in Survey.objects.exclude(status_char="draft"):
        status_obj = Status.objects.create(survey=survey, status=survey.status_char)
        Survey.objects.filter(pk=survey.pk).update(status=status_obj)


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0029_rename_survey_types"),
    ]

    operations = [
        # 1. Add temporary CharField
        migrations.AddField(
            model_name="survey",
            name="status_char",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending", "Pending"),
                    ("published", "Published"),
                    ("archived", "Archived"),
                    ("suspended", "Suspended"),
                    ("canceled", "Canceled"),
                    ("rejected", "Rejected"),
                    ("approved", "Approved"),
                    ("started", "Started"),
                    ("ended", "Ended"),
                ],
                default="draft",
                max_length=20,
                verbose_name="Status",
            ),
        ),
        # 2. Backfill from FK
        migrations.RunPython(forwards, backwards),
        # 3. Remove FK
        migrations.RemoveField(
            model_name="survey",
            name="status",
        ),
        # 4. Rename temp field to status
        migrations.RenameField(
            model_name="survey",
            old_name="status_char",
            new_name="status",
        ),
        # 5. Delete Status model
        migrations.DeleteModel(
            name="Status",
        ),
    ]
