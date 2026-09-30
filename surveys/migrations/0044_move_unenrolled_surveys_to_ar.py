from django.db import migrations
from django.db.models import Exists, OuterRef

"""Move every survey no learner has enrolled in to an Arabic primary.

Ruled 2026-09-29 (`forms:AD-1`): all of them, not only the ones 0042's `en`
default mislabelled. The accepted cost: an English-authored or bilingual
survey's legacy columns are filed under `ar` at its next enrolment wherever the
`ar` translation is empty, and an English-only survey reads `Survey.title` as
None until someone sets its primary back.

A survey with any `UserSurvey` keeps its primary — each enrolment froze it into
that learner's snapshot. `tools/audit_primary_locale.sql` lists those for a
per-survey ruling.

The enrolled check and the write are one UPDATE … WHERE NOT EXISTS: Tekton runs
this while the old pod is still enrolling learners, and a check-then-write in
two statements would move a survey someone enrolled in between them.
"""

LANGUAGE = "ar"


def move(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    UserSurvey = apps.get_model("user_surveys", "UserSurvey")
    Survey.objects.exclude(primary_language=LANGUAGE).filter(
        ~Exists(UserSurvey.objects.filter(survey_id=OuterRef("pk")))
    ).update(primary_language=LANGUAGE)


def unmove(apps, schema_editor):
    """Not reversible: the moved rows' previous primaries are not recorded, and
    an admin may have authored against `ar` since."""


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0043_survey_primary_language_default_ar"),
        ("user_surveys", "0023_backfill_user_materials"),
    ]

    operations = [
        migrations.RunPython(move, unmove),
    ]
