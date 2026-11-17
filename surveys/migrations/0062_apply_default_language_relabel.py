"""Relabel the translations an old import saved under the language "default" (intake report #132,
story default-language-translations 1.2).

It ships only after 0061's counts in the migrate-job log (Loki,
`{namespace="itqadem",service_name="forms"}`, lines prefixed `default-language:`) were read: 36
classification, 8,187 recommendation and 11 action translations relabellable, all to "ar", and 4
recommendation rows clashing with an Arabic row that has text.

Forward
    Re-evaluates `surveys.default_language.find_default_rows()` (the report's rule) and relabels
    every row in each table's relabellable bucket to its survey's primary language, changing only
    the `language` column; each update is guarded by `language="default"`. Clash rows are left as
    they are (ruled "Keep the Arabic text", 2026-11-17), as are rows whose parent is deleted, has no
    survey or has no primary language. If an update touches a different number of rows than its
    bucket holds it raises, and the default `atomic` rolls the whole migration back. It prints, per
    table, the count relabelled to each language and the count left labelled "default", then the
    0061 report re-run after the apply. Expected on prod: 36 / 8,187 / 11 relabelled to ar,
    0 / 4 / 0 left.

Reverse: irreversible in code
    The reverse is a no-op. The relabelled ids per table are not logged; the counts are in the Loki
    query above. Never delete this migration once it has run.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import default_language

    print("  default-language: apply (relabel to the survey's primary language)")
    for line in default_language.apply(default_language.find_default_rows()):
        print(f"  default-language: {line}")
    for line in default_language.summary(default_language.find_default_rows()):
        print(f"  default-language: after apply: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0061_report_default_language_rows"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
