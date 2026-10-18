"""Report the published assessments the search backfill would replay (story
search-indexes-assessments 1.2, report #102).

Report release (R1): it writes nothing. It runs `manage.py reconcile_snapshot --published-only
--surveys-only --live-only --dry-run` and prints one line,
`search-backfill: surveys=<n> events=<e> skipped=<s>`: the live published surveys the apply would
replay, the `SurveyCreated` + `SurveyPublished` events that makes, and the surveys skipped for
having no organization. Soft-deleted surveys are not counted, and collections are left out
(`--surveys-only`): the search indexer has no source type for them.
Read it from the forms migrate job's output in Loki, `{namespace="itqadem",service_name="forms"}`.
The apply, which writes those events to the outbox, ships as 0060 in a later release. Never
delete this migration once it has run.

Reverse: nothing to undo.
"""

import re
from io import StringIO

from django.core.management import call_command
from django.db import migrations

_COUNT = re.compile(r"\[surveys\] would emit=(\d+) skipped=(\d+)")


def forwards(apps, schema_editor):
    buf = StringIO()
    call_command(
        "reconcile_snapshot", "--published-only", "--surveys-only", "--live-only", "--dry-run",
        stdout=buf,
    )
    out = buf.getvalue()
    match = _COUNT.search(out)
    if match is None:
        raise RuntimeError(f"search-backfill: no count line in reconcile_snapshot output: {out!r}")
    events, skipped = int(match[1]), int(match[2])
    print("\n  search backfill, report (nothing written):")
    print(f"  search-backfill: surveys={events // 2} events={events} skipped={skipped}")


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0058_apply_soft_delete_children"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
