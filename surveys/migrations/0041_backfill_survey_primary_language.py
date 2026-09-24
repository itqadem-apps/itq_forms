from collections import defaultdict

from django.db import migrations

"""Fill `Survey.primary_language` with the value the old code already chose.

`forms:AD-1`. Before this pair of migrations, "the survey's primary locale" was
spelled three separate times — `Survey.primary_locale`, `Survey.language`, and
`create_survey_snapshot` — each as `survey.translations.first()`. On an
unordered queryset Django's `first()` falls back to `order_by("pk")`, so all
three resolved to the language of the *lowest-id* translation row: stable for a
fixed set of rows, but arbitrary in which language it names.

This backfill reproduces that selector exactly, which makes the migration
behaviour-preserving by construction: no survey's primary locale moves as the
column lands, so no learner enrolling across the deploy is filed under a
different language key than they would have been the day before. That is the
whole reason a backfill was preferred to deriving the value afresh — nobody has
to audit production first to know the answer is "nothing changes".

Query A of `tools/audit_primary_locale.sql` is this same selector in SQL, and
stays useful as a written-down statement of what the column now holds.

Surveys with no translations keep a null column and go on reading as
`Survey.PRIMARY_LANGUAGE_FALLBACK`, which is what the snapshot has always done
for them.
"""

CHUNK = 1000


def backfill(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    SurveyTranslation = apps.get_model("surveys", "SurveyTranslation")

    # One pass over the translations in (survey, id) order; the first row seen
    # for a survey is the one `.first()` would have returned for it.
    first_language = {}
    rows = SurveyTranslation.objects.order_by("survey_id", "id").values_list("survey_id", "language")
    for survey_id, language in rows.iterator():
        if language:
            first_language.setdefault(survey_id, language)

    by_language = defaultdict(list)
    for survey_id, language in first_language.items():
        by_language[language].append(survey_id)

    for language, survey_ids in by_language.items():
        for start in range(0, len(survey_ids), CHUNK):
            Survey.objects.filter(
                pk__in=survey_ids[start : start + CHUNK],
                primary_language__isnull=True,
            ).update(primary_language=language)


def unbackfill(apps, schema_editor):
    """Reversing this is 0040's job — it drops the column outright.

    Nulling the values here instead would throw away any primary an admin had
    since set by hand, to reach a state 0040 is about to discard anyway.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0040_survey_primary_language"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
