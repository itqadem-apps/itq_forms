"""Report the collection memberships that break the collection rules (intake report #128, story
curricula-order 2.1).

Report only: it writes nothing. It prints, over every link and over the links shown today, the
number of members that are not curricula (with one line per survey type) and the number of
curricula in more than one collection, with their ids. Read it from the forms migrate job's
output in Loki, `{namespace="itqadem",service_name="forms"} |= "collection-rules:"`. What the
apply does with them waits on the developer's ruling. Never delete this migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from survey_collections import rule_report

    print("\n  collection-rules: report (nothing written)")
    for line in rule_report.summary(
        rule_report.find(apps.get_model("survey_collections", "CollectionMembership"))
    ):
        print(f"  collection-rules: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("survey_collections", "0016_collection_member_order"),
        ("surveys", "0062_apply_default_language_relabel"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
