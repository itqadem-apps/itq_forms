"""Replay the published assessments into search (story search-indexes-assessments 1.2,
report #102).

It ships only after 0059's count in the R1 migrate-job log (Loki,
`{namespace="itqadem",service_name="forms"}`) has been read and story 1.1's indexer fix
(fri_fast_search) is live; replayed events are indexed only by the fixed indexer. Comparing this
release's count with R1's is a manual gate.

Forward
    Runs `manage.py reconcile_snapshot --published-only --surveys-only --live-only`: one
    `SurveyCreated` and one `SurveyPublished` per live published survey go to the outbox, and the
    relay forwards them after commit. Soft-deleted surveys are not replayed, collections are left
    out (`--surveys-only`; search has no source type for them), and
    the event shape is unchanged. The default `atomic` makes the replay all-or-nothing. It prints
    `search-backfill: surveys=<n> events=<e> skipped=<s>`, the same line as 0059.

Reverse: irreversible in code
    `backwards` is a no-op. Relayed rows cannot be recalled, but the consumers (search, itq_courses,
    itq_orders) are idempotent for a replay. A survey indexed wrongly is corrected by unpublishing or
    deleting it in forms.
"""

import re
from io import StringIO

from django.core.management import call_command
from django.db import migrations

_COUNT = re.compile(r"\[surveys\] emitted=(\d+) skipped=(\d+)")


def forwards(apps, schema_editor):
    buf = StringIO()
    call_command(
        "reconcile_snapshot", "--published-only", "--surveys-only", "--live-only",
        stdout=buf,
    )
    out = buf.getvalue()
    match = _COUNT.search(out)
    if match is None:
        raise RuntimeError(f"search-backfill: no count line in reconcile_snapshot output: {out!r}")
    events, skipped = int(match[1]), int(match[2])
    print("\n  search backfill, apply:")
    print(f"  search-backfill: surveys={events // 2} events={events} skipped={skipped}")


def backwards(apps, schema_editor):
    """Irreversible in code; the module docstring says how a wrong replay is corrected."""


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0059_report_search_backfill"),
        ("unimessaging", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
