"""Apply what story autism-merge 1.1 reported (report #64, `estate:AD-20`).

Apply release, built from the report 0053 printed in prod (forms-migrate-75d668b56f,
2026-10-06 14:02 UTC), which is saved verbatim as the undo record in
`.agent/implementation/spec-autism-merge-1-1-repoint-forms.md`. It moves exactly the reported
surveys {189, 5} and survey collections {1..7} from التوحد (7878f298-…) to اضطراب طيف التوحد
(6684c538-…) and republishes each one (SurveyUpdated / CollectionUpdated) so consumers refresh
category_id. Item rows only: no category or category-translation row is written (`estate:AD-15`).

If live data differs from the report (a missing or tombstoned category, different trees, children,
or other items on the source) it prints the mismatch and raises, failing the deploy with nothing
written. A re-run, where every reported item is already on the target and none remain on the
source, is a printed no-op. A database holding neither category is a printed no-op too.

Reverse: noop. Undo is the report: re-point the listed ids back to the source by hand, because a
blind reverse could not tell the reported items from items tagged اضطراب طيف التوحد later.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import autism_merge

    print("\n  autism-merge apply:")
    autism_merge.apply(echo=lambda line: print(f"  autism-merge: {line}"))


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0053_report_autism_merge"),
        ("pricing", "0006_price_currency_egp_constraints"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
