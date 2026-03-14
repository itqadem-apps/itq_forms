"""
Move Recommendation, RecommendationTranslation, Action, ActionTranslation,
and RecommendedMaterial from surveys to recommendations app.

Uses SeparateDatabaseAndState so the database tables remain unchanged
(surveys_*) while Django's internal state tracks them under the
recommendations app.
"""
import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("surveys", "0023_fix_classification_fk_state"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Recommendation",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("deleted_at", models.DateTimeField(blank=True, null=True)),
                        ("description", models.TextField()),
                        ("created_at", models.DateTimeField(auto_created=True, blank=True, default=django.utils.timezone.now)),
                        ("updated_at", models.DateTimeField(auto_now=True, null=True, blank=True)),
                        ("option", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="option_recommendations", to="surveys.answerschemaoption")),
                        ("survey", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="recommendations", to="surveys.survey")),
                    ],
                    options={
                        "ordering": ["created_at"],
                        "verbose_name": "Recommendation",
                        "verbose_name_plural": "Recommendations",
                        "db_table": "surveys_recommendation",
                    },
                ),
                migrations.CreateModel(
                    name="RecommendationTranslation",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("recommendation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="recommendations.recommendation")),
                        ("language", models.CharField(max_length=10)),
                        ("description", models.TextField(null=True, blank=True)),
                    ],
                    options={
                        "db_table": "surveys_recommendationtranslation",
                    },
                ),
                migrations.AddConstraint(
                    model_name="recommendationtranslation",
                    constraint=models.UniqueConstraint(fields=("recommendation", "language"), name="uq_recommendation_language"),
                ),
                migrations.AddIndex(
                    model_name="recommendationtranslation",
                    index=models.Index(fields=["recommendation", "language"], name="ix_recommendation_tr_rec_lang"),
                ),
                migrations.CreateModel(
                    name="Action",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("title", models.CharField(blank=True, default=None, max_length=255, null=True, verbose_name="Title")),
                        ("description", models.TextField(blank=True, default=None, null=True, verbose_name="Description")),
                        ("upper_limit", models.FloatField(default=0, verbose_name="Upper Limit")),
                        ("lower_limit", models.FloatField(default=0, verbose_name="Lower Limit")),
                        ("survey", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="actions", to="surveys.survey")),
                    ],
                    options={
                        "ordering": ["id"],
                        "db_table": "surveys_action",
                    },
                ),
                migrations.CreateModel(
                    name="ActionTranslation",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("action", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="recommendations.action")),
                        ("language", models.CharField(max_length=10)),
                        ("title", models.CharField(max_length=255, null=True, blank=True)),
                        ("description", models.TextField(null=True, blank=True)),
                    ],
                    options={
                        "db_table": "surveys_actiontranslation",
                    },
                ),
                migrations.AddConstraint(
                    model_name="actiontranslation",
                    constraint=models.UniqueConstraint(fields=("action", "language"), name="uq_action_language"),
                ),
                migrations.AddIndex(
                    model_name="actiontranslation",
                    index=models.Index(fields=["action", "language"], name="ix_action_tr_action_lang"),
                ),
                migrations.CreateModel(
                    name="RecommendedMaterial",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("object_id", models.PositiveIntegerField()),
                        ("action", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recommended_materials", to="recommendations.action")),
                        ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype")),
                    ],
                    options={
                        "db_table": "surveys_recommendedmaterial",
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
