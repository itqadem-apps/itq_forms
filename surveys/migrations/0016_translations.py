from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0015_backfill_surveytranslation"),
    ]

    operations = [
        migrations.CreateModel(
            name="SectionTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                ("title", models.CharField(max_length=255, null=True, blank=True)),
                ("description", models.TextField(null=True, blank=True)),
                (
                    "section",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.section"),
                ),
            ],
            options={
                "db_table": "surveys_sectiontranslation",
            },
        ),
        migrations.AddConstraint(
            model_name="sectiontranslation",
            constraint=models.UniqueConstraint(fields=("section", "language"), name="uq_section_language"),
        ),
        migrations.AddIndex(
            model_name="sectiontranslation",
            index=models.Index(fields=["section", "language"], name="ix_section_tr_section_lang"),
        ),
        migrations.CreateModel(
            name="QuestionTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                ("title", models.CharField(max_length=255, null=True, blank=True)),
                ("description", models.TextField(null=True, blank=True)),
                (
                    "question",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.question"),
                ),
            ],
            options={
                "db_table": "surveys_questiontranslation",
            },
        ),
        migrations.AddConstraint(
            model_name="questiontranslation",
            constraint=models.UniqueConstraint(fields=("question", "language"), name="uq_question_language"),
        ),
        migrations.AddIndex(
            model_name="questiontranslation",
            index=models.Index(fields=["question", "language"], name="ix_question_tr_question_lang"),
        ),
        migrations.CreateModel(
            name="AnswerSchemaTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                (
                    "schema",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.answerschema"),
                ),
            ],
            options={
                "db_table": "surveys_answerschematranslation",
            },
        ),
        migrations.AddConstraint(
            model_name="answerschematranslation",
            constraint=models.UniqueConstraint(fields=("schema", "language"), name="uq_answer_schema_language"),
        ),
        migrations.AddIndex(
            model_name="answerschematranslation",
            index=models.Index(fields=["schema", "language"], name="ix_ans_schema_tr_lang"),
        ),
        migrations.CreateModel(
            name="AnswerSchemaOptionTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                ("text", models.TextField(null=True, blank=True)),
                (
                    "option",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.answerschemaoption"),
                ),
            ],
            options={
                "db_table": "surveys_answerschemaoptiontranslation",
            },
        ),
        migrations.AddConstraint(
            model_name="answerschemaoptiontranslation",
            constraint=models.UniqueConstraint(fields=("option", "language"), name="uq_answer_schema_option_language"),
        ),
        migrations.AddIndex(
            model_name="answerschemaoptiontranslation",
            index=models.Index(fields=["option", "language"], name="ix_ans_opt_tr_lang"),
        ),
        migrations.CreateModel(
            name="ActionTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                ("title", models.CharField(max_length=255, null=True, blank=True)),
                ("description", models.TextField(null=True, blank=True)),
                (
                    "action",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.action"),
                ),
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
            name="RecommendationTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                ("description", models.TextField(null=True, blank=True)),
                (
                    "recommendation",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.recommendation"),
                ),
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
            name="ClassificationTranslation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=10)),
                ("name", models.CharField(max_length=255, null=True, blank=True)),
                (
                    "classification",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="translations", to="surveys.classification"),
                ),
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
    ]
