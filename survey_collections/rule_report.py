"""Find the collection memberships that break the collection rules (intake report #128, story
curricula-order 2.1).

A collection should hold only curricula (`survey_type` "curriculum"), and a curriculum should be
in at most one collection. A membership breaks the first rule when its survey is not a
curriculum; a curriculum breaks the second when it is linked to more than one collection.

Each count is taken twice: over every link ("all"), and over the links shown today ("shown":
the collection and the survey both have `deleted_at` null).

Reads only. The report ships as migration 0017 (writes nothing); a later apply should select by
the same rule. "Shown" tests `deleted_at` only, not publication status.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

CURRICULUM = "curriculum"
SCOPES = ("all", "shown")
NO_TYPE = "(no type)"
IDS_PER_LINE = 200


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
        if survey_type == CURRICULUM:
            self.collections_per_curriculum[survey_id] += 1
        else:
            self.types[survey_type or NO_TYPE] += 1

    def scope(self) -> Scope:
        return Scope(
            not_curricula=dict(self.types),
            shared_curricula=sorted(pk for pk, n in self.collections_per_curriculum.items() if n > 1),
        )


def find(membership_model=None) -> Found:
    """Every rule-breaking membership, over all links and over the shown ones; read, never written.

    A migration passes its historical `CollectionMembership` so a later model change cannot break it.
    """
    if membership_model is None:
        from survey_collections.models import CollectionMembership as membership_model

    rows = membership_model._base_manager.values_list(
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
