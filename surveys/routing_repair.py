"""Routing options left on questions that cannot route (`forms:AD-3`).

Report half of `estate:AD-20` / `forms:AD-14`. Under `forms:AD-3` only a single-select schema may
carry a `go_to` or `terminate` edge, but before v0.0.100 a question could change type while its
options kept their edges, so a checkbox or grid question (and the learner snapshots copied from it)
may still route, and the walk then follows whichever selected option it reads last.

`plan()` only reads; `describe()` renders it as deploy-log lines. Author options are listed by id;
snapshot options are counted only, never listed, so no learner, user or attempt id reaches the log.
A `full_form` survey's edges are dormant, not ambiguous (`forms:AD-11`), so they are left out. The
apply that clears these edges to `fall_through` ships in its own release, built from these ids.
"""

from django.db.models import Q

from surveys.flow import SINGLE_SELECT_TYPES
from surveys.models import AnswerSchemaOption, FlowAction, Survey

ROUTING_ACTIONS = (FlowAction.GO_TO, FlowAction.TERMINATE)


def _author_options():
    multi = AnswerSchemaOption.objects.filter(flow_action__in=ROUTING_ACTIONS).exclude(
        survey__display_option=Survey.DISPLAY_OPTION_FULL_FORM
    )
    # Either type outside single-select counts, so a question/schema drift is caught both ways.
    offending = multi.exclude(Q(question__type__in=SINGLE_SELECT_TYPES) & Q(schema__type__in=SINGLE_SELECT_TYPES))
    return [
        {
            "survey_id": row[0],
            "survey_deleted": row[1] is not None,
            "question_id": row[2],
            "question_deleted": row[3] is not None,
            "option_id": row[4],
            "question_type": row[5],
            "schema_type": row[6],
            "flow_action": row[7],
            "flow_target_id": row[8],
        }
        for row in offending.order_by("survey_id", "question_id", "id").values_list(
            "survey_id",
            "survey__deleted_at",
            "question_id",
            "question__deleted_at",
            "id",
            "question__type",
            "schema__type",
            "flow_action",
            "flow_target_id",
        )
    ]


def _snapshot_counts():
    from user_surveys.models import UserAnswer, UserAnswerOption

    offending = (
        UserAnswerOption.objects.filter(flow_action__in=ROUTING_ACTIONS)
        # Same two-way rule as the author side; a null question cannot vouch for a multi schema.
        .exclude(Q(question__type__in=SINGLE_SELECT_TYPES) & Q(schema__type__in=SINGLE_SELECT_TYPES))
        .exclude(user_survey__display_option=Survey.DISPLAY_OPTION_FULL_FORM)
    )
    open_ = offending.filter(user_survey__submitted_at__isnull=True)
    submitted = offending.filter(user_survey__submitted_at__isnull=False)
    return {
        "open_options": open_.count(),
        "open_attempts": open_.values("user_survey_id").distinct().count(),
        "submitted_options": submitted.count(),
        "submitted_attempts": submitted.values("user_survey_id").distinct().count(),
        "open_attempts_with_answer": UserAnswer.objects.filter(selected_options__in=open_.values("id"))
        .filter(user_survey__isnull=False, user_survey__submitted_at__isnull=True)
        .values("user_survey_id")
        .distinct()
        .count(),
    }


def plan():
    """Every offending author option and the snapshot counts, read and never written."""
    return {"options": _author_options(), "snapshots": _snapshot_counts()}


def describe(p):
    lines = []
    for o in p["options"]:
        lines.append(
            f"survey={o['survey_id']}{' (survey deleted)' if o['survey_deleted'] else ''}"
            f" question={o['question_id']}"
            f"{' (deleted)' if o['question_deleted'] else ''} option={o['option_id']}"
            f" question_type={o['question_type']} schema_type={o['schema_type']}"
            f" flow_action={o['flow_action']} flow_target={o['flow_target_id']}"
        )
    surveys = {o["survey_id"] for o in p["options"]}
    questions = {o["question_id"] for o in p["options"]}
    lines.append(
        f"author: {len(surveys)} surveys, {len(questions)} questions, {len(p['options'])} options route "
        "on a question that cannot route"
    )
    s = p["snapshots"]
    lines.append(
        f"snapshots: open {s['open_options']} options / {s['open_attempts']} attempts, "
        f"submitted {s['submitted_options']} options / {s['submitted_attempts']} attempts"
    )
    lines.append(f"snapshots: open attempts with an answer selecting one: {s['open_attempts_with_answer']}")
    return lines
