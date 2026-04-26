from django.db import migrations


def backfill_translations(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    Section = apps.get_model("surveys", "Section")
    Question = apps.get_model("surveys", "Question")
    AnswerSchema = apps.get_model("surveys", "AnswerSchema")
    AnswerSchemaOption = apps.get_model("surveys", "AnswerSchemaOption")
    Action = apps.get_model("surveys", "Action")
    Recommendation = apps.get_model("surveys", "Recommendation")
    Classification = apps.get_model("surveys", "Classification")

    SectionTranslation = apps.get_model("surveys", "SectionTranslation")
    QuestionTranslation = apps.get_model("surveys", "QuestionTranslation")
    AnswerSchemaTranslation = apps.get_model("surveys", "AnswerSchemaTranslation")
    AnswerSchemaOptionTranslation = apps.get_model("surveys", "AnswerSchemaOptionTranslation")
    ActionTranslation = apps.get_model("surveys", "ActionTranslation")
    RecommendationTranslation = apps.get_model("surveys", "RecommendationTranslation")
    ClassificationTranslation = apps.get_model("surveys", "ClassificationTranslation")

    survey_language = {
        row[0]: row[1]
        for row in Survey.objects.exclude(language__isnull=True).values_list("id", "language")
    }

    if not survey_language:
        return

    section_translations = []
    for section in Section.objects.all().iterator():
        lang = survey_language.get(section.survey_id)
        if not lang:
            continue
        section_translations.append(
            SectionTranslation(
                section_id=section.id,
                language=lang,
                title=section.title,
                description=section.description,
            )
        )
    if section_translations:
        SectionTranslation.objects.bulk_create(section_translations, ignore_conflicts=True, batch_size=500)

    question_translations = []
    for question in Question.objects.all().iterator():
        lang = survey_language.get(question.survey_id)
        if not lang:
            continue
        question_translations.append(
            QuestionTranslation(
                question_id=question.id,
                language=lang,
                title=question.title,
                description=question.description,
            )
        )
    if question_translations:
        QuestionTranslation.objects.bulk_create(question_translations, ignore_conflicts=True, batch_size=500)

    answer_schema_translations = []
    for schema in AnswerSchema.objects.all().iterator():
        lang = survey_language.get(schema.survey_id)
        if not lang:
            continue
        answer_schema_translations.append(
            AnswerSchemaTranslation(
                schema_id=schema.id,
                language=lang,
            )
        )
    if answer_schema_translations:
        AnswerSchemaTranslation.objects.bulk_create(
            answer_schema_translations,
            ignore_conflicts=True,
            batch_size=500,
        )

    option_translations = []
    for option in AnswerSchemaOption.objects.all().iterator():
        lang = survey_language.get(option.survey_id)
        if not lang:
            continue
        option_translations.append(
            AnswerSchemaOptionTranslation(
                option_id=option.id,
                language=lang,
                text=option.text,
            )
        )
    if option_translations:
        AnswerSchemaOptionTranslation.objects.bulk_create(
            option_translations,
            ignore_conflicts=True,
            batch_size=500,
        )

    action_translations = []
    for action in Action.objects.all().iterator():
        lang = survey_language.get(action.survey_id)
        if not lang:
            continue
        action_translations.append(
            ActionTranslation(
                action_id=action.id,
                language=lang,
                title=action.title,
                description=action.description,
            )
        )
    if action_translations:
        ActionTranslation.objects.bulk_create(action_translations, ignore_conflicts=True, batch_size=500)

    recommendation_translations = []
    for recommendation in Recommendation.objects.all().iterator():
        lang = survey_language.get(recommendation.survey_id)
        if not lang:
            continue
        recommendation_translations.append(
            RecommendationTranslation(
                recommendation_id=recommendation.id,
                language=lang,
                description=recommendation.description,
            )
        )
    if recommendation_translations:
        RecommendationTranslation.objects.bulk_create(
            recommendation_translations,
            ignore_conflicts=True,
            batch_size=500,
        )

    classification_translations = []
    for classification in Classification.objects.all().iterator():
        lang = survey_language.get(classification.survey_id)
        if not lang:
            continue
        classification_translations.append(
            ClassificationTranslation(
                classification_id=classification.id,
                language=lang,
                name=classification.name,
            )
        )
    if classification_translations:
        ClassificationTranslation.objects.bulk_create(
            classification_translations,
            ignore_conflicts=True,
            batch_size=500,
        )


def reverse_backfill(apps, schema_editor):
    for model_name in [
        "SectionTranslation",
        "QuestionTranslation",
        "AnswerSchemaTranslation",
        "AnswerSchemaOptionTranslation",
        "ActionTranslation",
        "RecommendationTranslation",
        "ClassificationTranslation",
    ]:
        apps.get_model("surveys", model_name).objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0016_translations"),
    ]

    operations = [
        migrations.RunPython(backfill_translations, reverse_backfill),
    ]
