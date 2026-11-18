"""Restore the 5 course exam links 0018 removed (intake report #128, story curricula-order 2.4).

0018's apply ran on prod 2026-11-18 and logged 5 removed exam memberships as
collection/survey/order `23/179/0`, `24/201/0`, `31/198/0`, `134/199/0`, `134/200/1`. They are
most likely course exams in their own course collections, where forms puts them by design.
Ruled "Curricula only, and restore the 5 links" (2026-11-18).

Forward
    For each of the 5 pairs only, recreates the `CollectionMembership` with its logged order when
    the collection and survey rows exist (soft-deleted or not), the collection is a course
    collection (`rule_report.course_collection_ids`) and the link is absent. Every other pair is
    skipped with its reason (`link exists`, `collection missing`, `survey missing`, `not a course
    collection`), leaving any existing link and its order as they are. No other membership,
    survey or collection changes, no member is renumbered, and no event is published.

    It prints one `restored: collection <cid> survey <sid> order <n> (<type>)` or `skipped:
    collection <cid> survey <sid> (<reason>)` line per pair, the skip followed by ` (<type>)` when
    the survey exists. A restored line ends ` order shared` when another member of that
    collection already holds the order (listings break the tie by id). Then `restored: <n>` and
    `skipped: <n>`, adding to 5, then the 0017 report re-run as `after restore:` lines, which
    count no course-collection member. Expected on prod, if all 5 are course collections:
    `restored: 5`, `skipped: 0`, `after restore: all: not curricula: 0`.

    A skip does not fail the migration: any skipped pair is left for a follow-up ruling by the
    developer.

    Read it in Loki: `{namespace="itqadem",service_name="forms"} |= "collection-rules:"`.

Reverse
    A no-op. Never delete this migration once it has run.
"""

from django.db import migrations

# (collection id, survey id, order), as 0018 logged them on prod.
REMOVED_PAIRS = (
    (23, 179, 0),
    (24, 201, 0),
    (31, 198, 0),
    (134, 199, 0),
    (134, 200, 1),
)

LINK_EXISTS = "link exists"


def _skip_reason(collection_id, survey_type, collections, courses, memberships, survey_id):
    if memberships.filter(surveycollection_id=collection_id, survey_id=survey_id).exists():
        return LINK_EXISTS
    if not collections.filter(pk=collection_id).exists():
        return "collection missing"
    if survey_type is None:
        return "survey missing"
    if collection_id not in courses:
        return "not a course collection"
    return None


def forwards(apps, schema_editor):
    from survey_collections import rule_report

    membership = apps.get_model("survey_collections", "CollectionMembership")
    reference = apps.get_model("external_references", "ExternalReference")
    collections = apps.get_model("survey_collections", "SurveyCollection")._base_manager
    surveys = apps.get_model("surveys", "Survey")._base_manager
    courses = rule_report.course_collection_ids(reference)
    memberships = membership._base_manager
    types = dict(surveys.filter(pk__in=[sid for _, sid, _ in REMOVED_PAIRS]).values_list("pk", "survey_type"))

    def label(survey_id):
        return types[survey_id] or rule_report.NO_TYPE

    def skip(collection_id, survey_id, reason):
        typed = f" ({label(survey_id)})" if survey_id in types else ""
        print(f"  collection-rules: skipped: collection {collection_id} survey {survey_id} ({reason}){typed}")

    print("\n  collection-rules: restore (course exam links 0018 removed)")
    restored = skipped = 0
    for collection_id, survey_id, order in REMOVED_PAIRS:
        reason = _skip_reason(collection_id, types.get(survey_id), collections, courses, memberships, survey_id)
        if reason is None:
            shared = memberships.filter(surveycollection_id=collection_id, order=order).exists()
            _, created = memberships.get_or_create(
                surveycollection_id=collection_id, survey_id=survey_id, defaults={"order": order}
            )
            if not created:
                reason = LINK_EXISTS
        if reason:
            skipped += 1
            skip(collection_id, survey_id, reason)
            continue
        restored += 1
        marker = " order shared" if shared else ""
        print(
            f"  collection-rules: restored: collection {collection_id} survey {survey_id} "
            f"order {order} ({label(survey_id)}){marker}"
        )
    print(f"  collection-rules: restored: {restored}")
    print(f"  collection-rules: skipped: {skipped}")
    for line in rule_report.summary(rule_report.find(membership, reference)):
        print(f"  collection-rules: after restore: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("survey_collections", "0018_remove_non_curriculum_members"),
        ("external_references", "0001_initial"),
        ("surveys", "0062_apply_default_language_relabel"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
