"""Find the collection memberships that break the collection rules, and remove the non-curriculum
ones (intake report #128, stories curricula-order 2.1 and 2.3).

A collection should hold only curricula (`survey_type` "curriculum"), and a curriculum should be
in at most one collection. A membership breaks the first rule when its survey is not a
curriculum; a curriculum breaks the second when it is linked to more than one collection.

Each count is taken twice: over every link ("all"), and over the links shown today ("shown":
the collection and the survey both have `deleted_at` null).

`find()` reads only; the report ships as migration 0017 (writes nothing). `apply()` deletes the
memberships that break the first rule, selected by the same test (story 2.3, migration 0018).
"Shown" tests `deleted_at` only, not publication status.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

CURRICULUM = "curriculum"
SCOPES = ("all", "shown")
NO_TYPE = "(no type)"
IDS_PER_LINE = 200


def _not_curriculum(survey_type: str) -> bool:
    return survey_type != CURRICULUM


def _label(survey_type: str) -> str:
    return survey_type or NO_TYPE


def _model(membership_model):
    if membership_model is None:
        from survey_collections.models import CollectionMembership as membership_model
    return membership_model


@dataclass
class Scope:
    # survey_type -> number of non-curriculum links, for every type that has one
    not_curricula: dict[str, int] = field(default_factory=dict)
    # ids of curricula linked to more than one collection, ascending
    shared_curricula: list[int] = field(default_factory=list)


@dataclass
class Found:
    all: Scope
    shown: Scope


class _Tally:
    def __init__(self):
        self.types: Counter[str] = Counter()
        self.collections_per_curriculum: Counter[int] = Counter()

    def add(self, survey_id: int, survey_type: str) -> None:
        if _not_curriculum(survey_type):
            self.types[_label(survey_type)] += 1
        else:
            self.collections_per_curriculum[survey_id] += 1

    def scope(self) -> Scope:
        return Scope(
            not_curricula=dict(self.types),
            shared_curricula=sorted(pk for pk, n in self.collections_per_curriculum.items() if n > 1),
        )


def find(membership_model=None) -> Found:
    """Every rule-breaking membership, over all links and over the shown ones; read, never written.

    A migration passes its historical `CollectionMembership` so a later model change cannot break it.
    """
    rows = _model(membership_model)._base_manager.values_list(
        "survey_id", "survey__survey_type", "surveycollection__deleted_at", "survey__deleted_at"
    )
    # unique_together(surveycollection, survey) makes each row a distinct collection for its survey.
    every, shown = _Tally(), _Tally()
    for survey_id, survey_type, collection_deleted, survey_deleted in rows.iterator():
        every.add(survey_id, survey_type)
        if collection_deleted is None and survey_deleted is None:
            shown.add(survey_id, survey_type)
    return Found(all=every.scope(), shown=shown.scope())


def summary(found: Found) -> list[str]:
    """The report as log lines, each scope in turn: the non-curriculum total, one line per survey
    type, then the shared-curricula count and their ids."""
    lines = []
    for name in SCOPES:
        scope: Scope = getattr(found, name)
        lines.append(f"{name}: not curricula: {sum(scope.not_curricula.values())}")
        for survey_type in sorted(scope.not_curricula, key=str):
            lines.append(f"{name}: {survey_type}: {scope.not_curricula[survey_type]}")
        lines.append(f"{name}: curricula in more than one collection: {len(scope.shared_curricula)}")
        # Chunked so no single log line outgrows Loki's line limit.
        ids = scope.shared_curricula
        for start in range(0, len(ids), IDS_PER_LINE):
            lines.append(f"{name}: shared curricula ids: {', '.join(map(str, ids[start:start + IDS_PER_LINE]))}")
    return lines


@dataclass(frozen=True)
class Breaker:
    pk: int
    collection_id: int
    survey_id: int
    order: int
    survey_type: str


def find_not_curricula(membership_model=None) -> list[Breaker]:
    """Every membership whose survey is not a curriculum, over every link (deleted collections or
    surveys included), ordered by collection then survey; read, never written."""
    rows = _model(membership_model)._base_manager.values_list(
        "pk", "surveycollection_id", "survey_id", "order", "survey__survey_type"
    ).order_by("surveycollection_id", "survey_id")
    return [Breaker(*row) for row in rows.iterator() if _not_curriculum(row[4])]


def apply(membership_model=None) -> list[str]:
    """Delete every membership whose survey is not a curriculum, re-checked now, and return the log
    lines: one `removed: collection <cid> survey <sid> order <n> (<type>)` per link, then the removed total
    and one line per survey type. Only membership rows are deleted; surveys, collections and the
    curricula memberships (with their order) are untouched. Raises on a count mismatch so the
    caller's transaction rolls back."""
    model = _model(membership_model)
    breakers = find_not_curricula(model)
    lines = [
        f"removed: collection {b.collection_id} survey {b.survey_id} order {b.order} ({_label(b.survey_type)})" for b in breakers
    ]
    pks = [b.pk for b in breakers]
    deleted, per_model = model._base_manager.filter(pk__in=pks).delete()
    removed = per_model.get(model._meta.label, 0)
    if removed != len(pks):
        raise RuntimeError(f"collection-rules: removed {removed} memberships, expected {len(pks)}")
    if deleted != removed:
        raise RuntimeError(f"collection-rules: deleted {deleted} rows for {removed} memberships, expected no cascade")
    lines.append(f"removed: {removed}")
    types = Counter(_label(b.survey_type) for b in breakers)
    for survey_type in sorted(types, key=str):
        lines.append(f"removed: {survey_type}: {types[survey_type]}")
    return lines
