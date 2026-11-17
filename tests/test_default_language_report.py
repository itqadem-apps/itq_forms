"""The report sorts every translation labelled "default" into one bucket and writes nothing (intake
report #132, story default-language-translations 1.1); story 1.2 relabels by the same rule."""

import importlib

import pytest
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings
from django.utils.timezone import now

from classifications.models import Classification, ClassificationTranslation
from recommendations.models import Action, ActionTranslation, Recommendation, RecommendationTranslation
from surveys import default_language as dl
from surveys.models import Survey

CLASS, REC, ACTION = 0, 1, 2


def _survey(organization_id, language="ar"):
    return Survey.objects.create(organization_id=organization_id, primary_language=language)


def _classification(survey=None, texts=()):
    c = Classification.objects.create(survey=survey)
    rows = [ClassificationTranslation.objects.create(classification=c, language=lang, name=t) for lang, t in texts]
    return c, rows


def _recommendation(survey=None, option=None, texts=()):
    r = Recommendation.objects.create(survey=survey, option=option)
    rows = [RecommendationTranslation.objects.create(recommendation=r, language=lang, description=t) for lang, t in texts]
    return r, rows


def _bucket_of(found, table, row):
    hits = [b for b, ids in found[table].buckets.items() if row.id in ids]
    assert len(hits) == 1, hits
    return hits[0]


def _state():
    def rows(model, *fields):
        return sorted(tuple(str(v) for v in r) for r in model._base_manager.values_list(*fields))

    return (
        rows(ClassificationTranslation, "id", "classification_id", "language", "name"),
        rows(RecommendationTranslation, "id", "recommendation_id", "language", "description"),
        rows(ActionTranslation, "id", "action_id", "language", "title", "description"),
        rows(Classification, "id", "survey_id", "deleted_at"),
        rows(Recommendation, "id", "survey_id", "option_id", "deleted_at"),
        rows(Survey, "id", "primary_language"),
    )


def test_relabellable(survey):
    s = _survey(survey.organization_id)
    _, (row,) = _classification(s, [("default", "Low")])

    found = dl.find_default_rows()

    assert _bucket_of(found, CLASS, row) == dl.RELABELLABLE
    assert found[CLASS].relabellable_by_language == {"ar": [row.id]}


def test_clash_primary_row_has_text(survey):
    s = _survey(survey.organization_id)
    _, (row, _) = _classification(s, [("default", "Low"), ("ar", "منخفض")])

    assert _bucket_of(dl.find_default_rows(), CLASS, row) == dl.CLASH_WITH_TEXT


def test_clash_primary_row_blank(survey):
    s = _survey(survey.organization_id)
    _, (row, _) = _recommendation(s, texts=[("default", "Practise"), ("ar", "<p></p>")])

    found = dl.find_default_rows()

    assert _bucket_of(found, REC, row) == dl.CLASH_BLANK
    assert found[REC].relabellable_by_language == {}


def test_other_language_only_is_relabellable(survey):
    s = _survey(survey.organization_id)
    _, (row, _) = _classification(s, [("default", "Low"), ("en", "Low")])

    assert _bucket_of(dl.find_default_rows(), CLASS, row) == dl.RELABELLABLE


@pytest.mark.parametrize("make", [_classification, _recommendation])
def test_no_survey(db, make):
    _, (row,) = make(texts=[("default", "x")])

    found = dl.find_default_rows()

    table = CLASS if make is _classification else REC
    assert _bucket_of(found, table, row) == dl.NO_SURVEY


def test_survey_via_option(survey, options):
    Survey.objects.filter(pk=survey.pk).update(primary_language="ar")
    _, (row,) = _recommendation(option=options[0], texts=[("default", "Practise")])

    found = dl.find_default_rows()

    assert _bucket_of(found, REC, row) == dl.RELABELLABLE
    assert found[REC].relabellable_by_language == {"ar": [row.id]}


@pytest.mark.parametrize("language", [None, "", "   ", "default", " Default "])
def test_no_primary_language(survey, language):
    Survey.objects.filter(pk=survey.pk).update(primary_language=language)
    _, (row,) = _classification(survey, [("default", "Low")])

    assert _bucket_of(dl.find_default_rows(), CLASS, row) == dl.NO_PRIMARY_LANGUAGE


def test_parent_deleted(survey):
    c, (row,) = _classification(survey, [("default", "Low")])
    Classification._base_manager.filter(pk=c.pk).update(deleted_at=now())
    r, (rec_row,) = _recommendation(survey, texts=[("default", "x")])
    Recommendation._base_manager.filter(pk=r.pk).update(deleted_at=now())

    found = dl.find_default_rows()

    assert _bucket_of(found, CLASS, row) == dl.PARENT_DELETED
    assert _bucket_of(found, REC, rec_row) == dl.PARENT_DELETED


def test_action(survey):
    survey = _survey(survey.organization_id, "en")
    action = Action.objects.create(survey=survey)
    row = ActionTranslation.objects.create(action=action, language="default", title="Act", description="Now")
    blank = Action.objects.create(survey=survey)
    clash = ActionTranslation.objects.create(action=blank, language="default", title="Act")
    ActionTranslation.objects.create(action=blank, language="en", title=" ", description="<p>&nbsp;</p>")

    found = dl.find_default_rows()

    assert _bucket_of(found, ACTION, row) == dl.RELABELLABLE
    assert found[ACTION].relabellable_by_language == {"en": [row.id]}
    assert _bucket_of(found, ACTION, clash) == dl.CLASH_BLANK


def test_not_default_is_not_counted(survey):
    _classification(survey, [("ar", "Low"), ("en", "Low")])
    _recommendation(survey, texts=[("en", "x")])

    found = dl.find_default_rows()

    assert [t.total for t in found] == [0, 0, 0]


def test_report_migration_writes_nothing(survey, options, capsys):
    Survey.objects.filter(pk=survey.pk).update(primary_language="en")
    s = _survey(survey.organization_id)
    _classification(s, [("default", "Low")])
    _classification(s, [("default", "High"), ("ar", "عالي")])
    _classification(texts=[("default", "Orphan")])
    _recommendation(option=options[0], texts=[("default", "x")])
    _recommendation(s, texts=[("default", "y"), ("ar", "<p></p>")])
    ActionTranslation.objects.create(action=Action.objects.create(survey=survey), language="default", title="Act")
    before = _state()

    importlib.import_module("surveys.migrations.0061_report_default_language_rows").forwards(None, None)

    assert _state() == before
    out = capsys.readouterr().out
    assert "default-language: report (nothing written)" in out
    assert 'default-language: classification translations: 3 labelled "default"' in out
    assert "default-language: classification translations: relabellable: 1" in out
    assert "default-language: classification translations: clash, primary row has text: 1" in out
    assert "default-language: classification translations: no survey: 1" in out
    assert "default-language: classification translations: relabellable to ar: 1" in out
    assert "default-language: recommendation translations: clash, primary row blank: 1" in out
    assert "default-language: recommendation translations: relabellable to en: 1" in out
    assert "default-language: action translations: relabellable to en: 1" in out
    assert 'default-language: recommendation translations: 2 labelled "default"' in out
    assert 'default-language: action translations: 1 labelled "default"' in out
    assert all(line.startswith("  default-language: ") for line in out.splitlines())


@pytest.mark.parametrize("title, description", [("", "Now"), ("Act", "<p></p>")])
def test_action_primary_row_with_text_in_one_field_clashes(survey, title, description):
    s = _survey(survey.organization_id, "en")
    action = Action.objects.create(survey=s)
    row = ActionTranslation.objects.create(action=action, language="default", title="Act")
    ActionTranslation.objects.create(action=action, language="en", title=title, description=description)

    assert _bucket_of(dl.find_default_rows(), ACTION, row) == dl.CLASH_WITH_TEXT


def test_own_survey_wins_over_the_options(survey, options):
    Survey.objects.filter(pk=survey.pk).update(primary_language="en")
    own = _survey(survey.organization_id, "ar")
    _, (row,) = _recommendation(own, option=options[0], texts=[("default", "x")])

    assert dl.find_default_rows()[REC].relabellable_by_language == {"ar": [row.id]}


def test_parent_deleted_is_checked_before_no_survey(db):
    c, (row,) = _classification(texts=[("default", "Low")])
    Classification._base_manager.filter(pk=c.pk).update(deleted_at=now())

    assert _bucket_of(dl.find_default_rows(), CLASS, row) == dl.PARENT_DELETED


def test_action_on_a_survey_with_no_primary_language(survey):
    Survey.objects.filter(pk=survey.pk).update(primary_language=None)
    row = ActionTranslation.objects.create(action=Action.objects.create(survey=survey), language="default", title="Act")

    assert _bucket_of(dl.find_default_rows(), ACTION, row) == dl.NO_PRIMARY_LANGUAGE


def test_padded_primary_language_is_stripped(survey):
    Survey.objects.filter(pk=survey.pk).update(primary_language=" ar ")
    _, (row,) = _classification(survey, [("default", "Low")])

    assert dl.find_default_rows()[CLASS].relabellable_by_language == {"ar": [row.id]}


def test_relabellable_on_a_deleted_survey_is_flagged(survey, options):
    gone = _survey(survey.organization_id)
    _, (row,) = _classification(gone, [("default", "Low")])
    Survey.objects.filter(pk=gone.pk).update(deleted_at=now())
    _, (via_option,) = _recommendation(option=options[0], texts=[("default", "x")])
    options[0].__class__.objects.filter(pk=options[0].pk).update(deleted_at=now())
    _, (live,) = _classification(survey, [("default", "High")])

    found = dl.find_default_rows()

    assert found[CLASS].survey_deleted == [row.id]
    assert _bucket_of(found, CLASS, row) == dl.RELABELLABLE
    assert found[REC].survey_deleted == [via_option.id]
    assert "classification translations: relabellable but the survey or option is deleted: 1" in dl.summary(found)


def test_blank_default_row_is_flagged(survey):
    _, (row,) = _classification(survey, [("default", "<p>&nbsp;</p>")])
    _classification(survey, [("default", "Low")])

    found = dl.find_default_rows()

    assert found[CLASS].default_blank == [row.id]
    assert "classification translations: relabellable but the default text itself is blank: 1" in dl.summary(found)


def test_default_variant_is_counted_apart(survey):
    _, (row,) = _classification(survey, [("Default", "Low")])
    _classification(survey, [(" default", "High")])

    found = dl.find_default_rows()

    assert found[CLASS].total == 0
    assert found[CLASS].variants == 2
    assert (
        'classification translations: labelled a "default" variant (other case or spaces), not counted above: 2'
        in dl.summary(found)
    )


def test_ruling_buckets_list_their_ids(db):
    _, (row,) = _classification(texts=[("default", "Orphan")])

    assert f"classification translations: no survey ids: {row.id}" in dl.summary(dl.find_default_rows())


def test_ids_line_is_capped(db):
    rows = [_classification(texts=[("default", "x")])[1][0] for _ in range(dl.MAX_IDS + 1)]

    line = next(l for l in dl.summary(dl.find_default_rows()) if "no survey ids:" in l)

    assert line.endswith(", …")
    assert line.count(",") == dl.MAX_IDS


def test_report_sits_on_the_current_leaves():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    migration = loader.get_migration("surveys", "0061_report_default_language_rows")

    assert set(migration.dependencies) == {
        ("surveys", "0060_apply_search_backfill"),
        ("classifications", "0003_remove_classification_name"),
        ("recommendations", "0006_report_empty_recommendations"),
    }
    assert loader.graph.leaf_nodes("surveys") == [("surveys", "0061_report_default_language_rows")]
