"""Repair the null owners left between the 0035 backfill and the CAP-1 binding.

0035 set every null ``organization_id`` to the ``itqadem`` org on 2026-04-26.
But ``create_survey`` did not bind the column from the caller's auth context
until 2026-09-22 (SPEC-forms-permission-gates CAP-1), and no client ever sent
``organizationId`` — so everything created through the app in that window is
null-owned again. CAP-2's ``ensure_in_org`` treats a null owner as a refusal,
which makes those rows invisible to every tenant caller, so the repair has to
land with it.

Prod cannot run a management command, so the repair rides in as a data
migration: it runs unattended at deploy, on every environment. Every null row
it finds today was created after 0035, which is exactly the window in
question — there is no date filter to apply.

``Survey`` carries no creator or user column, so there is no per-row signal to
attribute ownership from; ``itqadem`` is the same answer 0035 gave, for the
same reason.
"""
import logging

from django.db import migrations

ORG_SLUG = "itqadem"

logger = logging.getLogger(__name__)


def _resolve_org_id():
    from pkg_auth.authorization.adapters.django_orm.models import Organization

    return (
        Organization.objects.using("acl")
        .values_list("id", flat=True)
        .get(slug=ORG_SLUG)
    )


def backfill(apps, schema_editor):
    # Deliberately allowed to raise if the slug is missing: a silent skip would
    # leave the rows unreachable behind the CAP-2 gate with nothing in the
    # deploy log to say so.
    org_id = _resolve_org_id()

    Survey = apps.get_model("surveys", "Survey")
    SurveyCollection = apps.get_model("survey_collections", "SurveyCollection")
    ChildGuardian = apps.get_model("accounts", "ChildGuardian")

    for label, queryset, value in (
        ("surveys.Survey", Survey.objects.filter(organization_id__isnull=True), org_id),
        (
            "survey_collections.SurveyCollection",
            SurveyCollection.objects.filter(organization_id__isnull=True),
            org_id,
        ),
        (
            "accounts.ChildGuardian",
            ChildGuardian.objects.filter(organization_id__isnull=True),
            str(org_id),
        ),
    ):
        # Counted before the update so the deploy log answers "how many rows
        # were stranded?" — there is no other way to take that number.
        affected = queryset.count()
        queryset.update(organization_id=value)
        logger.info(
            "0040 backfill: %s rows of %s had a null organization_id, set to %r (%s)",
            affected, label, ORG_SLUG, org_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0039_normalize_survey_type"),
        ("survey_collections", "0014_surveycollection_cover_id_surveycollection_thumb_id"),
        ("accounts", "0003_childguardian"),
    ]

    operations = [
        # Irreversible on purpose. 0035's reverse blanked every itqadem-owned
        # row, which was survivable when nothing else wrote the column. It is
        # not survivable now: CAP-1 binds real owners on write, so a reverse
        # cannot tell a row this migration repaired from one a caller
        # legitimately created in the itqadem org, and blanking both would
        # destroy ownership data rather than restore a prior state.
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
