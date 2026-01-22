from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("survey_collections", "0003_remove_surveycollection_author_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SurveyCollectionTranslation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("language", models.CharField(blank=True, max_length=64, null=True)),
                ("title", models.CharField(blank=True, max_length=255, null=True)),
                ("description", models.TextField(blank=True, null=True)),
                ("short_description", models.CharField(blank=True, max_length=300, null=True)),
                ("slug", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "collection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="translations",
                        to="survey_collections.surveycollection",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["collection", "language"], name="ix_survey_col_tr_lang"),
                ],
            },
        ),
    ]
