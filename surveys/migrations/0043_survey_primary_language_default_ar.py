from django.db import migrations, models

"""Default `Survey.primary_language` to Arabic.

The business ruled on 2026-09-29 that a survey's default language is Arabic
(`forms:AD-1`). ORM-level only, as 0042's `en` was: there is no `db_default`, so
a row inserted by raw SQL stays null and reads `PRIMARY_LANGUAGE_FALLBACK`.

No row moves here. Moving the unenrolled surveys is 0044's job, and a survey
with an enrolment never moves: its learners' snapshots froze its primary.
"""


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0042_survey_primary_language_default_en"),
    ]

    operations = [
        migrations.AlterField(
            model_name="survey",
            name="primary_language",
            field=models.CharField(
                blank=True,
                default="ar",
                help_text="The language this survey's body text is authored in. Read it through Survey.primary_locale, never directly. It decides which language key the legacy title/description/text columns fall back into when a learner enrols, so changing it on a survey that already has content mislabels that content until every row is re-saved.",
                max_length=10,
                null=True,
                verbose_name="Primary Language",
            ),
        ),
    ]
