"""Best-effort backfill of UserMaterial for enrolments that predate 0022.

Those learners were snapshotted before the table existed, so the only record of
what their bands recommended is `UserAction.origin_id` pointing at the live
`Action`. `Action` is hard-deleted and cascades with its `Survey`, so that
pointer dangles for some rows; those are skipped rather than failing the deploy.

Runs once, ever. See `forwards` for why that is load-bearing and not just tidy.
"""

from django.db import migrations

# Rows per bulk_create and per iterator page. UserAction carries one row per
# band per enrolment, so on a mature survey service this table is large; the
# batch is what keeps peak memory flat instead of proportional to it.
BATCH = 2000


def forwards(apps, schema_editor):
    UserAction = apps.get_model("user_surveys", "UserAction")
    UserMaterial = apps.get_model("user_surveys", "UserMaterial")
    Material = apps.get_model("recommendations", "Material")

    # Run once, ever. 0022 creates the table, so on a real forward deploy this
    # is empty and the backfill proceeds. On any later re-run — reverse to 0022
    # and re-apply, say — it is not, and we must not touch it.
    #
    # This is a correctness guard, not an optimisation. Keying on "which
    # user_actions already have rows" instead would skip only bands that were
    # pinned at enrolment: a band that had NO materials then is absent from
    # that set, so a re-run would hand an already-enrolled learner whatever an
    # admin has pinned since. That silently breaks the freeze rule the whole
    # design rests on. A partly-written first run cannot strand us here — the
    # migration is atomic, so a failure rolls the table back to empty.
    if UserMaterial.objects.exists():
        return

    # Admin-authored and small (bands x pinned entries), unlike UserAction.
    # Loading it first turns the scan below into a bounded `IN` over the
    # actions that actually have materials, instead of a walk of every
    # UserAction row ever written.
    by_action = {}
    for material in Material.objects.select_related("recommendable").iterator(chunk_size=BATCH):
        by_action.setdefault(material.action_id, []).append(material)
    if not by_action:
        return

    batch = []
    user_actions = (
        UserAction.objects.filter(origin_id__in=list(by_action))
        .only("id", "origin_id", "user_survey_id")
        .iterator(chunk_size=BATCH)
    )
    for user_action in user_actions:
        for material in by_action.get(user_action.origin_id, ()):
            recommendable = material.recommendable
            batch.append(
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
        if len(batch) >= BATCH:
            UserMaterial.objects.bulk_create(batch, batch_size=BATCH)
            batch = []

    if batch:
        UserMaterial.objects.bulk_create(batch, batch_size=BATCH)


def backwards(apps, schema_editor):
    """Deliberately a no-op.

    Nothing on a UserMaterial row says whether the backfill wrote it or the
    enrolment snapshot did, so `all().delete()` here would take every row a
    learner has been given since deploy — and `migrate user_surveys 0022`
    reverses this migration WITHOUT dropping the table, so that data would not
    come back. Reversing past 0022 drops the table and takes the rows with it,
    which is the only reversal that should lose anything.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0022_usermaterial"),
        ("recommendations", "0005_recommendable_replace_generic_fk"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
