"""Read every forms id counter beside its table's highest id (intake report #133, stories
add-recommendation 3.1 and 3.2).

On prod every `createRecommendation` failed with a duplicate key on `surveys_recommendation_pkey`:
`legacy_load` hands out explicit ids, so a table's sequence can sit below its `max(id)`. A table is
**behind** when it has rows and the next id its counter would hand out (`last_value + 1` once called,
else `last_value`) is at or below `max(id)`.

The tables are every model of the project's own apps, auto-created M2M through tables included,
whose primary key is an auto-increment field, read from the registry passed in (a migration's
historical `apps`, so a fresh database never names a table that does not exist yet).

Reads only: `last_value` is read straight from the sequence, which never advances it. The report
ships as `surveys` migration 0063 (writes nothing); the apply (story 3.2) reuses `read_counters`
and ships in its own release. Tables are never schema-qualified; `pg_get_serial_sequence` and the
connection's search path resolve them.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import models

PROJECT_APPS = (
    "accounts",
    "surveys",
    "taxonomy",
    "survey_collections",
    "pricing",
    "classifications",
    "recommendations",
    "external_references",
    "user_surveys",
    "media",
)


def serial_tables(apps) -> list[tuple[str, str]]:
    """(table, pk column) for every concrete project table with an auto-increment id, by table."""
    found = set()
    for label in PROJECT_APPS:
        try:
            app_config = apps.get_app_config(label)
        except LookupError:  # an app added later is absent from earlier historical states
            continue
        for model in app_config.get_models(include_auto_created=True):
            meta = model._meta
            if meta.proxy or not meta.managed:
                continue
            if isinstance(meta.pk, models.AutoField):
                found.add((meta.db_table, meta.pk.column))
    return sorted(found)


@dataclass(frozen=True)
class Counter:
    table: str
    sequence: str | None
    last_value: int | None = None
    is_called: bool | None = None
    max_id: int | None = None

    @property
    def next_id(self) -> int | None:
        if self.sequence is None:
            return None
        return self.last_value + 1 if self.is_called else self.last_value

    @property
    def behind(self) -> int:
        """Width of `next_id..max_id`: how many ids the counter must skip to get past `max(id)`
        (0: in step). Not a count of rows; ids in that range may be gaps."""
        if self.sequence is None or self.max_id is None or self.next_id > self.max_id:
            return 0
        return self.max_id - self.next_id + 1


def read_counters(apps, connection) -> list[Counter]:
    """Every serial table's sequence state and `max(id)`, read and never written."""
    counters = []
    qn = connection.ops.quote_name
    with connection.cursor() as cur:
        for table, column in serial_tables(apps):
            cur.execute("select pg_get_serial_sequence(%s, %s)", [qn(table), column])
            sequence = cur.fetchone()[0]
            if not sequence:
                counters.append(Counter(table, None))
                continue
            cur.execute(f"select last_value, is_called from {sequence}")
            last_value, is_called = cur.fetchone()
            cur.execute(f"select max({qn(column)}) from {qn(table)}")
            counters.append(Counter(table, sequence, last_value, is_called, cur.fetchone()[0]))
    return counters


def summary(counters: list[Counter]) -> list[str]:
    """One line per table, then how many are behind."""
    lines = []
    for c in counters:
        if c.sequence is None:
            lines.append(f"{c.table}: no sequence")
            continue
        line = (
            f"{c.table}: last_value={c.last_value} is_called={c.is_called} "
            f"next={c.next_id} max(id)={c.max_id if c.max_id is not None else 'none'}"
        )
        if c.behind:
            line += f" BEHIND by {c.behind}"
        lines.append(line)
    behind = sum(1 for c in counters if c.behind)
    lines.append(f"behind: {behind} of {len(counters)} table(s)")
    return lines
