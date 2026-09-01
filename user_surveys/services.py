import logging
import random
from collections import Counter
from uuid import uuid4

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.timezone import now

logger = logging.getLogger(__name__)

from .models import (
    UserAction,
    UserAnswer,
    UserAnswerOption,
    UserAnswerSchema,
    UserClassification,
    UserQuestion,
    UserRecommendation,
    UserSection,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)
from surveys.models import Survey
from survey_collections.models import SurveyCollection


def _build_translations(qs, fields, source=None, primary_lang=None):
    """Build a {lang: {field: value}} dict from a translations queryset.

    If *source* and *primary_lang* are given the primary-language values
    are merged from the source model instance.
    """
    result = {}
    for t in qs:
        entry = {}
        for f in fields:
            entry[f] = getattr(t, f, None)
        result[t.language] = entry
    if source and primary_lang:
        result.setdefault(primary_lang, {})
        for f in fields:
            result[primary_lang].setdefault(f, getattr(source, f, None))
    return result


def check_time_expired(user_survey: UserSurvey) -> bool:
    """Return True if the timed assessment has exceeded its time limit."""
    if (
        user_survey.is_timed
        and user_survey.time_limit
        and user_survey.started_at
    ):
        return now() - user_survey.started_at >= user_survey.time_limit
    return False


def create_survey_snapshot(survey: Survey, user_survey: UserSurvey) -> None:
    """Deep-copy the full survey tree into user_surveys models."""
    first_translation = survey.translations.first()
    primary_lang = first_translation.language if first_translation else "default"

    # ── 1. Classifications ───────────────────────────────────────────
    classification_map = {}  # original_id -> UserClassification
    for c in survey.classifications.all():
        uc = UserClassification.objects.create(
            origin_id=c.id,
            user_survey=user_survey,
            score=c.score,
            deleted_at=c.deleted_at,
            created_at=c.created_at,
            updated_at=c.updated_at,
            translations=_build_translations(c.translations.all(), ["name"], source=c, primary_lang=primary_lang),
        )
        classification_map[c.id] = uc

    # ── 2. Sections ──────────────────────────────────────────────────
    section_map = {}  # original_id -> UserSection

    def snapshot_section(s):
        us = UserSection.objects.create(
            origin_id=s.id,
            user_survey=user_survey,
            order=s.order,
            is_hidden=s.is_hidden,
            cover_asset_id=s.cover_asset_id,
            submit_action=s.submit_action,
            submit_action_target=None,  # resolved below
            created_at=s.created_at,
            updated_at=s.updated_at,
            translations=_build_translations(s.translations.all(), ["title", "description"], source=s, primary_lang=primary_lang),
        )
        section_map[s.id] = us
        return us

    def section_for(source, kind):
        """Resolve a child row's section, snapshotting one the survey's own
        section list did not cover rather than dropping the link.

        ``section_map.get(...)`` used to swallow that case, and a snapshot
        question left with ``section = NULL`` disappears from
        ``userSurvey.sections[].questions`` for good — the results screen then
        renders a section with no questions. A row whose source section is
        genuinely NULL has nothing to link and stays unsectioned.
        """
        section_id = source.section_id
        if section_id is None:
            return None
        if section_id in section_map:
            return section_map[section_id]
        logger.warning(
            "%s %s on survey %s references section %s, which is not in that "
            "survey's own section list; snapshotting it so the link survives",
            kind, source.id, survey.id, section_id,
        )
        return snapshot_section(source.section)

    sections = list(survey.sections.order_by("order"))
    for s in sections:
        snapshot_section(s)

    # resolve self-FK submit_action_target
    for s in sections:
        if s.submit_action_target_id and s.submit_action_target_id in section_map:
            us = section_map[s.id]
            us.submit_action_target = section_map[s.submit_action_target_id]
            us.save(update_fields=["submit_action_target"])

    # ── 3. Questions ─────────────────────────────────────────────────
    question_map = {}  # original_id -> UserQuestion
    questions = list(
        survey.questions.select_related("section")
        .prefetch_related("translations")
        .order_by("section__order", "order")
    )
    for q in questions:
        uq = UserQuestion.objects.create(
            origin_id=q.id,
            user_survey=user_survey,
            section=section_for(q, "question"),
            answer_time=q.answer_time,
            order=q.order,
            is_required=q.is_required,
            type=q.type,
            cover_asset_id=q.cover_asset_id,
            created_at=q.created_at,
            updated_at=q.updated_at,
            translations=_build_translations(q.translations.all(), ["title", "description"], source=q, primary_lang=primary_lang),
        )
        question_map[q.id] = uq

    # ── 4. Answer Schemas ────────────────────────────────────────────
    schema_map = {}  # original_id -> UserAnswerSchema
    from surveys.models import AnswerSchema

    schemas = list(AnswerSchema.objects.filter(survey=survey))
    for schema in schemas:
        uas = UserAnswerSchema.objects.create(
            origin_id=schema.id,
            user_survey=user_survey,
            section=section_for(schema, "answer schema"),
            question=question_map[schema.question_id],
            type=schema.type,
            with_file=schema.with_file,
            is_mcq=schema.is_mcq,
            is_grid=schema.is_grid,
        )
        schema_map[schema.id] = uas

    # ── 5. Answer Options ────────────────────────────────────────────
    option_map = {}  # original_id -> UserAnswerOption
    from surveys.models import AnswerSchemaOption

    options = list(
        AnswerSchemaOption.objects.filter(survey=survey)
        .prefetch_related("translations")
        .order_by("order")
    )
    for opt in options:
        uao = UserAnswerOption.objects.create(
            origin_id=opt.id,
            user_survey=user_survey,
            section=section_for(opt, "answer option"),
            question=question_map.get(opt.question_id),
            schema=schema_map[opt.schema_id],
            classification=classification_map.get(opt.classification_id),
            score=opt.score,
            image_asset_id=opt.image_asset_id,
            is_row=opt.is_row,
            is_column=opt.is_column,
            ending_option=opt.ending_option,
            order=opt.order,
            translations=_build_translations(opt.translations.all(), ["text"], source=opt, primary_lang=primary_lang),
        )
        option_map[opt.id] = uao

    # ── 6. Recommendations ───────────────────────────────────────────
    for r in survey.recommendations.prefetch_related("translations").all():
        UserRecommendation.objects.create(
            origin_id=r.id,
            user_survey=user_survey,
            option=option_map.get(r.option_id),
            deleted_at=r.deleted_at,
            created_at=r.created_at,
            updated_at=r.updated_at,
            translations=_build_translations(r.translations.all(), ["description"], source=r, primary_lang=primary_lang),
        )

    # ── 7. Actions ───────────────────────────────────────────────────
    for a in survey.actions.prefetch_related("translations").all():
        UserAction.objects.create(
            origin_id=a.id,
            user_survey=user_survey,
            upper_limit=a.upper_limit,
            lower_limit=a.lower_limit,
            translations=_build_translations(a.translations.all(), ["title", "description"], source=a, primary_lang=primary_lang),
        )

    # ── 8. Randomization ─────────────────────────────────────────────
    if user_survey.randomize_questions:
        uqs = list(UserQuestion.objects.filter(user_survey=user_survey, section__isnull=False))
        random.shuffle(uqs)
        for i, uq in enumerate(uqs, start=1):
            uq.order = i
        UserQuestion.objects.bulk_update(uqs, ["order"])

    if user_survey.randomize_options:
        # randomize within each answer schema
        for schema in UserAnswerSchema.objects.filter(user_survey=user_survey):
            opts = list(schema.options.all())
            random.shuffle(opts)
            for i, opt in enumerate(opts, start=1):
                opt.order = i
            UserAnswerOption.objects.bulk_update(opts, ["order"])


def enroll_user_in_assessment(request_user, survey_id, child=None, collection_id=None):
    """
    Enroll the given user into a survey (assessment).
    Creates a full snapshot of the survey tree.
    Returns (user_survey, created) where created is False if an open enrollment already exists.
    """
    survey = get_object_or_404(Survey, id=survey_id)

    if getattr(survey, "is_for_child", False):
        if not child:
            raise ValueError("child is required for this survey.")
    else:
        child = None

    existing = UserSurvey.objects.filter(
        user=request_user,
        survey=survey,
        child=child,
        submitted_at__isnull=True,
    ).first()
    if existing:
        return existing, False

    collection = None
    if collection_id:
        collection = SurveyCollection.objects.filter(id=collection_id).first()

    with transaction.atomic():
        survey_translations = _build_translations(
            survey.translations.all(),
            ["title", "description", "short_description", "slug"],
        )

        user_survey = UserSurvey.objects.create(
            # source reference
            survey=survey,
            # enrollment
            user=request_user,
            child=child,
            collection=collection,
            # snapshot fields
            status=survey.status,
            survey_type=survey.survey_type,
            display_option=survey.display_option,
            is_timed=survey.is_timed,
            time_limit=survey.time_limit,
            is_for_child=survey.is_for_child,
            is_evaluable=survey.is_evaluable,
            evaluation_type=survey.evaluation_type,
            use_score=survey.use_score,
            use_classifications=survey.use_classifications,
            use_recommendations=survey.use_recommendations,
            use_actions=survey.use_actions,
            allow_end_based_on_answer_repeat=survey.allow_end_based_on_answer_repeat,
            answers_count_to_end=survey.answers_count_to_end,
            end_based_on_answer_repeat_in_row=survey.end_based_on_answer_repeat_in_row,
            enable_anti_cheat=survey.enable_anti_cheat,
            lock_answers=survey.lock_answers,
            randomize_questions=survey.randomize_questions,
            randomize_options=survey.randomize_options,
            session_token=uuid4() if survey.enable_anti_cheat else None,
            cover_id=survey.cover_id,
            thumb_id=survey.thumb_id,
            category_id_snapshot=survey.category_id,
            sponsor=survey.sponsor,
            survey_created_at=survey.created_at,
            survey_updated_at=survey.updated_at,
            translations=survey_translations,
        )

        create_survey_snapshot(survey, user_survey)

    return user_survey, True


def _evaluate_answer(user_survey: UserSurvey, answer: UserAnswer) -> tuple[int, list, list]:
    """Evaluate a single answer. Returns (score, classifications, recommendations)."""
    selected = list(answer.selected_options.all())
    if not selected:
        return 0, [], []

    Q = UserQuestion  # type constants

    score = 0
    if user_survey.use_score:
        if answer.type in Q.SINGLE_SELECT_TYPES:
            score = selected[0].score or 0
        elif answer.type in Q.MULTI_SELECT_TYPES + Q.GRID_TYPES:
            score = sum(opt.score or 0 for opt in selected)

    classifications = []
    if user_survey.use_classifications:
        classifications = [opt.classification for opt in selected if opt.classification]

    recommendations = []
    if user_survey.use_recommendations:
        for opt in selected:
            recommendations.extend(list(opt.option_recommendations.all()))

    return score, classifications, recommendations


def evaluate_assessment(user_survey: UserSurvey) -> None:
    """Score, classify, recommend, and match actions for a submitted assessment."""
    total_score = 0
    all_classifications = []
    all_recommendations = []

    answers = list(user_survey.useranswer_set.exclude(question__section__isnull=True))
    for answer in answers:
        score, classifications, recommendations = _evaluate_answer(user_survey, answer)

        # Save per-answer score
        if user_survey.use_score:
            answer.score = score
            answer.save(update_fields=["score"])

        total_score += score
        all_classifications.extend(classifications)
        all_recommendations.extend(recommendations)

    # ── Score ──
    update_fields = ["evaluated_at"]
    if user_survey.use_score:
        user_survey.score = total_score
        update_fields.append("score")

    user_survey.evaluated_at = now()

    # ── Actions (score-range matching) ──
    if user_survey.use_actions and user_survey.use_score:
        matched_action = (
            UserAction.objects.filter(
                user_survey=user_survey,
                lower_limit__lte=total_score,
                upper_limit__gte=total_score,
            )
            .first()
        )
        if matched_action:
            user_survey.action = matched_action
            update_fields.append("action")

    user_survey.save(update_fields=update_fields)

    # ── Classifications (sorted by count, descending) ──
    if user_survey.use_classifications:
        filtered = [c for c in all_classifications if c is not None]
        user_survey.usersurveyclassification_set.all().delete()
        if filtered:
            counts = Counter(c.id for c in filtered)
            unique = {c.id: c for c in filtered}.values()
            for classification in sorted(unique, key=lambda c: counts[c.id], reverse=True):
                UserSurveyClassification.objects.create(
                    user_survey=user_survey,
                    classification=classification,
                    count=counts[classification.id],
                )

    # ── Recommendations (sorted by count, descending) ──
    if user_survey.use_recommendations:
        filtered = [r for r in all_recommendations if r is not None]
        user_survey.usersurveyrecommendation_set.all().delete()
        if filtered:
            counts = Counter(r.id for r in filtered)
            unique = {r.id: r for r in filtered}.values()
            for recommendation in sorted(unique, key=lambda r: counts[r.id], reverse=True):
                UserSurveyRecommendation.objects.create(
                    user_survey=user_survey,
                    recommendation=recommendation,
                    count=counts[recommendation.id],
                )


def finish_assessment(
    user_survey: UserSurvey,
    reason: str = UserSurvey.TERMINATION_COMPLETED,
) -> None:
    # Skip required-question validation for forced terminations
    if reason == UserSurvey.TERMINATION_COMPLETED:
        required_questions = user_survey.questions.filter(is_required=True, section__isnull=False)
        if required_questions.exists():
            required_ids = set(required_questions.values_list("id", flat=True))
            answered_ids = set(
                user_survey.useranswer_set.filter(question_id__in=required_ids)
                .exclude(answer__isnull=True, selected_options__isnull=True)
                .values_list("question_id", flat=True)
            )
            missing = required_ids - answered_ids
            if missing:
                raise ValueError("You must answer all required questions before finishing the assessment.")

    user_survey.last_question = None
    user_survey.submitted_at = now()
    user_survey.termination_reason = reason
    user_survey.save(update_fields=["last_question", "submitted_at", "termination_reason"])

    # The snapshot is the record of what this user was asked, and results and
    # review render from it. A question the user skipped still belongs on the
    # review screen, shown as unanswered — deleting it here was unrecoverable
    # and left every fully-skipped section with `questions: []`, which the
    # clients read as a zero denominator. If a surface ever wants only the
    # answered questions, that is a filter at query time, not a write here.

    if user_survey.evaluation_type == UserSurvey.EVALUATION_TYPE_AUTOMATIC:
        evaluate_assessment(user_survey)

    # Notify downstream consumers (e.g. itq_courses, for quiz-lesson progress)
    # that the user finished this survey. Published AFTER any automatic
    # evaluation so the event payload carries the final score when scoring
    # is in scope. Outbox-backed: same DB transaction as the save above.
    from app.messaging.publisher import publish
    from user_surveys.events import SurveyResponseSubmitted

    publish(SurveyResponseSubmitted(
        aggregate_id=user_survey.id,
        survey_id=user_survey.survey_id,
        user_survey_id=user_survey.id,
        respondent_user_id=user_survey.user_id,
        score=user_survey.score,
        submitted_at=user_survey.submitted_at,
    ))
