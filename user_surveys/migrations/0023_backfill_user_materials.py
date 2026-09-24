"""Best-effort backfill of UserMaterial for enrolments that predate 0022.

Those learners were snapshotted before the table existed, so the only record of
what their bands recommended is `UserAction.origin_id` pointing at the live
`Action`. `Action` is hard-deleted and cascades with its `Survey`, so that
pointer dangles for some rows — those are skipped, not failed. The rest get
exactly what a fresh enrolment would write today.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    UserAction = apps.get_model("user_surveys", "UserAction")
    UserMaterial = apps.get_model("user_surveys", "UserMaterial")
    Material = apps.get_model("recommendations", "Material")

    # 0022 creates the table, so a normal forward run starts empty. Re-running
    # against a partly-populated table is the case this guards, and skipping
    # the join entirely is what keeps the common path off a full-table join.
    already = set()
    if UserMaterial.objects.exists():
        already = set(UserMaterial.objects.values_list("user_action_id", flat=True))

    user_actions = [
        ua
        for ua in UserAction.objects.filter(origin_id__isnull=False).only(
            "id", "origin_id", "user_survey_id"
        )
        if ua.id not in already
    ]
    if not user_actions:
        return

    by_action = {}
    origin_ids = {ua.origin_id for ua in user_actions}
    for material in Material.objects.filter(action_id__in=origin_ids).select_related("recommendable"):
        by_action.setdefault(material.action_id, []).append(material)

    rows = []
    for user_action in user_actions:
        for material in by_action.get(user_action.origin_id, ()):
            recommendable = material.recommendable
            rows.append(
                UserMaterial(
                    origin_id=material.id,
                    user_survey_id=user_action.user_survey_id,
                    user_action_id=user_action.id,
                    recommendable=recommendable,
                    source_service=recommendable.source_service,
                    source_model=recommendable.source_model,
                    source_id=recommendable.source_id,
                    data=recommendable.data or {},
                )
            )

    if rows:
        UserMaterial.objects.bulk_create(rows, batch_size=1000)


def backwards(apps, schema_editor):
    UserMaterial = apps.get_model("user_surveys", "UserMaterial")
    UserMaterial.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0022_usermaterial"),
        ("recommendations", "0005_recommendable_replace_generic_fk"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
