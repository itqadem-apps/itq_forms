"""The report finds live recommendations with no text in any language and writes nothing (intake
report #133, story add-recommendation 2.1); story 2.2 deletes by the same rule."""

import importlib

import pytest
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings

from django.utils.timezone import now

from recommendations import empty_cleanup
from recommendations.models import Recommendation, RecommendationTranslation
from user_surveys.models import UserRecommendation, UserSurvey


def _rec(survey=None, option=None, texts=()):
    r = Recommendation.objects.create(survey=survey, option=option)
    for language, text in texts:
        RecommendationTranslation.objects.create(recommendation=r, language=language, description=text)
    return r


def _state():
    translations = RecommendationTranslation._base_manager.values_list("id", "recommendation_id", "language", "description")
    return (
        sorted(Recommendation._base_manager.values_list("id", "survey_id", "option_id", "deleted_at")),
        sorted((str(a), b, c, d) for a, b, c, d in translations),
        sorted(UserRecommendation._base_manager.values_list("id", "origin_id", "deleted_at")),
    )


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "  ",
        "<p></p>",
        "<p>&nbsp;</p>",
        "<p> <br/> &NBSP; </p>\n",
        "<p>&nbsp</p>",
        "<p>&ensp;&emsp;&thinsp;</p>",
        "<p>\u00a0</p>",
        "<p>\u200b\ufeff</p>",
        "<p>&#8203;&#x200B;</p>",
    ],
)
def test_is_blank(text):
    assert empty_cleanup.is_blank(text)


@pytest.mark.parametrize("text", ["x", "<p>Read more</p>", "&nbsp;a"])
def test_is_not_blank(text):
    assert not empty_cleanup.is_blank(text)


def test_no_translation_is_empty(survey):
    r = _rec(survey)

    found = empty_cleanup.find_empty()

    assert found.no_translation == [r.id]
    assert found.only_blank == []
    assert found.by_survey == {survey.id: [r.id]}


def test_only_blank_translations_are_empty(survey):
    r = _rec(survey, texts=[("en", None), ("ar", "  "), ("fr", "<p></p>"), ("default", "<p>&nbsp;</p>")])

    found = empty_cleanup.find_empty()

    assert found.only_blank == [r.id]
    assert found.no_translation == []


def test_text_in_any_language_is_not_empty(survey):
    _rec(survey, texts=[("en", "<p></p>"), ("default", "Practise daily")])

    assert empty_cleanup.find_empty().ids == []


def test_already_deleted_is_not_counted(survey):
    r = _rec(survey)
    Recommendation._base_manager.filter(pk=r.pk).update(deleted_at=now())

    assert empty_cleanup.find_empty().ids == []


def test_survey_via_option(survey, options):
    r = _rec(option=options[0])

    assert empty_cleanup.find_empty().by_survey == {survey.id: [r.id]}


def test_own_survey_wins_over_the_options(survey, options):
    from surveys.models import Survey

    other = Survey.objects.create(organization_id=survey.organization_id, primary_language="en")
    r = _rec(survey=other, option=options[0])

    assert empty_cleanup.find_empty().by_survey == {other.id: [r.id]}


def test_blank_with_media_is_empty_and_counted_apart(survey):
    r = _rec(survey, texts=[("en", '<p><img src="a.png"></p>')])
    _rec(survey, texts=[("en", "<p></p>")])

    found = empty_cleanup.find_empty()

    assert r.id in found.only_blank
    assert found.with_media == [r.id]
    assert "blank but holding an image, video or embed: 1" in empty_cleanup.summary(found)


def test_no_survey(db):
    r = _rec()

    found = empty_cleanup.find_empty()

    assert found.by_survey == {None: [r.id]}
    assert "no survey: 1" in empty_cleanup.summary(found)


def test_learner_copies_are_counted(survey):
    empty = _rec(survey)
    full = _rec(survey, texts=[("en", "text")])
    us = UserSurvey.objects.create(survey=survey)
    UserRecommendation.objects.create(user_survey=us, origin_id=empty.id)
    UserRecommendation.objects.create(user_survey=us, origin_id=empty.id)
    UserRecommendation.objects.create(user_survey=us, origin_id=full.id)
    gone = UserRecommendation.objects.create(user_survey=us, origin_id=empty.id)
    UserRecommendation._base_manager.filter(pk=gone.pk).update(deleted_at=now())

    assert empty_cleanup.find_empty().learner_copies == 2


def test_learner_copies_counted_past_one_chunk(db):
    Recommendation.objects.bulk_create([Recommendation() for _ in range(empty_cleanup.CHUNK + 1)])
    last = Recommendation._base_manager.order_by("-id").first()
    us = UserSurvey.objects.create()
    UserRecommendation.objects.create(user_survey=us, origin_id=last.id)

    assert empty_cleanup.find_empty().learner_copies == 1


def test_report_migration_writes_nothing(survey, options, capsys):
    a = _rec(survey)
    _rec(survey, texts=[("en", "<p></p>")])
    _rec(survey, texts=[("en", "text")])
    _rec()
    us = UserSurvey.objects.create(survey=survey)
    UserRecommendation.objects.create(user_survey=us, origin_id=a.id)
    before = _state()

    importlib.import_module("recommendations.migrations.0006_report_empty_recommendations").forwards(None, None)

    assert _state() == before
    out = capsys.readouterr().out
    assert "empty-recommendations: report (nothing written)" in out
    assert "empty-recommendations: total: 3 empty recommendation(s)" in out
    assert "empty-recommendations: no translation: 2" in out
    assert "empty-recommendations: only blank translations: 1" in out
    assert f"empty-recommendations: survey {survey.id}: 2" in out
    assert "empty-recommendations: no survey: 1" in out
    assert "empty-recommendations: learner copies pointing at an empty recommendation: 1" in out


def test_report_sits_on_the_current_leaves():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    migration = loader.get_migration("recommendations", "0006_report_empty_recommendations")

    assert ("recommendations", "0005_recommendable_replace_generic_fk") in migration.dependencies
    assert ("user_surveys", "0033_report_exam_regrade_again") in migration.dependencies
    assert loader.graph.leaf_nodes("recommendations") == [("recommendations", "0006_report_empty_recommendations")]
