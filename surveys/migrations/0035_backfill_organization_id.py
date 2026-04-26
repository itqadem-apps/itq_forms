from django.db import migrations

ORG_SLUG = "itqadem"


def _resolve_org_id():
    from pkg_auth.authorization.adapters.django_orm.models import Organization

    return (
        Organization.objects.using("acl")
        .values_list("id", flat=True)
        .get(slug=ORG_SLUG)
    )


def backfill(apps, schema_editor):
    org_id = _resolve_org_id()

    Survey = apps.get_model("surveys", "Survey")
    SurveyCollection = apps.get_model("survey_collections", "SurveyCollection")
    ChildGuardian = apps.get_model("accounts", "ChildGuardian")

    Survey.objects.filter(organization_id__isnull=True).update(organization_id=org_id)
    SurveyCollection.objects.filter(organization_id__isnull=True).update(
        organization_id=org_id
    )
    ChildGuardian.objects.filter(organization_id__isnull=True).update(
        organization_id=str(org_id)
    )


def unbackfill(apps, schema_editor):
    org_id = _resolve_org_id()

    Survey = apps.get_model("surveys", "Survey")
    SurveyCollection = apps.get_model("survey_collections", "SurveyCollection")
    ChildGuardian = apps.get_model("accounts", "ChildGuardian")

    Survey.objects.filter(organization_id=org_id).update(organization_id=None)
    SurveyCollection.objects.filter(organization_id=org_id).update(organization_id=None)
    ChildGuardian.objects.filter(organization_id=str(org_id)).update(
        organization_id=None
    )


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0034_survey_organization_id"),
        ("survey_collections", "0012_surveycollection_organization_id"),
        ("accounts", "0003_childguardian"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
