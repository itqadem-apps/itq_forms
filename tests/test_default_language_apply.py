"""The apply relabels only the report's relabellable bucket to the survey's primary language, changing
the `language` column and nothing else (intake report #132, story default-language-translations
1.2)."""

import importlib

import pytest
from django.db import transaction
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings
from django.utils.timezone import now

from classifications.models import Classification, ClassificationTranslation
from recommendations.models import Action, ActionTranslation, RecommendationTranslation
from surveys import default_language as dl
from surveys.models import Survey
from tests.test_default_language_report import _classification, _recommendation, _state, _survey
from user_surveys.models import UserClassification, UserRecommendation, UserSurvey

APPLY = "surveys.migrations.0062_apply_default_language_relabel"


def _run(capsys):
    importlib.import_module(APPLY).forwards(None, None)
    return capsys.readouterr().out


def _row(model, row):
    return model._base_manager.values_list("language", *_texts(model)).get(pk=row.pk)


def _texts(model):
    return {
        ClassificationTranslation: ("name",),
        RecommendationTranslation: ("description",),
        ActionTranslation: ("title", "description"),
    }[model]


def test_relabellable(survey, capsys):
    s = _survey(survey.organization_id)
    _, (row,) = _classification(s, [("default", "Low")])

    _run(capsys)

    assert _row(ClassificationTranslation, row) == ("ar", "Low")


def test_recommendation_via_option(survey, options, capsys):
    Survey.objects.filter(pk=survey.pk).update(primary_language="ar")
    _, (row,) = _recommendation(option=options[0], texts=[("default", "<p>Practise</p>")])

    _run(capsys)

    assert _row(RecommendationTranslation, row) == ("ar", "<p>Practise</p>")


def test_action(survey, capsys):
    s = _survey(survey.organization_id, "en")
    row = ActionTranslation.objects.create(
        action=Action.objects.create(survey=s), language="default", title="Act", description="Now"
    )

    _run(capsys)

    assert _row(ActionTranslation, row) == ("en", "Act", "Now")


def test_clash_with_text_is_untouched(survey, capsys):
    s = _survey(survey.organization_id)
    _, (default, ar) = _recommendation(s, texts=[("default", "Practise"), ("ar", "تدرب")])

    _run(capsys)

    assert _row(RecommendationTranslation, default) == ("default", "Practise")
    assert _row(RecommendationTranslation, ar) == ("ar", "تدرب")


def test_clash_blank_is_untouched(survey, capsys):
    s = _survey(survey.organization_id)
    _, (default, ar) = _classification(s, [("default", "Low"), ("ar", "<p></p>")])

    _run(capsys)

    assert _row(ClassificationTranslation, default) == ("default", "Low")
    assert _row(ClassificationTranslation, ar) == ("ar", "<p></p>")


def test_skipped_buckets_stay_default(survey, capsys):
    gone, (deleted_row,) = _classification(survey, [("default", "Gone")])
    Classification._base_manager.filter(pk=gone.pk).update(deleted_at=now())
    _, (orphan,) = _recommendation(texts=[("default", "Orphan")])
    no_language = Survey.objects.create(organization_id=survey.organization_id, primary_language="")
    _, (unlabelled,) = _classification(no_language, [("default", "Low")])

    _run(capsys)

    assert _row(ClassificationTranslation, deleted_row) == ("default", "Gone")
    assert _row(RecommendationTranslation, orphan) == ("default", "Orphan")
    assert _row(ClassificationTranslation, unlabelled) == ("default", "Low")


def test_not_default_is_unchanged(survey, capsys):
    s = _survey(survey.organization_id)
    _classification(s, [("ar", "منخفض"), ("en", "Low")])
    _recommendation(s, texts=[("en", "x")])
    before = _state()

    out = _run(capsys)

    assert _state() == before
    assert "default-language: classification translations: left labelled \"default\": 0" in out


def test_snapshots_are_unchanged(survey, capsys):
    s = _survey(survey.organization_id)
    c, _ = _classification(s, [("default", "Low")])
    r, _ = _recommendation(s, texts=[("default", "x")])
    us = UserSurvey.objects.create(survey=s)
    UserClassification.objects.create(user_survey=us, origin_id=c.id, translations={"default": {"name": "Low"}})
    UserRecommendation.objects.create(user_survey=us, origin_id=r.id, translations={"default": {"description": "x"}})

    def snapshots():
        return (
            sorted(map(str, UserSurvey._base_manager.values_list("id", "survey_id"))),
            sorted(map(str, UserClassification._base_manager.values_list("id", "origin_id", "translations"))),
            sorted(map(str, UserRecommendation._base_manager.values_list("id", "origin_id", "translations"))),
        )

    before = snapshots()

    _run(capsys)

    assert snapshots() == before


def test_count_mismatch_raises_and_rolls_back(survey):
    s = _survey(survey.organization_id)
    _, (cls_row,) = _classification(s, [("default", "Low")])
    act = ActionTranslation.objects.create(action=Action.objects.create(survey=s), language="default", title="Act")
    found = dl.find_default_rows()
    ActionTranslation._base_manager.filter(pk=act.pk).update(language="en")

    with pytest.raises(RuntimeError, match="action translations: relabelled 0 to ar, expected 1"):
        with transaction.atomic():
            dl.apply(found)

    assert _row(ClassificationTranslation, cls_row) == ("default", "Low")


def test_rerun_relabels_nothing(survey, capsys):
    s = _survey(survey.organization_id)
    _classification(s, [("default", "Low")])

    _run(capsys)
    before = _state()
    out = _run(capsys)

    assert _state() == before
    assert "relabelled to" not in out
    assert 'default-language: classification translations: left labelled "default": 0' in out
    assert "default-language: after apply: classification translations: relabellable: 0" in out


def test_printed_counts(survey, options, capsys):
    Survey.objects.filter(pk=survey.pk).update(primary_language="en")
    s = _survey(survey.organization_id)
    _classification(s, [("default", "Low")])
    _classification(s, [("default", "High")])
    _classification(texts=[("default", "Orphan")])
    _recommendation(option=options[0], texts=[("default", "x")])
    _recommendation(s, texts=[("default", "y")])
    _recommendation(s, texts=[("default", "z"), ("ar", "ع")])
    ActionTranslation.objects.create(action=Action.objects.create(survey=s), language="default", title="Act")

    out = _run(capsys)

    lines = out.splitlines()
    assert lines[0] == "  default-language: apply (relabel to the survey's primary language)"
    assert all(line.startswith("  default-language: ") for line in lines)
    assert "default-language: classification translations: relabelled to ar: 2" in out
    assert 'default-language: classification translations: left labelled "default": 1' in out
    assert "default-language: recommendation translations: relabelled to ar: 1" in out
    assert "default-language: recommendation translations: relabelled to en: 1" in out
    assert 'default-language: recommendation translations: left labelled "default": 1' in out
    assert "default-language: action translations: relabelled to ar: 1" in out
    assert 'default-language: action translations: left labelled "default": 0' in out
    assert "default-language: after apply: recommendation translations: clash, primary row has text: 1" in out
    assert "default-language: after apply: recommendation translations: relabellable: 0" in out
    assert "default-language: after apply: classification translations: no survey: 1" in out


def test_apply_depends_on_the_report_and_is_atomic():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    migration = loader.get_migration("surveys", "0062_apply_default_language_relabel")

    assert migration.dependencies == [("surveys", "0061_report_default_language_rows")]
    assert migration.atomic is True
