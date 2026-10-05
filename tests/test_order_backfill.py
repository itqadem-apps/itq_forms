"""Story survey-flow 1.6 — the survey-wide order backfill (`forms:AD-4`, `forms:AD-14`).

Fixtures mimic the live data before the backfill: author questions numbered 1..k within each
section, a sectionless question (which the legacy key sorts last), an open snapshot copied from
that shape, an open shuffled snapshot whose orders interleave its sections, and a submitted
snapshot that must not be touched.
"""

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.timezone import now

from surveys import order_backfill
from surveys.models import Question, Section
from surveys.question_order import flat_question_ids
from user_surveys.models import UserQuestion, UserSurvey
from user_surveys.services import enroll_user_in_assessment


def _legacy_shape(survey):
    """Sections A, B, C; two questions in A and B, one in C; one sectionless question; orders
    section-scoped, the way every survey holds them before the backfill."""
    sections = [Section.objects.create(survey=survey, title=t) for t in "ABC"]
    for sec in sections[:2]:
        Question.objects.create(survey=survey, section=sec, title=f"{sec.title}2", type="text")
    loose = Question.objects.create(survey=survey, section=sections[0], title="loose", type="text")
    Question.objects.filter(pk=loose.pk).update(section=None)
    for rank, sec in enumerate(sections, start=1):
        Section.objects.filter(pk=sec.pk).update(order=rank)
        for i, pk in enumerate(sec.questions.order_by("id").values_list("id", flat=True), start=1):
            Question.objects.filter(pk=pk).update(order=i)
    Question.objects.filter(pk=loose.pk).update(order=1)
    return sections, loose


def _author_orders(survey):
    return dict(Question.objects.filter(survey=survey).values_list("id", "order"))


def _snapshot_orders(user_survey):
    return dict(UserQuestion.objects.filter(user_survey=user_survey).values_list("id", "order"))


def _rendered(qs):
    return flat_question_ids(qs)


def _by_order(qs):
    return list(qs.order_by("order", "id").values_list("id", flat=True))


@pytest.fixture
def legacy(user, user2, survey):
    sections, loose = _legacy_shape(survey)
    open_us, _ = enroll_user_in_assessment(user, survey.id)

    shuffled, _ = enroll_user_in_assessment(user2, survey.id)
    # A shuffled attempt: survey-wide 1..N in a random order that interleaves the sections.
    ids = list(UserQuestion.objects.filter(user_survey=shuffled).order_by("-id").values_list("id", flat=True))
    for i, pk in enumerate(ids, start=1):
        UserQuestion.objects.filter(pk=pk).update(order=i)

    third = get_user_model().objects.create(id="u3", username="u3", email="u3@x.test")
    submitted, _ = enroll_user_in_assessment(third, survey.id)
    UserSurvey.objects.filter(pk=submitted.pk).update(submitted_at=now())
    return {"sections": sections, "loose": loose, "open": open_us, "shuffled": shuffled, "submitted": submitted}


def _run(*args):
    out = StringIO()
    call_command("backfill_question_order", *args, stdout=out)
    return out.getvalue()


# ── Dry run ─────────────────────────────────────────────────────


def test_dry_run_reports_each_sequence_and_writes_nothing(survey, legacy):
    author = _author_orders(survey)
    snaps = {k: _snapshot_orders(legacy[k]) for k in ("open", "shuffled", "submitted")}
    section_orders = dict(Section.objects.filter(survey=survey).values_list("id", "order"))

    out = _run("--dry-run")

    assert _author_orders(survey) == author
    assert {k: _snapshot_orders(legacy[k]) for k in snaps} == snaps
    assert dict(Section.objects.filter(survey=survey).values_list("id", "order")) == section_orders
    assert f"survey {survey.id}: " in out
    assert f"open snapshot {legacy['open'].id}: " in out
    assert f"open snapshot {legacy['shuffled'].id}: " in out
    assert f"snapshot {legacy['submitted'].id}:" not in out
    # The full resulting sequence is listed, not only a count.
    for pk in _rendered(Question.objects.filter(survey=survey)):
        assert f"question {pk} " in out
    assert "Dry run — nothing written." in out
    assert "REFUSED" not in out


def test_dry_run_json_lists_the_sequence_in_rendered_order(survey, legacy):
    lines = [json.loads(line) for line in _run("--dry-run", "--json").splitlines()]
    plan = next(p for p in lines if p.get("kind") == "survey")
    assert [row["question"] for row in plan["sequence"]] == plan["rendered_before"]
    assert [row["position"] for row in plan["sequence"]] == list(range(1, len(plan["sequence"]) + 1))
    assert lines[-1]["summary"]["submitted_snapshots_untouched"] == 1


def test_a_mode_is_required():
    with pytest.raises(CommandError):
        _run()


# ── Apply: author side ──────────────────────────────────────────


def test_apply_numbers_every_survey_one_to_n_in_its_rendered_order(survey, legacy):
    questions = Question.objects.filter(survey=survey)
    before = _rendered(questions)
    assert before[-1] == legacy["loose"].id, "the legacy key sorts the sectionless question last"

    _run("--apply")

    assert _by_order(questions) == before
    assert _rendered(questions) == before
    assert sorted(_author_orders(survey).values()) == list(range(1, len(before) + 1))
    a, b, c = legacy["sections"]
    assert list(Section.objects.filter(survey=survey).order_by("order").values_list("id", flat=True)) == [a.id, b.id, c.id]


def test_apply_reaches_the_author_order_only_through_renumber_questions(survey, legacy, monkeypatch):
    calls, checks = [], []
    real_renumber, real_check = order_backfill.renumber_questions, order_backfill.assert_forward_only
    monkeypatch.setattr(order_backfill, "renumber_questions", lambda sid, sequence=None: calls.append((sid, sequence)) or real_renumber(sid, sequence=sequence))
    monkeypatch.setattr(order_backfill, "assert_forward_only", lambda owner, positions, field: checks.append((type(owner).__name__, field)) or real_check(owner, positions, field))
    legacy_sequence = _rendered(Question.objects.filter(survey=survey))

    _run("--apply")

    assert calls == [(survey.id, legacy_sequence)]
    assert ("Survey", "order") in checks
    assert ("UserSurvey", "order") in checks


def test_a_second_run_finds_nothing_to_do(survey, legacy):
    _run("--apply")
    out = _run("--dry-run")
    assert "surveys: 1 scanned, 0 renumbered, 0 refused" in out
    assert "open snapshots: 2 scanned, 0 renumbered, 0 refused" in out


def test_a_survey_already_survey_wide_keeps_a_sectionless_question_between_sections(survey):
    a = Section.objects.create(survey=survey, title="A")
    b = Section.objects.create(survey=survey, title="B")
    loose = Question.objects.create(survey=survey, section=a, title="loose", type="text")
    Question.objects.filter(pk=loose.pk).update(section=None)
    layout = [a.questions.get().id, loose.id, b.questions.get().id]
    for i, pk in enumerate(layout, start=1):
        Question.objects.filter(pk=pk).update(order=i)

    out = _run("--apply")

    assert _by_order(Question.objects.filter(survey=survey)) == layout
    assert "surveys: 1 scanned, 0 renumbered, 0 refused" in out


# ── Apply: learner snapshots ────────────────────────────────────


def test_open_snapshots_are_renumbered_and_keep_their_rendered_order(survey, legacy):
    for key in ("open", "shuffled"):
        qs = UserQuestion.objects.filter(user_survey=legacy[key])
        legacy[key]._before = _rendered(qs)

    _run("--apply")

    for key in ("open", "shuffled"):
        qs = UserQuestion.objects.filter(user_survey=legacy[key])
        assert _rendered(qs) == legacy[key]._before
        assert _by_order(qs) == legacy[key]._before
        assert sorted(_snapshot_orders(legacy[key]).values()) == list(range(1, qs.count() + 1))


def test_a_shuffled_snapshot_keeps_its_in_section_order_and_its_sections_become_contiguous(survey, legacy):
    qs = UserQuestion.objects.filter(user_survey=legacy["shuffled"])
    in_section = {
        sid: list(qs.filter(section_id=sid).order_by("order", "id").values_list("id", flat=True))
        for sid in set(qs.exclude(section=None).values_list("section_id", flat=True))
    }

    _run("--apply")

    sequence = _by_order(qs)
    section_of = dict(qs.values_list("id", "section_id"))
    for sid, ids in in_section.items():
        positions = [sequence.index(pk) for pk in ids]
        assert [sequence[p] for p in sorted(positions)] == ids
        assert positions == list(range(positions[0], positions[0] + len(ids))), "contiguous"
    assert all(section_of[pk] is not None for pk in sequence[:-1])


def test_submitted_snapshots_are_not_touched(survey, legacy):
    before = _snapshot_orders(legacy["submitted"])
    _run("--apply")
    assert _snapshot_orders(legacy["submitted"]) == before


def test_a_snapshot_submitted_after_listing_is_skipped(survey, legacy):
    UserSurvey.objects.filter(pk=legacy["open"].pk).update(submitted_at=now())
    before = _snapshot_orders(legacy["open"])
    assert order_backfill.apply_snapshot(legacy["open"].id) is None
    assert _snapshot_orders(legacy["open"]) == before


# ── Refusal ─────────────────────────────────────────────────────


@pytest.fixture
def tied(survey, legacy):
    """Two sections sharing one `order`: the legacy key interleaves them, so any renumber that
    makes sections contiguous changes what renders."""
    a, b, _ = legacy["sections"]
    Section.objects.filter(pk=b.pk).update(order=1)
    return survey


def test_a_survey_whose_rendered_order_would_change_is_refused_not_written(tied, legacy):
    author = _author_orders(tied)

    out = _run("--dry-run")
    assert f"REFUSED survey {tied.id}" in out

    with pytest.raises(CommandError, match="refused"):
        _run("--apply")
    assert _author_orders(tied) == author
    # The open snapshots were still written: they render the same.
    assert sorted(_snapshot_orders(legacy["open"]).values()) == list(range(1, len(author) + 1))


def test_allow_render_change_writes_a_named_refused_survey(tied, legacy):
    _run("--apply", "--survey", str(tied.id), "--allow-render-change")
    orders = sorted(_author_orders(tied).values())
    assert orders == list(range(1, len(orders) + 1))


def test_allow_render_change_needs_apply_and_a_survey(tied):
    with pytest.raises(CommandError):
        _run("--dry-run", "--allow-render-change")
    with pytest.raises(CommandError):
        _run("--apply", "--allow-render-change")

