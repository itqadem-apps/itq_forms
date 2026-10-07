"""The report release lists routing options left on questions that cannot route and writes nothing
(`forms:AD-3`, `forms:AD-11`, `estate:AD-20`)."""

import importlib
from datetime import datetime, timezone

from surveys.models import AnswerSchema, AnswerSchemaOption, FlowAction, Question, Survey
from surveys.question_order import renumber_questions
from user_surveys.models import UserAnswer, UserAnswerOption, UserAnswerSchema, UserQuestion, UserSurvey
from user_surveys.services import enroll_user_in_assessment


def _questions(survey, *types):
    qs = [Question.objects.create(survey=survey, title=t, type=t) for t in types]
    renumber_questions(survey.id, [q.id for q in qs])
    return qs


def _route(question, action, target=None):
    option = question.answer_schema.options.first()
    AnswerSchemaOption.objects.filter(pk=option.pk).update(flow_action=action, flow_target=target)
    return option


def _snapshot():
    return (
        sorted(Survey.objects.values_list("id", "deleted_at")),
        sorted(Question.objects.values_list("id", "type", "deleted_at")),
        sorted(AnswerSchema.objects.values_list("id", "type")),
        sorted(AnswerSchemaOption.objects.values_list("id", "flow_action", "flow_target_id")),
        sorted(UserSurvey.objects.values_list("id", "submitted_at")),
        sorted(UserQuestion.objects.values_list("id", "type")),
        sorted(UserAnswerSchema.objects.values_list("id", "type")),
        sorted(UserAnswerOption.objects.values_list("id", "question_id", "flow_action", "flow_target_id")),
        sorted(UserAnswer.selected_options.through.objects.values_list("useranswer_id", "useransweroption_id")),
    )


def _run(capsys):
    before = _snapshot()
    importlib.import_module("surveys.migrations.0055_report_routing_on_multi_select").forwards(None, None)
    assert _snapshot() == before
    return capsys.readouterr().out


def _line(survey, question, option, qtype, stype, action, target, deleted=False, survey_deleted=False):
    return (
        f"routing-repair: survey={survey.id}{' (survey deleted)' if survey_deleted else ''} question={question.id}{' (deleted)' if deleted else ''}"
        f" option={option.id} question_type={qtype} schema_type={stype}"
        f" flow_action={action} flow_target={target}"
    )


def test_clean_db_reports_zero(survey, capsys):
    out = _run(capsys)

    assert "routing-repair: author: 0 surveys, 0 questions, 0 options" in out
    assert "routing-repair: snapshots: open 0 options / 0 attempts, submitted 0 options / 0 attempts" in out
    assert "routing-repair: snapshots: open attempts with an answer selecting one: 0" in out


def test_a_checkbox_go_to_is_listed_with_both_types_and_its_target(survey, capsys):
    q1, q5 = _questions(survey, "checkbox", "radio")
    option = _route(q1, FlowAction.GO_TO, q5)

    out = _run(capsys)

    assert _line(survey, q1, option, "checkbox", "checkbox", "go_to", q5.id) in out
    assert "author: 1 surveys, 1 questions, 1 options" in out


def test_a_grid_terminate_is_listed(survey, capsys):
    (q,) = _questions(survey, "radio_grid")
    option = _route(q, FlowAction.TERMINATE)

    out = _run(capsys)

    assert _line(survey, q, option, "radio_grid", "radio_grid", "terminate", None) in out


def test_a_question_schema_drift_is_listed_with_both_types(survey, capsys):
    q1, q2 = _questions(survey, "radio", "radio")
    option = _route(q1, FlowAction.GO_TO, q2)
    AnswerSchema.objects.filter(question=q1).update(type="checkbox")

    out = _run(capsys)

    assert _line(survey, q1, option, "radio", "checkbox", "go_to", q2.id) in out


def test_a_radio_edge_is_not_listed(survey, user, capsys):
    q1, q2 = _questions(survey, "radio", "dropdown")
    _route(q1, FlowAction.GO_TO, q2)
    _route(q2, FlowAction.TERMINATE)
    enroll_user_in_assessment(user, survey.id)

    out = _run(capsys)

    assert "author: 0 surveys, 0 questions, 0 options" in out
    assert "snapshots: open 0 options / 0 attempts, submitted 0 options / 0 attempts" in out
    assert "snapshots: open attempts with an answer selecting one: 0" in out


def test_a_reverse_drift_is_listed_with_both_types(survey, capsys):
    q1, q2 = _questions(survey, "checkbox", "radio")
    option = _route(q1, FlowAction.GO_TO, q2)
    AnswerSchema.objects.filter(question=q1).update(type="radio")

    out = _run(capsys)

    assert _line(survey, q1, option, "checkbox", "radio", "go_to", q2.id) in out


def test_a_snapshot_drift_is_counted_either_way(survey, user, capsys):
    q1, q2, q3 = _questions(survey, "radio", "radio", "radio")
    a = _route(q1, FlowAction.GO_TO, q3)
    b = _route(q2, FlowAction.TERMINATE)
    us, _ = enroll_user_in_assessment(user, survey.id)
    copy_a = UserAnswerOption.objects.get(user_survey=us, origin_id=a.id)
    copy_b = UserAnswerOption.objects.get(user_survey=us, origin_id=b.id)
    # a: question checkbox, schema radio. b: no question, schema checkbox.
    UserQuestion.objects.filter(pk=copy_a.question_id).update(type="checkbox")
    UserAnswerSchema.objects.filter(pk=copy_b.schema_id).update(type="checkbox")
    UserAnswerOption.objects.filter(pk=copy_b.pk).update(question=None)

    out = _run(capsys)

    assert "snapshots: open 2 options / 1 attempts, submitted 0 options / 0 attempts" in out


def test_a_soft_deleted_survey_is_marked(survey, capsys):
    (q,) = _questions(survey, "checkbox")
    option = _route(q, FlowAction.TERMINATE)
    Survey.objects.filter(pk=survey.pk).update(deleted_at=datetime.now(timezone.utc))

    out = _run(capsys)

    assert _line(survey, q, option, "checkbox", "checkbox", "terminate", None, survey_deleted=True) in out


def test_a_soft_deleted_question_is_listed_and_marked(survey, capsys):
    (q,) = _questions(survey, "checkbox")
    option = _route(q, FlowAction.TERMINATE)
    Question.objects.filter(pk=q.pk).update(deleted_at=datetime.now(timezone.utc))

    out = _run(capsys)

    assert _line(survey, q, option, "checkbox", "checkbox", "terminate", None, deleted=True) in out


def test_a_full_form_survey_is_dormant_not_offending(survey, user, capsys):
    q1, q2 = _questions(survey, "checkbox", "radio")
    _route(q1, FlowAction.GO_TO, q2)
    enroll_user_in_assessment(user, survey.id)
    Survey.objects.filter(pk=survey.pk).update(display_option=Survey.DISPLAY_OPTION_FULL_FORM)
    UserSurvey.objects.update(display_option=Survey.DISPLAY_OPTION_FULL_FORM)

    out = _run(capsys)

    assert "author: 0 surveys, 0 questions, 0 options" in out
    assert "snapshots: open 0 options / 0 attempts, submitted 0 options / 0 attempts" in out


def test_snapshots_are_counted_by_attempt_state_and_no_ids_are_printed(survey, user, user2, capsys):
    q1, q2 = _questions(survey, "checkbox", "radio")
    option = _route(q1, FlowAction.GO_TO, q2)
    open_us, _ = enroll_user_in_assessment(user, survey.id)
    done_us, _ = enroll_user_in_assessment(user2, survey.id)
    UserSurvey.objects.filter(pk=done_us.pk).update(submitted_at=datetime.now(timezone.utc))
    copy = UserAnswerOption.objects.get(user_survey=open_us, origin_id=option.id)
    answer = UserAnswer.objects.create(user=user, user_survey=open_us, question=copy.question)
    answer.selected_options.add(copy)

    out = _run(capsys)

    assert "routing-repair: snapshots: open 1 options / 1 attempts, submitted 1 options / 1 attempts" in out
    assert "routing-repair: snapshots: open attempts with an answer selecting one: 1" in out
    # Only the one author option is listed by id; snapshot rows appear as counts and nothing else.
    lines = [line for line in out.splitlines() if "routing-repair:" in line]
    assert len(lines) == 4
    assert _line(survey, q1, option, "checkbox", "checkbox", "go_to", q2.id) in lines[0]
    assert user.id not in out and user2.id not in out
