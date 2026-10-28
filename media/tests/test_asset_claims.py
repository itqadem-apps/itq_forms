"""Asset claims (`media.asset_claims`): what forms tells media its records use,
after commit, and the one-off backfill."""
from __future__ import annotations

import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from pkg_media.models import ClaimItem, ClaimStatus

from media import asset_claims
from surveys.models import AnswerSchemaOption, Question, Section, Survey
from surveys.soft_delete import soft_delete
from user_surveys.models import UserAnswer, UserSurvey

ORG = "11111111-1111-1111-1111-111111111111"


def _id() -> str:
    return str(uuid.uuid4())


class FakeAssets:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple] = []
        self.fail = fail

    def claim(self, ids, *, ref, org=None, user=None, collection=None):
        if self.fail:
            raise RuntimeError("media down")
        ids = [str(i) for i in ids]
        self.calls.append(("claim", ref, tuple(sorted(ids)), org, user, collection))
        return [ClaimItem(asset_id=i, status=ClaimStatus.CLAIMED) for i in ids]

    def release(self, ids, *, ref):
        if self.fail:
            raise RuntimeError("media down")
        self.calls.append(("release", ref, tuple(sorted(str(i) for i in ids))))
        return []


class FakeClient:
    def __init__(self, fail: bool = False):
        self.assets = FakeAssets(fail)


@pytest.fixture
def media(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(asset_claims, "build_client", lambda: client)
    return client.assets


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    """Run what was queued for after commit, as a committed request would."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


# ── Live path ───────────────────────────────────────────────────────────


def test_a_survey_claims_its_artwork_after_commit_and_releases_the_old(survey, media, commit):
    thumb, cover, new_thumb = _id(), _id(), _id()
    with commit():
        survey.thumb_id, survey.cover_id = thumb, cover
        survey.save()
        assert media.calls == []  # nothing before commit
    ref = f"forms:survey/{survey.pk}"
    assert sorted(media.calls) == sorted([
        ("claim", ref, (cover,), ORG, None, "survey-cover"),
        ("claim", ref, (thumb,), ORG, None, "survey-thumb"),
    ])

    media.calls.clear()
    with commit():
        survey.thumb_id = new_thumb
        survey.save()
    assert media.calls == [
        ("claim", ref, (new_thumb,), ORG, None, "survey-thumb"),
        ("release", ref, (thumb,)),
    ]


def test_a_save_that_does_not_change_an_id_calls_nothing(survey, media, commit):
    survey.cover_id = _id()
    survey.save()
    with commit():
        survey.save()
        survey.save(update_fields=["status"])
    assert media.calls == []


def test_a_blank_or_malformed_id_is_ignored(survey, media, commit):
    with commit():
        survey.thumb_id, survey.cover_id = "", "not-a-uuid"
        survey.save()
    assert media.calls == []


def test_a_collection_soft_delete_releases_its_artwork(collection, media, commit):
    cover = _id()
    collection.cover_id = cover
    collection.save()
    from django.utils.timezone import now

    with commit():
        collection.deleted_at = now()
        collection.save()
    assert media.calls == [("release", f"forms:collection/{collection.pk}", (cover,))]


def test_section_question_and_option_images_carry_the_survey_org(survey, section, question, options, media, commit):
    sc, qc, oi = _id(), _id(), _id()
    with commit():
        section.cover_asset_id = sc
        section.save()
        question.cover_asset_id = qc
        question.save()
        options[0].image_asset_id = oi
        options[0].save()
    assert sorted(media.calls) == sorted([
        ("claim", f"forms:section/{section.pk}", (sc,), ORG, None, "section-cover"),
        ("claim", f"forms:question/{question.pk}", (qc,), ORG, None, "question-cover"),
        ("claim", f"forms:option/{options[0].pk}", (oi,), ORG, None, "option-image"),
    ])


def test_soft_deleting_a_section_releases_its_group(survey, section, question, options, media, commit):
    sc, qc, oi = _id(), _id(), _id()
    Section.objects.filter(pk=section.pk).update(cover_asset_id=sc)
    Question.objects.filter(pk=question.pk).update(cover_asset_id=qc)
    AnswerSchemaOption.objects.filter(pk=options[1].pk).update(image_asset_id=oi)
    with commit():
        soft_delete("section", Section.objects.get(pk=section.pk), survey.pk)
    assert sorted(media.calls) == sorted([
        ("release", f"forms:section/{section.pk}", (sc,)),
        ("release", f"forms:question/{question.pk}", (qc,)),
        ("release", f"forms:option/{options[1].pk}", (oi,)),
    ])


def test_soft_deleting_an_option_releases_it(survey, options, media, commit):
    oi = _id()
    AnswerSchemaOption.objects.filter(pk=options[0].pk).update(image_asset_id=oi)
    with commit():
        soft_delete("option", AnswerSchemaOption.objects.get(pk=options[0].pk), survey.pk)
    assert media.calls == [("release", f"forms:option/{options[0].pk}", (oi,))]


def test_a_hard_delete_releases_every_id(survey, media, commit):
    thumb = _id()
    survey.thumb_id = thumb
    survey.save()
    pk = survey.pk
    with commit():
        Survey.objects.get(pk=pk).delete()
    assert ("release", f"forms:survey/{pk}", (thumb,)) in media.calls


def test_enrolment_claims_the_snapshot_under_the_attempt(user, survey, section, question, options, media, commit):
    thumb, sc, oi = _id(), _id(), _id()
    Survey.objects.filter(pk=survey.pk).update(thumb_id=thumb)
    Section.objects.filter(pk=section.pk).update(cover_asset_id=sc)
    AnswerSchemaOption.objects.filter(pk=options[2].pk).update(image_asset_id=oi)
    from user_surveys.services import enroll_user_in_assessment

    with commit():
        attempt, _ = enroll_user_in_assessment(user, survey.id)
    ref = f"forms:attempt/{attempt.pk}"
    assert sorted(c for c in media.calls if c[1] == ref) == sorted([
        ("claim", ref, (oi,), ORG, None, "option-image"),
        ("claim", ref, (sc,), ORG, None, "section-cover"),
        ("claim", ref, (thumb,), ORG, None, "survey-thumb"),
    ])

    media.calls.clear()
    with commit():
        UserSurvey.objects.get(pk=attempt.pk).delete()
    assert media.calls == [("release", ref, tuple(sorted((thumb, sc, oi))))]


def test_an_answer_file_carries_the_respondent(enrolled_survey, user, media, commit):
    f1, f2 = _id(), _id()
    with commit():
        answer = UserAnswer.objects.create(user_survey=enrolled_survey, user=user, file_asset_id=f1)
    ref = f"forms:answer/{answer.pk}"
    assert media.calls == [("claim", ref, (f1,), ORG, user.pk, "answer-file")]

    media.calls.clear()
    with commit():
        answer.file_asset_id = f2
        answer.save()
    assert media.calls == [("claim", ref, (f2,), ORG, user.pk, "answer-file"), ("release", ref, (f1,))]

    media.calls.clear()
    with commit():
        answer.delete()
    assert media.calls == [("release", ref, (f2,))]


def test_a_media_failure_never_fails_the_write(survey, monkeypatch, commit, caplog):
    monkeypatch.setattr(asset_claims, "build_client", lambda: FakeClient(fail=True))
    with commit():
        survey.cover_id = _id()
        survey.save()
    assert Survey.objects.get(pk=survey.pk).cover_id == survey.cover_id
    assert "backfill repairs it" in caplog.text


def test_without_media_nothing_is_sent(survey, monkeypatch, commit):
    monkeypatch.setattr(asset_claims, "build_client", lambda: None)
    with commit():
        survey.cover_id = _id()
        survey.save()  # no error


# ── Backfill ────────────────────────────────────────────────────────────


@pytest.fixture
def tree(user, survey, section, question, options, collection):
    ids = {k: _id() for k in ("thumb", "cover", "section", "question", "option", "ccover", "file", "dead")}
    Survey.objects.filter(pk=survey.pk).update(thumb_id=ids["thumb"], cover_id=ids["cover"])
    Section.objects.filter(pk=section.pk).update(cover_asset_id=ids["section"])
    Question.objects.filter(pk=question.pk).update(cover_asset_id=ids["question"])
    AnswerSchemaOption.objects.filter(pk=options[0].pk).update(image_asset_id=ids["option"])
    # A soft-deleted option is not a live record.
    from django.utils.timezone import now

    AnswerSchemaOption.objects.filter(pk=options[1].pk).update(image_asset_id=ids["dead"], deleted_at=now())
    type(collection).objects.filter(pk=collection.pk).update(cover_id=ids["ccover"])
    from user_surveys.services import enroll_user_in_assessment

    attempt, _ = enroll_user_in_assessment(user, survey.id)
    answer = UserAnswer.objects.create(user_survey=attempt, user=user, file_asset_id=ids["file"])
    return ids, attempt, answer


def test_backfill_rows_cover_every_live_reference(tree, survey, section, question, options, collection, user):
    ids, attempt, answer = tree
    rows = set(asset_claims.backfill_rows())
    a = f"forms:attempt/{attempt.pk}"
    assert rows == {
        (ids["thumb"], f"forms:survey/{survey.pk}", ORG, None, "survey-thumb"),
        (ids["cover"], f"forms:survey/{survey.pk}", ORG, None, "survey-cover"),
        (ids["ccover"], f"forms:collection/{collection.pk}", ORG, None, "collection-cover"),
        (ids["section"], f"forms:section/{section.pk}", ORG, None, "section-cover"),
        (ids["question"], f"forms:question/{question.pk}", ORG, None, "question-cover"),
        (ids["option"], f"forms:option/{options[0].pk}", ORG, None, "option-image"),
        (ids["thumb"], a, ORG, None, "survey-thumb"),
        (ids["cover"], a, ORG, None, "survey-cover"),
        (ids["section"], a, ORG, None, "section-cover"),
        (ids["question"], a, ORG, None, "question-cover"),
        (ids["option"], a, ORG, None, "option-image"),
        (ids["file"], f"forms:answer/{answer.pk}", ORG, user.pk, "answer-file"),
    }


def test_backfill_is_a_dry_run_by_default(tree, media):
    out = StringIO()
    call_command("backfill_media_claims", stdout=out)
    text = out.getvalue()
    assert "rows: 12" in text
    assert "distinct asset ids: 7" in text
    assert "dry run: nothing claimed" in text
    assert media.calls == []


def test_backfill_apply_claims_and_reports(tree, media):
    out = StringIO()
    call_command("backfill_media_claims", "--apply", stdout=out)
    assert "claimed: 12, already_claimed: 0, not_found: 0" in out.getvalue()
    assert {c[0] for c in media.calls} == {"claim"}
    assert sum(len(c[2]) for c in media.calls) == 12
