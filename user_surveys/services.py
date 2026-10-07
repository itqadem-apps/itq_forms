import logging
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
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
    UserMaterial,
    UserQuestion,
    UserRecommendation,
    UserSection,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)
from surveys.models import FlowAction, ScoreBasis, Survey
from surveys.question_order import assert_forward_only, flat_order, flat_question_ids
from survey_collections.models import SurveyCollection
from user_surveys.flow import prune_off_path, recalculate_on_path


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
        entry = result.setdefault(primary_lang, {})
        for f in fields:
            # `setdefault` was wrong here: a primary-language translation row
            # that exists but carries a null title puts the key in the dict
            # with a `None` value, so the fallback never fired and the question
            # snapshotted with no text at all — blank on the runner and on the
            # review screen, while every question lacking the row entirely
            # rendered fine. An empty translation means "not translated", not
            # "intentionally empty", so the model's own value wins.
            if entry.get(f) in (None, ""):
                entry[f] = getattr(source, f, None)
    return result


def _snapshot_materials(action, user_action, user_survey) -> None:
    """Freeze which catalog entries an action recommends, at enrolment time.

    The set is frozen; the payload is not. See ``UserMaterial`` for the full
    ruling — the FK is what keeps a retitled course rendering correctly, and
    the copied columns are what keeps the card standing once the catalog row
    is deleted.
    """
    rows = []
    for material in action.materials.all():
        recommendable = material.recommendable
        rows.append(
            UserMaterial(
                origin_id=material.id,
                user_survey=user_survey,
                user_action=user_action,
                recommendable=recommendable,
                source_service=recommendable.source_service,
                source_model=recommendable.source_model,
                source_id=recommendable.source_id,
                data=recommendable.data or {},
            )
        )
    # One INSERT per band rather than one per material: a band's material
    # count is admin-controlled and unbounded, and the reads are already
    # prefetched at the `actions` level.
    UserMaterial.objects.bulk_create(rows)


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
    """Deep-copy the full survey tree into user_surveys models.

    Everything written here is frozen at enrolment: an admin editing the survey
    afterwards does not reach a learner already in progress. Translations are
    flattened into a ``JSONField`` on each row rather than left as live rows,
    for the same reason.

    Materials (step 7) are the one documented split. The *set* of materials a
    band recommends is frozen like everything else, but each row keeps a FK to
    the ``Recommendable`` it came from and renders that row's live ``data``.
    The catalog is maintained by the event consumer, not by an admin, so a
    course retitled or moved upstream would otherwise leave the learner holding
    a wrong title and a dead link with no one able to correct it. Deleting the
    catalog row nulls the FK and the frozen copy takes over, so the card
    survives. ``UserMaterial`` carries the full ruling.

    Step 7 is the one conditional step: a survey with ``use_actions`` off
    snapshots no score bands and no materials, because evaluation can never
    match one. The reasoning, including what it changes for a client, is at
    that step.
    """
    # `forms:AD-1`: one definition of the primary locale, stored on the survey
    # and read by the admin builder over GraphQL. It decides which language key
    # the source models' legacy columns fall back into on every row below, so
    # deriving it a second way here would file one language's text under
    # another language's key — silently, and differently per survey. That this
    # is a stored value and not a derived one is what makes it safe to freeze:
    # everything written below is frozen, so a primary that moved after
    # enrolment would leave the learner holding a permanent mislabel.
    # `Survey.primary_locale` also supplies the "default" this used to spell
    # out inline.
    primary_lang = survey.primary_locale

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
        # `forms:AD-3`: the edge lands on this learner's own question. The copy is whole-tree, so a
        # target outside it can only be corrupt data, refused rather than stored dangling.
        if opt.flow_target_id is not None and opt.flow_target_id not in question_map:
            raise ValueError(
                f"Option {opt.id} on survey {survey.id} routes to question {opt.flow_target_id}, "
                "which is not in the survey's own question list."
            )
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
            flow_action=opt.flow_action,
            flow_target=question_map.get(opt.flow_target_id),
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
    # Gated on the flag evaluation reads. `evaluate_assessment` matches a band
    # only `if user_survey.use_actions and user_survey.use_score` (below, and
    # the same pair gates `pdf_service.py:121`), so with actions switched off
    # nothing this step writes is ever reachable — a row per band, and since
    # the materials work landed, a `UserMaterial` per entry pinned behind each
    # of them.
    #
    # The gate covers `UserAction` as well as `UserMaterial`, deliberately.
    # Skipping the materials alone would be invisible — they render only
    # through `UserActionType.materials`, which returns rows for the matched
    # band, and there is no matched band — but it would leave a band row
    # carrying nothing, which reads exactly like a band an admin pinned nothing
    # to. Skipping both is the state that reads truthfully: the survey does not
    # use bands, so it snapshots none.
    #
    # That is an API change for such a survey: `userSurvey.actions` returns an
    # empty list where it used to return every band. No client renders
    # differently, because each already gates on the flag before reading the
    # list — `app/composables/solve/useResultsData.ts:54` and
    # `server/utils/survey-report/build-html.ts:328` in `lyr-surveys`, and the
    # server-side PDF at `pdf_service.py:121`. "Every band is returned so a
    # client can show the scale" (`user_surveys/types/user_survey.py:265`)
    # is about a survey that HAS a scale; one with `use_actions` off has none.
    #
    # `user_survey.use_actions`, not `survey.use_actions`: the frozen copy is
    # what evaluation will consult, so reading it here is what keeps the write
    # side and the read side from ever disagreeing. The one caller copies it
    # off the survey moments earlier, so today the two are the same value.
    #
    # Not narrowed to `use_actions and use_score`, evaluation's full condition.
    # Bands on a survey that acts but does not score are equally unmatchable,
    # but there the client is at least configured for bands and could mean to
    # show them; that narrowing is a separate ruling this story did not make.
    if user_survey.use_actions:
        for a in survey.actions.prefetch_related("translations", "materials__recommendable").all():
            ua = UserAction.objects.create(
                origin_id=a.id,
                user_survey=user_survey,
                upper_limit=a.upper_limit,
                lower_limit=a.lower_limit,
                translations=_build_translations(a.translations.all(), ["title", "description"], source=a, primary_lang=primary_lang),
            )
            _snapshot_materials(a, ua, user_survey)

    # ── 8. Randomization ─────────────────────────────────────────────
    if user_survey.randomize_questions:
        _shuffle_questions(user_survey)

    if user_survey.randomize_options:
        # randomize within each answer schema
        for schema in UserAnswerSchema.objects.filter(user_survey=user_survey):
            opts = list(schema.options.all())
            random.shuffle(opts)
            for i, opt in enumerate(opts, start=1):
                opt.order = i
            UserAnswerOption.objects.bulk_update(opts, ["order"])

    # `forms:AD-5`'s enrolment caller: the snapshot's edges run forward in the order this learner
    # will walk, shuffle included. A violation raises, so the enrolment rolls back whole.
    snapshot = UserQuestion.objects.filter(user_survey=user_survey)
    positions = {pk: i for i, pk in enumerate(flat_question_ids(snapshot), start=1)}
    assert_forward_only(user_survey, positions, field="flow_target")


def _shuffle_questions(user_survey: UserSurvey) -> None:
    """`forms:AD-12`: anchors — a question an edge starts from (go_to or terminate) or lands on —
    keep their place. Every other question moves only among the slots its own section holds (no
    section is one group) within its gap between adjacent anchors, so what each edge skips is the
    same for every learner and sections stay contiguous. Run once, at enrolment."""
    rows = list(
        UserQuestion.objects.filter(user_survey=user_survey).order_by().values_list("id", "section_id", "section__order", "order")
    )
    sequence = flat_order(rows)
    section_of = {r[0]: r[1] for r in rows}
    anchors: set[int] = set()
    for source, target in (
        UserAnswerOption.objects.filter(user_survey=user_survey, question__isnull=False)
        .exclude(flow_action=FlowAction.FALL_THROUGH)
        .values_list("question_id", "flow_target_id")
    ):
        anchors.add(source)
        if target is not None:
            anchors.add(target)

    shuffled = list(sequence)

    def settle(gap: list[int]) -> None:
        groups: dict = {}
        for i in gap:
            groups.setdefault(section_of[sequence[i]], []).append(i)
        for slots in groups.values():
            ids = [sequence[i] for i in slots]
            random.shuffle(ids)
            for i, pk in zip(slots, ids):
                shuffled[i] = pk

    gap: list[int] = []
    for i, pk in enumerate(sequence):
        if pk in anchors:
            settle(gap)
            gap = []
        else:
            gap.append(i)
    settle(gap)

    UserQuestion.objects.bulk_update([UserQuestion(pk=pk, order=i) for i, pk in enumerate(shuffled, start=1)], ["order"])


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
            shuffle_scope=survey.shuffle_scope,
            score_basis=survey.score_basis,
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


def option_scores_by_question(user_survey: UserSurvey) -> dict[int, list[int]]:
    """Every snapshot option score of the attempt, keyed by question, in one query."""
    scores = defaultdict(list)
    for question_id, score in UserAnswerOption.objects.filter(user_survey=user_survey).values_list(
        "schema__question_id", "score"
    ):
        scores[question_id].append(score or 0)
    return dict(scores)


def question_max_score(question: UserQuestion, scores: list[int] | None = None) -> int:
    """The most one question can score: the highest option of a single-select, the positive
    options summed for a multi-select or grid. Pass `scores` from `option_scores_by_question` to
    avoid a query per question."""
    if scores is None:
        scores = [s or 0 for s in UserAnswerOption.objects.filter(schema__question=question).values_list("score", flat=True)]
    if question.type in UserQuestion.SINGLE_SELECT_TYPES:
        return max(scores, default=0)
    if question.type in UserQuestion.MULTI_SELECT_TYPES + UserQuestion.GRID_TYPES:
        return sum(max(0, s) for s in scores)
    return 0


def max_score(user_survey: UserSurvey, scores: dict[int, list[int]] | None = None) -> int:
    """The attempt's denominator under its declared basis (`forms:AD-10`); see `max_scores`."""
    return max_scores([user_survey], {user_survey.id: scores} if scores is not None else None)[user_survey.id]


def max_scores(
    user_surveys: Iterable[UserSurvey], scores: dict[int, dict[int, list[int]]] | None = None
) -> dict[int, int]:
    """Each attempt's denominator under its own declared basis (`forms:AD-10`), read from the
    stored `on_path` flags, never a replay (`forms:AD-17`). At most three queries however many
    attempts: option scores (skipped when `scores`, keyed by attempt then question, is passed),
    questions, and answered question ids (only when an attempt counts `answered`)."""
    by_id = {us.id: us for us in user_surveys}
    if not by_id:
        return {}

    if scores is None:
        scores = defaultdict(lambda: defaultdict(list))
        for us_id, question_id, score in UserAnswerOption.objects.filter(user_survey_id__in=by_id).values_list(
            "user_survey_id", "schema__question_id", "score"
        ):
            scores[us_id][question_id].append(score or 0)

    answering = [us_id for us_id, us in by_id.items() if us.score_basis == ScoreBasis.ANSWERED]
    answered = set()
    if answering:
        answered = set(
            UserAnswer.objects.filter(user_survey_id__in=answering, selected_options__isnull=False).values_list(
                "user_survey_id", "question_id"
            )
        )

    totals = dict.fromkeys(by_id, 0)
    for question in UserQuestion.objects.filter(user_survey_id__in=by_id).only("id", "type", "on_path", "user_survey_id"):
        us_id = question.user_survey_id
        basis = by_id[us_id].score_basis
        if basis != ScoreBasis.ALL and not question.on_path:
            continue
        if basis == ScoreBasis.ANSWERED and (us_id, question.id) not in answered:
            continue
        totals[us_id] += question_max_score(question, scores.get(us_id, {}).get(question.id, []))
    return totals


def evaluate_assessment(user_survey: UserSurvey) -> None:
    """Score, classify, recommend, and match actions for a submitted assessment."""
    total_score = 0
    all_classifications = []
    all_recommendations = []

    # Scoped to the question, never to section membership (`forms:AD-13`). An answer the path no
    # longer reaches never scores, under every basis (`forms:AD-10`); one whose question link is
    # null still does, as before.
    answers = list(user_survey.useranswer_set.exclude(question__on_path=False))
    if user_survey.use_score:
        # A score left from an earlier evaluation would still render beside an answer that no
        # longer counts.
        user_survey.useranswer_set.filter(question__on_path=False).exclude(score=None).update(score=None)
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
    # One transaction under a row lock, which `answer_question` also takes: no answer write can move
    # the path between the walk and the prune. Callers in autocommit (should_terminate,
    # auto_submit_expired) get their own transaction here; a refused submit simply rolls back.
    with transaction.atomic():
        locked = UserSurvey.objects.select_for_update().get(pk=user_survey.pk)
        _finish_locked(locked, reason)
        user_survey.refresh_from_db()


def _finish_locked(user_survey: UserSurvey, reason: str) -> None:
    recalculate_on_path(user_survey)
    # Skip required-question validation for forced terminations; a required question the path
    # skipped is not missing (`forms:AD-19`).
    if reason == UserSurvey.TERMINATION_COMPLETED:
        required_questions = user_survey.questions.filter(is_required=True, on_path=True)
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

    # The walk was just refreshed, so a forced end prunes against the current path (`forms:AD-19`).
    prune_off_path(user_survey)

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
        # The denominator under the attempt's basis (`forms:AD-10`), so a consumer grades
        # score / max_score; null when unscored or awaiting manual evaluation.
        max_score=max_score(user_survey) if user_survey.use_score and user_survey.score is not None else None,
        submitted_at=user_survey.submitted_at,
    ))
