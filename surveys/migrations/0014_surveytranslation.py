from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0013_backfill_prices"),
    ]

    operations = [
        migrations.CreateModel(
            name="SurveyTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                ("title", models.CharField(max_length=255, null=True, blank=True)),
                ("description", models.TextField(null=True, blank=True)),
                ("short_description", models.CharField(max_length=300, null=True, blank=True)),
                ("slug", models.CharField(max_length=255, null=True, blank=True)),
                (
                    "survey",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.survey"),
                ),
            ],
            options={
                "db_table": "surveys_surveytranslation",
            },
        ),
        migrations.AddConstraint(
            model_name="surveytranslation",
            constraint=models.UniqueConstraint(fields=("survey", "language"), name="uq_survey_language"),
        ),
        migrations.AddIndex(
            model_name="surveytranslation",
            index=models.Index(fields=["survey", "language"], name="ix_survey_tr_survey_lang"),
        ),
    ]
