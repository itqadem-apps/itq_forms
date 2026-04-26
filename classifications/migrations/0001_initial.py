"""
Move Classification and ClassificationTranslation from surveys to classifications app.

Uses SeparateDatabaseAndState so the database tables remain unchanged
(surveys_classification, surveys_classificationtranslation) while Django's
internal state tracks them under the classifications app.
"""
import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("surveys", "0020_survey_enable_anti_cheat"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Classification",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("deleted_at", models.DateTimeField(blank=True, null=True)),
                        ("name", models.CharField(blank=True, max_length=255, null=True)),
                        ("survey", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="classifications", to="surveys.survey")),
                        ("score", models.IntegerField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_created=True, blank=True, default=django.utils.timezone.now)),
                        ("updated_at", models.DateTimeField(auto_now=True, null=True, blank=True)),
                    ],
                    options={
                        "ordering": ["created_at"],
                        "verbose_name": "Classification",
                        "verbose_name_plural": "Classifications",
                        "db_table": "surveys_classification",
                    },
                ),
                migrations.CreateModel(
                    name="ClassificationTranslation",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("classification", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="classifications.classification")),
                        ("language", models.CharField(max_length=10)),
                        ("name", models.CharField(blank=True, max_length=255, null=True)),
                    ],
                    options={
                        "db_table": "surveys_classificationtranslation",
                    },
                ),
                migrations.AddConstraint(
                    model_name="classificationtranslation",
                    constraint=models.UniqueConstraint(fields=("classification", "language"), name="uq_classification_language"),
                ),
                migrations.AddIndex(
                    model_name="classificationtranslation",
                    index=models.Index(fields=["classification", "language"], name="ix_class_tr_lang"),
                ),
            ],
            database_operations=[],
        ),
    ]
