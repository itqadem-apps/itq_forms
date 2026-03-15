"""
Add cover_id and thumb_id to Survey, migrate data from SurveyMediaAsset, then drop the model.
"""
from django.db import migrations, models


def forwards(apps, schema_editor):
    SurveyMediaAsset = apps.get_model("surveys", "SurveyMediaAsset")
    Survey = apps.get_model("surveys", "Survey")

    # Batch update covers
    for asset in SurveyMediaAsset.objects.filter(asset_type="cover"):
        Survey.objects.filter(pk=asset.survey_id).update(cover_id=asset.asset_id)

    # Batch update thumbnails
    for asset in SurveyMediaAsset.objects.filter(asset_type="thumbnail"):
        Survey.objects.filter(pk=asset.survey_id).update(thumb_id=asset.asset_id)


def backwards(apps, schema_editor):
    SurveyMediaAsset = apps.get_model("surveys", "SurveyMediaAsset")
    Survey = apps.get_model("surveys", "Survey")

    for survey in Survey.objects.filter(cover_id__isnull=False):
        SurveyMediaAsset.objects.create(
            survey_id=survey.pk,
            asset_id=survey.cover_id,
            asset_type="cover",
        )
    for survey in Survey.objects.filter(thumb_id__isnull=False):
        SurveyMediaAsset.objects.create(
            survey_id=survey.pk,
            asset_id=survey.thumb_id,
            asset_type="thumbnail",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0024_move_recommendations_to_own_app"),
    ]

    operations = [
        # 1. Add new columns
        migrations.AddField(
            model_name="survey",
            name="cover_id",
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="survey",
            name="thumb_id",
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
        # 2. Migrate data
        migrations.RunPython(forwards, backwards),
        # 3. Remove the old model
        migrations.DeleteModel(name="SurveyMediaAsset"),
    ]
