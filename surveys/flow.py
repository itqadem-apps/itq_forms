"""An answer option's edge: where answering it sends the learner (`forms:AD-3`, `forms:AD-5`).

`validate_edge` checks one option's two columns before it is stored; `assert_survey_forward`
then runs the one forward-only predicate over every edge of the survey, the edge just written
included, against the survey's current order.
"""

from django.core.exceptions import ValidationError

from surveys.models import AnswerSchemaOption, FlowAction, Question
from surveys.question_order import assert_forward_only, flat_question_ids

# A learner picks exactly one option on these, so one answer yields one edge. Every other type
# that carries options (checkbox, and both grids, which take one answer per row) admits several.
SINGLE_SELECT_TYPES = (Question.QUESTION_TYPE_RADIO_MCQ, Question.QUESTION_TYPE_DROPDOWN_MCQ)


def validate_edge(option: AnswerSchemaOption) -> None:
    errors: dict[str, list[str]] = {}
    action = option.flow_action
    if action not in FlowAction.values:
        errors["flow_action"] = [f"\"{action}\" is not a flow action; use one of {', '.join(FlowAction.values)}."]
    elif action == FlowAction.GO_TO:
        if option.flow_target_id is None:
            errors["flow_target_id"] = ["A go_to edge must name the question it goes to."]
        elif not Question.objects.filter(
            pk=option.flow_target_id, survey_id=option.survey_id, deleted_at__isnull=True
        ).exists():
            errors["flow_target_id"] = [f"Question {option.flow_target_id} is not a question of this survey."]
    elif option.flow_target_id is not None:
        errors["flow_target_id"] = [f"Only a go_to edge names a target question; this option's action is {action}."]

    if action in (FlowAction.GO_TO, FlowAction.TERMINATE) and option.schema.type not in SINGLE_SELECT_TYPES:
        errors.setdefault("flow_action", []).append(
            "Only a single-choice question (radio or dropdown) can route: this one admits more than one "
            "selected option, so one answer would not yield one edge."
        )
    if errors:
        raise ValidationError(errors)


def assert_survey_forward(survey, field: str = "flow_target_id") -> None:
    positions = {pk: i for i, pk in enumerate(flat_question_ids(Question.objects.filter(survey_id=survey.pk)), start=1)}
    assert_forward_only(survey, positions, field=field)


def clear_edges_into(question_ids) -> None:
    """Edges that would lose their target fall through instead, so `flow_target` is still set if
    and only if `flow_action` is go_to."""
    AnswerSchemaOption.objects.filter(flow_target_id__in=question_ids).update(
        flow_action=FlowAction.FALL_THROUGH, flow_target=None
    )
