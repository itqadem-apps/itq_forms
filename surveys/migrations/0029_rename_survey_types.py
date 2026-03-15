"""
Rename survey_type values: questionnaire -> assessment, smart_form -> form.
Updates both Survey and the choices on the field.
"""
from django.db import migrations, models


def forwards(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    Survey.objects.filter(survey_type="questionnaire").update(survey_type="assessment")
    Survey.objects.filter(survey_type="smart_form").update(survey_type="form")


def backwards(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    Survey.objects.filter(survey_type="assessment").update(survey_type="questionnaire")
    Survey.objects.filter(survey_type="form").update(survey_type="smart_form")


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0028_slugify_survey_translations"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="survey",
            name="survey_type",
            field=models.CharField(
                choices=[
                    ("survey", "Survey"),
                    ("assessment", "Assessment"),
                    ("curriculum", "Curriculum"),
                    ("exam", "Exam"),
                    ("form", "Form"),
                ],
                default="survey",
                max_length=255,
                verbose_name="Survey Type",
            ),
        ),
    ]
