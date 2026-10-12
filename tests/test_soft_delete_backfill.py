"""The R1 report finds the live children of already soft-deleted rows and writes nothing; the R2
apply stamps each with its parent's `deleted_at` (`forms:AD-21`, `forms:AD-14`)."""

import importlib
from datetime import datetime, timedelta, timezone

from surveys import soft_delete_backfill
from surveys.models import AnswerSchemaOption, Question, Section
from user_surveys.models import UserAnswerOption, UserQuestion
from user_surveys.services import enroll_user_in_assessment

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = T1 + timedelta(days=1)


def _all(model):
    return model._base_manager


def _state():
    return (
        sorted(_all(Section).values_list("id", "deleted_at")),
        sorted(_all(Question).values_list("id", "deleted_at")),
        sorted(_all(AnswerSchemaOption).values_list("id", "deleted_at")),
        sorted(UserQuestion.objects.values_list("id", "origin_id")),
        sorted(UserAnswerOption.objects.values_list("id", "origin_id")),
    )


def _layout(survey, enrol=None):
    """S1 (deleted at T1) holding Q1; S2 live holding Q2 (deleted at T2) and Q3 live. `enrol`, a
    user, takes a learner snapshot before the parents are stamped."""
    s1 = Section.objects.create(survey=survey, title="S1")
    s2 = Section.objects.create(survey=survey, title="S2")
    q1 = _all(Question).get(section=s1)
    q2 = _all(Question).get(section=s2)
    q3 = Question.objects.create(survey=survey, section=s2, title="Q3")
    if enrol is not None:
        enroll_user_in_assessment(enrol, survey.id)
    _all(Section).filter(pk=s1.pk).update(deleted_at=T1)
    _all(Question).filter(pk=q2.pk).update(deleted_at=T2)
    return s1, s2, q1, q2, q3


def _option_ids(question):
    return sorted(_all(AnswerSchemaOption).filter(question=question).values_list("id", flat=True))


def test_plan_finds_the_orphans(survey):
    s1, s2, q1, q2, q3 = _layout(survey)

    [p] = soft_delete_backfill.plan()

    assert p.survey_id == survey.id
    assert p.questions == [(q1.id, s1.id, T1)]
    assert sorted(o[0] for o in p.options) == _option_ids(q1) + _option_ids(q2)
    assert {o[0]: o[2] for o in p.options} == {
        **{pk: T1 for pk in _option_ids(q1)},
        **{pk: T2 for pk in _option_ids(q2)},
    }
    assert not any(o[1] == q3.id for o in p.options)


def test_report_migration_writes_nothing(survey, user, capsys):
    s1, *_ = _layout(survey, enrol=user)
    before = _state()

    importlib.import_module("surveys.migrations.0057_report_soft_delete_children").forwards(None, None)

    assert _state() == before
    out = capsys.readouterr().out
    assert f"soft-delete-children: survey {survey.id}: 1 question(s), 2 option(s) to stamp" in out
    assert f"deleted section {s1.id}: live question(s)" in out
    assert "soft-delete-children: summary: 1 surveys, 1 questions, 2 options to stamp" in out


def test_apply_stamps_with_the_parent_timestamp_and_is_repeatable(survey, user):
    s1, s2, q1, q2, q3 = _layout(survey, enrol=user)
    snapshots = (sorted(UserQuestion.objects.values_list("id", "origin_id")), sorted(UserAnswerOption.objects.values_list("id", "origin_id")))

    soft_delete_backfill.run(apply=True)

    assert _all(Question).get(pk=q1.pk).deleted_at == T1
    assert set(_all(AnswerSchemaOption).filter(question=q1).values_list("deleted_at", flat=True)) == {T1}
    assert set(_all(AnswerSchemaOption).filter(question=q2).values_list("deleted_at", flat=True)) == {T2}
    assert _all(Question).get(pk=q3.pk).deleted_at is None
    assert set(_all(AnswerSchemaOption).filter(question=q3).values_list("deleted_at", flat=True)) == {None}
    assert _all(Section).get(pk=s2.pk).deleted_at is None
    assert snapshots == (sorted(UserQuestion.objects.values_list("id", "origin_id")), sorted(UserAnswerOption.objects.values_list("id", "origin_id")))

    assert soft_delete_backfill.plan() == []
    assert soft_delete_backfill.run(apply=True)["surveys"] == 0


def test_stale_option_section_is_counted_not_stamped(survey):
    s1 = Section.objects.create(survey=survey, title="S1")
    q = Question.objects.create(survey=survey, title="sectionless")
    _all(AnswerSchemaOption).filter(question=q).update(section=s1)
    _all(Question).filter(section=s1).update(section=None)
    _all(Section).filter(pk=s1.pk).update(deleted_at=T1)

    [p] = soft_delete_backfill.plan()
    assert p.options == [] and p.questions == []
    assert p.stale_option_sections == _all(AnswerSchemaOption).filter(section=s1).count() >= 2

    soft_delete_backfill.run(apply=True)
    assert set(_all(AnswerSchemaOption).filter(section=s1).values_list("deleted_at", flat=True)) == {None}


def test_a_legacy_question_is_keyed_by_its_sections_survey_and_a_homeless_one_is_reported(survey):
    s1, s2, q1, q2, q3 = _layout(survey)
    _all(Question).filter(pk=q1.pk).update(survey=None)
    homeless = Question.objects.create(survey=survey, title="homeless")
    _all(Question).filter(pk=homeless.pk).update(survey=None, section=None)

    [p] = soft_delete_backfill.plan()
    assert p.survey_id == survey.id
    assert p.questions == [(q1.id, s1.id, T1)]
    assert soft_delete_backfill.run(apply=False)["unresolved_questions"] == [homeless.id]

    soft_delete_backfill.run(apply=True)
    assert _all(Question).get(pk=q1.pk).deleted_at == T1
    assert _all(Question).get(pk=homeless.pk).deleted_at is None


def test_a_live_go_to_into_a_deleted_question_is_reported_then_made_fall_through(survey, user, capsys):
    from surveys.models import FlowAction

    s1, s2, q1, q2, q3 = _layout(survey)
    into_deleted, into_orphan, into_live = (
        AnswerSchemaOption.objects.create(survey=survey, section=s2, question=q3, schema=q3.answer_schema, text=text).pk
        for text in ("to Q2", "to Q1", "to Q4")
    )
    q4 = Question.objects.create(survey=survey, section=s2, title="Q4")
    for option_id, target in ((into_deleted, q2), (into_orphan, q1), (into_live, q4)):
        _all(AnswerSchemaOption).filter(pk=option_id).update(flow_action=FlowAction.GO_TO, flow_target=target)

    [p] = soft_delete_backfill.plan()
    assert sorted(p.jumps) == sorted([(into_deleted, q3.id, q2.id), (into_orphan, q3.id, q1.id)])

    importlib.import_module("surveys.migrations.0057_report_soft_delete_children").forwards(None, None)
    out = capsys.readouterr().out
    assert f"option {into_deleted} of live question {q3.id}: go_to deleted question {q2.id} -> fall_through" in out
    assert f"option {into_orphan} of live question {q3.id}: go_to deleted question {q1.id} -> fall_through" in out
    assert "2 dangling go_to edges to make fall-through" in out
    assert _all(AnswerSchemaOption).get(pk=into_deleted).flow_action == FlowAction.GO_TO

    counts = soft_delete_backfill.run(apply=True)
    assert counts["jumps"] == 2
    assert "2 dangling go_to edges made fall-through" in soft_delete_backfill.summary(counts, applied=True)[0]
    assert set(_all(AnswerSchemaOption).filter(pk__in=[into_deleted, into_orphan]).values_list("flow_action", "flow_target_id")) == {
        (FlowAction.FALL_THROUGH, None)
    }
    assert _all(AnswerSchemaOption).values_list("flow_action", "flow_target_id").get(pk=into_live) == (FlowAction.GO_TO, q4.id)
    assert soft_delete_backfill.plan() == []

    # The survey enrols once the apply has run (R3 refuses a dangling target).
    enroll_user_in_assessment(user, survey.id)


def test_the_apply_migration_writes_and_logs_every_id(survey, capsys):
    """R2: 0058 is the apply, logging the ids it writes for the manual reversal."""
    s1, s2, q1, q2, q3 = _layout(survey)

    importlib.import_module("surveys.migrations.0058_apply_soft_delete_children").forwards(None, None)

    out = capsys.readouterr().out
    assert f"deleted section {s1.id}: live question(s) [{q1.id}]" in out
    assert "soft-delete-children: summary: 1 surveys, 1 questions, 2 options stamped" in out
    assert _all(Question).get(pk=q1.pk).deleted_at == T1
