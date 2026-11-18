"""Remove the collection memberships whose survey is not a curriculum (intake report #128, story
curricula-order 2.3).

It ships only after 0017's counts in the migrate-job log (Loki,
`{namespace="itqadem",service_name="forms"} |= "collection-rules:"`) were read on prod
(2026-11-18 09:19:40 UTC): 5 members that are not curricula, all exams, and 0 curricula in more
than one collection. Ruled "Remove the 5 links" (2026-11-18).

Forward
    Re-checks the rule at run time (`survey_collections.rule_report`, the report's own test) over
    every link, deleted collections or surveys included, and deletes exactly those membership rows.
    Surveys, collections and the curricula memberships (with their order) are untouched, and no
    event is published. It prints one `removed: collection <cid> survey <sid> order <n> (<type>)`
    line per link, so a link can be restored by hand to its place, then the removed total and one
    line per survey type, then the 0017 report re-run after the apply. If the delete removes a
    different number of memberships than it selected, or cascades to any other row, it raises, and
    the default `atomic` rolls the migration back. Expected on prod: `removed: 5`,
    `removed: exam: 5`, `after apply: all: not curricula: 0`.

Reverse: irreversible in code
    The reverse is a no-op; the removed pairs are in the Loki query above. Never delete this
    migration once it has run.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from survey_collections import rule_report

    membership = apps.get_model("survey_collections", "CollectionMembership")
    reference = apps.get_model("external_references", "ExternalReference")
    print("\n  collection-rules: apply (remove non-curriculum members)")
    for line in rule_report.apply(membership, reference):
        print(f"  collection-rules: {line}")
    for line in rule_report.summary(rule_report.find(membership, reference)):
        print(f"  collection-rules: after apply: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("survey_collections", "0017_report_rule_breaking_members"),
        ("external_references", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
