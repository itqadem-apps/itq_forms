"""`UserAnswer.file_asset_id`: the asset a file question's answer uploaded (`forms-answer-file`).

Reverse: drops the column.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0031_report_regrade_anomalies"),
    ]

    operations = [
        migrations.AddField(
            model_name="useranswer",
            name="file_asset_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
