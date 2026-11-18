"""Find the collection memberships that break the collection rules, remove the non-curriculum
ones, and refuse new ones (intake report #128, stories curricula-order 2.1, 2.2 and 2.3).

A collection should hold only curricula (`survey_type` "curriculum"), and a curriculum should be
in at most one collection. A membership breaks the first rule when its survey is not a
curriculum; a curriculum breaks the second when it is linked to more than one collection.

Each count is taken twice: over every link ("all"), and over the links shown today ("shown":
the collection and the survey both have `deleted_at` null).

`find()` reads only; the report ships as migration 0017 (writes nothing). `apply()` deletes the
memberships that break the first rule, selected by the same test (story 2.3, migration 0018).
"Shown" tests `deleted_at` only, not publication status.

The rules bind curriculum collections only. A course collection (one with an `ExternalReference`
whose `source_service` is "courses", whatever its `type`) holds its course's exams by design, so
none of its memberships is counted, removed or refused (ruling "Curricula only, and restore the
5 links", 2026-11-18). `refusal()` is the add-path check `addSurveyToCollection` calls.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

CURRICULUM = "curriculum"
SCOPES = ("all", "shown")
NO_TYPE = "(no type)"
IDS_PER_LINE = 200
NOT_CURRICULUM_REFUSAL = "Only curricula can be added to a collection."
SHARED_CURRICULUM_REFUSAL = "This curriculum is already in another collection."


def _not_curriculum(survey_type: str) -> bool:
    return survey_type != CURRICULUM


def _label(survey_type: str) -> str:
    return survey_type or NO_TYPE


def _model(membership_model):
    if membership_model is None:
        from survey_collections.models import CollectionMembership as membership_model
    return membership_model


def _course_references(reference_model=None):
    # Imported here: courses.py loads models at import, and migrations import this module.
    from external_references.courses import SOURCE_SERVICE

    if reference_model is None:
        from external_references.models import ExternalReference as reference_model
    return reference_model._base_manager.filter(source_service=SOURCE_SERVICE, collection__isnull=False)


def course_collection_ids(reference_model=None) -> set[int]:
    """Ids of the course collections, the ones the rules never apply to. A migration passes its
    historical `ExternalReference`."""
    return set(_course_references(reference_model).values_list("collection_id", flat=True))


def refusal(collection, survey) -> str | None:
    """Why adding `survey` to `collection` breaks the rules, or None when it may be added. An
    existing member is never refused, so re-adding stays the no-op `append_member` makes it. A
    curriculum's links to soft-deleted or course collections do not count: the admin cannot see
    or fix those."""
    from survey_collections.models import CollectionMembership

    courses = _course_references()
    if courses.filter(collection=collection).exists():
        return None
    memberships = CollectionMembership._base_manager
    if memberships.filter(surveycollection=collection, survey=survey).exists():
        return None
    if _not_curriculum(survey.survey_type):
        return NOT_CURRICULUM_REFUSAL
    elsewhere = (
        memberships.filter(survey=survey, surveycollection__deleted_at__isnull=True)
        .exclude(surveycollection=collection)
        .exclude(surveycollection_id__in=courses.values("collection_id"))
    )
    if elsewhere.exists():
        return SHARED_CURRICULUM_REFUSAL
    return None


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


def find(membership_model=None, reference_model=None) -> Found:
    """Every rule-breaking membership outside course collections, over all links and over the shown
    ones; read, never written.

    A migration passes its historical `CollectionMembership` and `ExternalReference` so a later
    model change cannot break it.
    """
    courses = course_collection_ids(reference_model)
    rows = _model(membership_model)._base_manager.values_list(
        "surveycollection_id", "survey_id", "survey__survey_type", "surveycollection__deleted_at", "survey__deleted_at"
    )
    # unique_together(surveycollection, survey) makes each row a distinct collection for its survey.
    every, shown = _Tally(), _Tally()
    for collection_id, survey_id, survey_type, collection_deleted, survey_deleted in rows.iterator():
        if collection_id in courses:
            continue
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


def find_not_curricula(membership_model=None, reference_model=None) -> list[Breaker]:
    """Every membership whose survey is not a curriculum, outside course collections, over every
    link (deleted collections or surveys included), ordered by collection then survey; read, never
    written."""
    courses = course_collection_ids(reference_model)
    rows = _model(membership_model)._base_manager.values_list(
        "pk", "surveycollection_id", "survey_id", "order", "survey__survey_type"
    ).order_by("surveycollection_id", "survey_id")
    return [Breaker(*row) for row in rows.iterator() if _not_curriculum(row[4]) and row[1] not in courses]


def apply(membership_model=None, reference_model=None) -> list[str]:
    """Delete every membership whose survey is not a curriculum outside course collections,
    re-checked now, and return the log lines: one
    `removed: collection <cid> survey <sid> order <n> (<type>)` per link, then the removed total and
    one line per survey type. Only membership rows are deleted; surveys, collections and the
    curricula memberships (with their order) are untouched. Raises on a count mismatch so the
    caller's transaction rolls back."""
    model = _model(membership_model)
    breakers = find_not_curricula(model, reference_model)
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
