"""Decide, for every legacy row, which target row it *is* -- or that it is new.

The previous importer assumed a legacy id and a target id were the same thing.
They are not, in three separate ways, all of them observed in the live data:

  * `blogs_blog` was renumbered on the way in. Target collection 8 is legacy
    blog 25. Matching collections by id would overwrite thirteen unrelated rows.
  * Genuine 2026 rows sit on ids the legacy database also uses. Questions
    3080-3082 were created this year inside imported survey 155; legacy uses
    those ids for surveys 2 and 162.
  * Rows exist in legacy that were never loaded at all -- 4,587 recommendations,
    13 surveys, 57 collections -- because the export the old importer read had
    already dropped everything soft-deleted.

So identity is established by a *witness* that the importer could not have
forged, not by the id:

  id + created_at (to the millisecond -- the target column lost the microseconds)
      surveys, sections, questions, classifications, recommendations
  id + the parent chain              schemas, options, actions
      these tables carry no timestamp
  created_at alone                   collections
      their ids were not preserved, so the id cannot witness anything

A legacy row whose id is taken by a target row that fails the witness test is a
COLLISION: the target row belongs to somebody else and the legacy row needs a
fresh id, recorded in the id map so its children can follow it.
"""

from dataclasses import dataclass
from enum import Enum


class Mode(Enum):
    UPDATE = "update"   # this legacy row is already in the target; refresh it in place
    INSERT = "insert"   # not present; write it, keeping the legacy id
    REMAP = "remap"     # not present, and its id is taken; write it under a new id


@dataclass
class Resolution:
    table: str
    mapping: dict          # legacy_id -> target_id
    mode: dict             # legacy_id -> Mode

    @property
    def counts(self):
        c = {m: 0 for m in Mode}
        for m in self.mode.values():
            c[m] += 1
        return c


def _ms(ts):
    """Truncate to milliseconds -- the target stores no finer than that."""
    if ts is None:
        return None
    return ts.replace(microsecond=(ts.microsecond // 1000) * 1000)


def resolve(name, legacy_rows, target_rows, next_id):
    """legacy_rows / target_rows: {id: witness}. Returns a Resolution.

    `next_id` is called for each collision and must return an unused target id.
    """
    mapping, mode = {}, {}
    for lid, witness in legacy_rows.items():
        if lid in target_rows:
            if target_rows[lid] == witness:
                mapping[lid], mode[lid] = lid, Mode.UPDATE
            else:
                mapping[lid], mode[lid] = next_id(), Mode.REMAP
        else:
            mapping[lid], mode[lid] = lid, Mode.INSERT
    return Resolution(name, mapping, mode)


def resolve_by_witness(name, legacy_rows, target_rows, next_id):
    """For tables whose ids were NOT preserved. Match on the witness alone.

    Refuses to guess when a witness is ambiguous: if two target rows share one,
    there is no fact that distinguishes them and the loader must not pick.
    """
    index = {}
    for tid, witness in target_rows.items():
        index.setdefault(witness, []).append(tid)
    ambiguous = {w: ids for w, ids in index.items() if len(ids) > 1}
    if ambiguous:
        raise SystemExit(
            f"{name}: {len(ambiguous)} witness value(s) match more than one target row "
            f"-- cannot decide which is which: {list(ambiguous.items())[:5]}"
        )
    mapping, mode = {}, {}
    for lid, witness in legacy_rows.items():
        hit = index.get(witness)
        if hit:
            mapping[lid], mode[lid] = hit[0], Mode.UPDATE
        else:
            mapping[lid], mode[lid] = next_id(), Mode.REMAP
    return Resolution(name, mapping, mode)
