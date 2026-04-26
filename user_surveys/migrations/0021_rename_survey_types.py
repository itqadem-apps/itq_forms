"""
Align UserSurvey snapshot survey_type values with renamed assessment types:
questionnaire -> assessment, smart_form -> form.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    UserSurvey = apps.get_model("user_surveys", "UserSurvey")
    UserSurvey.objects.filter(survey_type="questionnaire").update(survey_type="assessment")
    UserSurvey.objects.filter(survey_type="smart_form").update(survey_type="form")


def backwards(apps, schema_editor):
    UserSurvey = apps.get_model("user_surveys", "UserSurvey")
    UserSurvey.objects.filter(survey_type="assessment").update(survey_type="questionnaire")
    UserSurvey.objects.filter(survey_type="form").update(survey_type="smart_form")


class Migration(migrations.Migration):

    dependencies = [
        ("user_surveys", "0020_termination_reason"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]