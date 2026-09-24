"""The primary locale must name one language, and always the same one.

`forms:AD-1`. The enrolment snapshot merges each source row's legacy column
(`Section.title`, `Question.title`, `AnswerSchemaOption.text`) into exactly one
language's key — the survey's primary locale — wherever the translation for
that language is null or empty. The admin builder mirrors those same legacy
columns from the locale *it* calls primary. Nothing checks that the two agree,
and nothing fails when they do not: the learner just gets one language's words
filed under another language's key.

It used to be derivable two ways. `survey.translations.first()` is `ORDER BY id`
over a `uuid4` primary key — an answer that depends on which row won a coin
toss at insert time, and so differs per survey. These tests pin the single
definition instead: the value stored on `Survey.primary_language`.

Stored rather than derived because `create_survey_snapshot` freezes the primary
into each learner's own rows and never revisits them. A derived primary moves
the moment an author adds a translation; every learner who enrolled between the
move and a re-save of the body text would keep the mislabel for good. Several
tests below exist only to pin that it does *not* move.
"""

import importlib
from uuid import UUID

import pytest

from surveys.models import (
    Section,
    SectionTranslation,
    Survey,
    SurveyTranslation,
)
from user_surveys.models import UserSection
from user_surveys.services import enroll_user_in_assessment


@pytest.fixture
def bare_survey(db):
    return Survey.objects.create(
        survey_type=Survey.ASSESSMENT_TYPE_SURVEY,
        display_option=Survey.DISPLAY_OPTION_BY_QUESTION,
        evaluation_type=Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION,
    )


def _translate(survey, *languages):
    for language in languages:
        SurveyTranslation.objects.create(
            survey=survey, language=language, title=f"title-{language}"
        )


def _reload(survey):
    return Survey.objects.get(pk=survey.pk)


# ── the definition ───────────────────────────────────────────────────

def test_the_stored_column_is_the_definition(bare_survey):
    """Not the alphabetically first language, not the first row, not the most
    translated — whatever the column says."""
    _translate(bare_survey, "ar", "en")
    bare_survey.primary_language = "en"
    bare_survey.save(update_fields=["primary_language"])

    assert _reload(bare_survey).primary_locale == "en"


def test_it_does_not_consult_the_translations_at_all(bare_survey):
    """A primary with no translation row behind it still reports itself. The
    accessor answers from the column; query B of the audit SQL is what finds
    this state, rather than the accessor quietly papering over it."""
    _translate(bare_survey, "en")
    bare_survey.primary_language = "fr"
    bare_survey.save(update_fields=["primary_language"])

    survey = _reload(bare_survey)
    assert survey.primary_locale == "fr"
    assert survey.title is None


def test_a_survey_with_no_primary_falls_back(bare_survey):
    assert bare_survey.primary_language is None
    assert bare_survey.primary_locale == Survey.PRIMARY_LANGUAGE_FALLBACK == "default"


def test_the_other_accessors_agree_with_it(bare_survey):
    """`Survey.language` and `Survey.title` are the other two places that used
    to answer this question independently."""
    _translate(bare_survey, "en", "ar")

    survey = _reload(bare_survey)
    assert survey.language == survey.primary_locale == "en"
    assert survey.title == "title-en"


def test_language_reports_absence_rather_than_the_fallback(bare_survey):
    assert bare_survey.language is None


def test_nothing_orders_translations_by_language_any_more(bare_survey):
    """The first ruling put `ordering = ["language"]` on the translation models
    and made that ordering the definition. It was reversed; a model ordering
    reinstated for a list view must not quietly become the definition again,
    and `primary_locale` must not read through one."""
    assert not SurveyTranslation._meta.ordering

    _translate(bare_survey, "en", "ar")
    bare_survey.primary_language = "en"
    bare_survey.save(update_fields=["primary_language"])
    assert _reload(bare_survey).primary_locale == "en"


# ── the write path keeps it honest ───────────────────────────────────

def test_the_first_language_authored_claims_it(bare_survey):
    _translate(bare_survey, "en")
    assert _reload(bare_survey).primary_language == "en"


def test_an_earlier_language_does_not_move_it(bare_survey):
    """The reversal, in one test. Under the ordering rule this flipped to `ar`
    and every legacy column in the survey silently changed which language it
    was backing."""
    _translate(bare_survey, "en")
    _translate(bare_survey, "ar")

    assert _reload(bare_survey).primary_locale == "en"


def test_a_later_language_does_not_move_it_either(bare_survey):
    _translate(bare_survey, "ar")
    _translate(bare_survey, "en")

    assert _reload(bare_survey).primary_locale == "ar"


def test_re_saving_a_translation_does_not_move_it(bare_survey):
    _translate(bare_survey, "en")
    later = SurveyTranslation.objects.create(survey=bare_survey, language="ar", title="x")
    later.title = "y"
    later.save()

    assert _reload(bare_survey).primary_locale == "en"


def test_bulk_create_does_not_claim_it(bare_survey):
    """Documented on `SurveyTranslation.save`: `bulk_create` bypasses the hook,
    so an importer using it has to set the column itself. Pinned so the gap is
    a known one rather than a discovery."""
    SurveyTranslation.objects.bulk_create(
        [SurveyTranslation(survey=bare_survey, language="en", title="t")]
    )

    assert _reload(bare_survey).primary_language is None


# ── what the snapshot does with it ───────────────────────────────────

def test_the_snapshot_files_the_legacy_column_under_the_primary_locale(user, bare_survey):
    """The whole point. A blank `ar` section title falls back to the legacy
    column, and lands under `en` — the same key the builder mirrors that column
    from."""
    _translate(bare_survey, "en", "ar")
    section = Section.objects.create(
        survey=bare_survey, title="Legacy title", description="Legacy description"
    )
    SectionTranslation.objects.create(section=section, language="ar", title="")
    SectionTranslation.objects.create(section=section, language="en", title="")

    user_survey, _ = enroll_user_in_assessment(user, bare_survey.id)

    snapshot = UserSection.objects.get(user_survey=user_survey, origin_id=section.id)
    assert snapshot.translations["en"]["title"] == "Legacy title"
    assert snapshot.translations["ar"]["title"] in (None, "")


def test_the_snapshot_does_not_depend_on_translation_row_order(user, bare_survey):
    """Same survey, translations authored in the other order. Under `ORDER BY
    id` this pair of runs could disagree; the column makes the survey's own
    authoring history the only thing that decides."""
    _translate(bare_survey, "en")
    _translate(bare_survey, "ar")
    section = Section.objects.create(survey=bare_survey, title="Legacy title")
    SectionTranslation.objects.create(section=section, language="ar", title=None)
    SectionTranslation.objects.create(section=section, language="en", title=None)

    user_survey, _ = enroll_user_in_assessment(user, bare_survey.id)

    snapshot = UserSection.objects.get(user_survey=user_survey, origin_id=section.id)
    assert snapshot.translations["en"]["title"] == "Legacy title"


def test_adding_a_language_does_not_change_what_a_later_learner_gets(user, django_user_model, bare_survey):
    """The freeze argument, as a test. Snapshots are never revisited, so the
    only defence a learner who enrols tomorrow has is that the primary did not
    move today."""
    _translate(bare_survey, "en")
    section = Section.objects.create(survey=bare_survey, title="Legacy title")

    first, _ = enroll_user_in_assessment(user, bare_survey.id)

    _translate(bare_survey, "ar")
    later_user = django_user_model.objects.create(username="later-learner")
    second, _ = enroll_user_in_assessment(later_user, bare_survey.id)

    for user_survey in (first, second):
        snapshot = UserSection.objects.get(user_survey=user_survey, origin_id=section.id)
        assert snapshot.translations["en"]["title"] == "Legacy title"
        assert "ar" not in snapshot.translations or snapshot.translations["ar"].get("title") != "Legacy title"


def test_a_survey_with_no_primary_snapshots_under_the_fallback(user, bare_survey):
    section = Section.objects.create(survey=bare_survey, title="Legacy title")

    user_survey, _ = enroll_user_in_assessment(user, bare_survey.id)

    snapshot = UserSection.objects.get(user_survey=user_survey, origin_id=section.id)
    assert snapshot.translations["default"]["title"] == "Legacy title"


# ── the backfill ─────────────────────────────────────────────────────

def _run_backfill():
    from django.apps import apps

    module = importlib.import_module("surveys.migrations.0041_backfill_survey_primary_language")
    module.backfill(apps, None)


def test_the_backfill_reproduces_the_old_selector(bare_survey):
    """`.first()` meant `ORDER BY id`, so the lowest-id translation named the
    language — whatever order the rows were written in. Reproducing it exactly
    is what makes the migration behaviour-preserving: no survey's primary moves
    as the column lands, and so nobody had to audit production first."""
    SurveyTranslation.objects.create(
        id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        survey=bare_survey,
        language="ar",
        title="written first",
    )
    SurveyTranslation.objects.create(
        id=UUID("00000000-0000-4000-8000-000000000000"),
        survey=bare_survey,
        language="en",
        title="written second",
    )
    Survey.objects.filter(pk=bare_survey.pk).update(primary_language=None)

    _run_backfill()

    assert _reload(bare_survey).primary_language == "en"


def test_the_backfill_leaves_a_translationless_survey_null(bare_survey):
    Survey.objects.filter(pk=bare_survey.pk).update(primary_language=None)

    _run_backfill()

    survey = _reload(bare_survey)
    assert survey.primary_language is None
    assert survey.primary_locale == Survey.PRIMARY_LANGUAGE_FALLBACK


def test_the_backfill_does_not_overwrite_a_primary_that_is_already_set(bare_survey):
    """It fills gaps; it does not have an opinion about a survey that already
    has an answer. Re-running the migration must not move anything."""
    _translate(bare_survey, "en", "ar")
    Survey.objects.filter(pk=bare_survey.pk).update(primary_language="ar")

    _run_backfill()

    assert _reload(bare_survey).primary_language == "ar"


# ── the citable contract ─────────────────────────────────────────────

def test_the_graphql_field_returns_the_same_value(bare_survey):
    """The canvas reads `Survey.primaryLanguage` instead of deriving a primary
    of its own, so this field is load-bearing rather than informational."""
    from surveys.types.survey import SurveyType

    _translate(bare_survey, "en", "ar")
    survey = _reload(bare_survey)

    assert SurveyType.primary_language(survey) == survey.primary_locale == "en"
