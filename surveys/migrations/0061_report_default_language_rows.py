"""Report the translations an old import saved under the language "default" (intake report #132,
story default-language-translations 1.1).

Report only: it writes nothing. For each of the classification, recommendation and action
translation tables it prints the number of rows labelled "default" and how many fall in each
bucket of `surveys.default_language` (parent deleted, no survey, no primary language, clash with a
primary-language row that has text, clash with a blank one, relabellable), then the relabellable
count per primary language. Read it from the forms migrate job's output in Loki,
`{namespace="itqadem",service_name="forms"}`, lines prefixed `default-language:`. The apply, which
relabels (story 1.2), ships separately in its own release. Never delete this migration once it has
run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import default_language

    print("  default-language: report (nothing written)")
    for line in default_language.summary(default_language.find_default_rows()):
        print(f"  default-language: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0060_apply_search_backfill"),
        ("classifications", "0003_remove_classification_name"),
        ("recommendations", "0006_report_empty_recommendations"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
