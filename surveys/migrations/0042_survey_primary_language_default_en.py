from django.db import migrations, models

"""Give `Survey.primary_language` an English default, and fill the rows 0041 left null.

`forms:AD-1` keeps the primary a stored column so it cannot move under a learner.
0041 filled it from the translations each survey already had; a survey with no
translations kept a null column and read back as `PRIMARY_LANGUAGE_FALLBACK` —
`"default"`, which names no locale the admin builder offers. The builder read
that as "this survey has no primary language", refused per-language body text,
and said so on every visit, so a new survey could never be authored in two
languages without someone setting the column by hand first.

Those rows now say `en`. This *does* move the key their legacy columns are filed
under at enrolment, from `default` to `en` — the only rows that move are ones
with no translations at all, where no language key was ever readable.
"""

LANGUAGE = "en"


def fill(apps, schema_editor):
    apps.get_model("surveys", "Survey").objects.filter(
        primary_language__isnull=True
    ).update(primary_language=LANGUAGE)


def unfill(apps, schema_editor):
    """Not reversible in kind: the rows this filled are indistinguishable from
    ones 0041 filled with `en` from a real translation, and nulling both would
    lose a primary an admin had set."""


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0041_backfill_survey_primary_language"),
    ]

    operations = [
        migrations.AlterField(
            model_name="survey",
            name="primary_language",
            field=models.CharField(
                blank=True,
                default="en",
                help_text="The language this survey's body text is authored in. Read it through Survey.primary_locale, never directly. It decides which language key the legacy title/description/text columns fall back into when a learner enrols, so changing it on a survey that already has content mislabels that content until every row is re-saved.",
                max_length=10,
                null=True,
                verbose_name="Primary Language",
            ),
        ),
        migrations.RunPython(fill, unfill),
    ]
