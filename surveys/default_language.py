"""Sort the translations an old import saved under the language "default" (intake report #132,
stories default-language-translations 1.1 and 1.2).

The admin Build page reads only a real language, so classification names, recommendation texts and
action titles and descriptions labelled "default" show as empty boxes. Story 1.2 relabels them to
their survey's primary language; this module decides, for every "default" row of the three tables,
which one bucket it falls in, checked in this order:

- **parent deleted**: the classification or recommendation has `deleted_at` set (actions have no
  soft delete);
- **no survey**: the parent has no survey (a recommendation falls back to its option's survey);
- **no primary language**: the survey's `primary_language` column is null or empty, as stored
  (`Survey.PRIMARY_LANGUAGE_FALLBACK` is "default" itself, so it is never substituted). The column is
  stripped, and one reading "default" in any case names no language either;
- **clash**: the parent already has a row in the primary language, split by whether that row has
  text (blank = every text field null or empty once HTML tags and whitespace are removed);
- **relabellable**: everything else, grouped by the primary language it would take.

Reads only. The report ships as surveys migration 0061 (writes nothing); story 1.2's apply reuses
`find_default_rows` so the number it relabels is the number reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from recommendations.empty_cleanup import is_blank

DEFAULT = "default"

PARENT_DELETED = "parent deleted"
NO_SURVEY = "no survey"
NO_PRIMARY_LANGUAGE = "no primary language"
CLASH_WITH_TEXT = "clash, primary row has text"
CLASH_BLANK = "clash, primary row blank"
RELABELLABLE = "relabellable"
BUCKETS = (PARENT_DELETED, NO_SURVEY, NO_PRIMARY_LANGUAGE, CLASH_WITH_TEXT, CLASH_BLANK, RELABELLABLE)


@dataclass
class TableFound:
    table: str
    # bucket -> ids of the "default" rows in it, sorted
    buckets: dict[str, list[UUID]] = field(default_factory=lambda: {b: [] for b in BUCKETS})
    # primary language -> ids of the relabellable rows that would take it, sorted
    relabellable_by_language: dict[str, list[UUID]] = field(default_factory=dict)
    # Informational, not buckets (they do not change the total):
    # relabellable ids whose survey, or the option it was reached through, is soft-deleted
    survey_deleted: list[UUID] = field(default_factory=list)
    # relabellable ids whose own "default" row is blank in every text field
    default_blank: list[UUID] = field(default_factory=list)
    # rows labelled a variant of "default" (other case or padded), counted in no bucket
    variants: int = 0

    @property
    def total(self) -> int:
        return sum(len(ids) for ids in self.buckets.values())


@dataclass
class _Spec:
    table: str
    translation: str  # "app_label.Model"
    parent_fk: str
    text_fields: tuple[str, ...]
    soft_delete: bool
    # (path to the parent's survey, soft-deletable hop on the way or None); first non-null wins
    survey_paths: tuple[tuple[str, str | None], ...]


SPECS = (
    _Spec("classification translations", "classifications.ClassificationTranslation", "classification",
          ("name",), True, (("survey", None),)),
    _Spec("recommendation translations", "recommendations.RecommendationTranslation", "recommendation",
          ("description",), True, (("survey", None), ("option__survey", "option"))),
    _Spec("action translations", "recommendations.ActionTranslation", "action",
          ("title", "description"), False, (("survey", None),)),
)

# The buckets a human must rule on; the report lists their ids.
RULING_BUCKETS = (NO_SURVEY, NO_PRIMARY_LANGUAGE, CLASH_WITH_TEXT)
MAX_IDS = 50


def _primary(language: str | None) -> str | None:
    language = (language or "").strip()
    if not language or language.lower() == DEFAULT:
        return None
    return language


def _find_table(spec: _Spec) -> TableFound:
    from django.apps import apps

    model = apps.get_model(spec.translation)
    p = spec.parent_fk
    cols = ["id", f"{p}_id", *spec.text_fields] + ([f"{p}__deleted_at"] if spec.soft_delete else [])
    for path, hop in spec.survey_paths:
        cols += [f"{p}__{path}_id", f"{p}__{path}__primary_language", f"{p}__{path}__deleted_at",
                 f"{p}__{hop}__deleted_at" if hop else f"{p}__{path}__deleted_at"]

    found = TableFound(spec.table)
    found.variants = (
        model._base_manager.filter(language__iregex=r"^\s*default\s*$").exclude(language=DEFAULT).count()
    )
    pending: list[tuple[UUID, int, str, bool, bool]] = []  # (row, parent, language, deleted, blank)
    n_text = len(spec.text_fields)
    for values in model._base_manager.filter(language=DEFAULT).order_by("id").values_list(*cols):
        pk, parent_id, *rest = values
        texts, rest = rest[:n_text], rest[n_text:]
        deleted_at = rest.pop(0) if spec.soft_delete else None
        survey = next((rest[i : i + 4] for i in range(0, len(rest), 4) if rest[i] is not None), None)
        if deleted_at is not None:
            found.buckets[PARENT_DELETED].append(pk)
        elif survey is None:
            found.buckets[NO_SURVEY].append(pk)
        elif (language := _primary(survey[1])) is None:
            found.buckets[NO_PRIMARY_LANGUAGE].append(pk)
        else:
            gone = survey[2] is not None or survey[3] is not None
            pending.append((pk, parent_id, language, gone, all(is_blank(t) for t in texts)))

    primary_rows: dict[tuple[int, str], bool] = {}
    if pending:
        others = model._base_manager.filter(
            **{f"{p}_id__in": {row[1] for row in pending}},
            language__in={row[2] for row in pending},
        )
        for parent_id, language, *texts in others.values_list(f"{p}_id", "language", *spec.text_fields):
            primary_rows[(parent_id, language)] = not all(is_blank(t) for t in texts)

    for pk, parent_id, language, gone, blank in pending:
        has_text = primary_rows.get((parent_id, language))
        if has_text is None:
            found.buckets[RELABELLABLE].append(pk)
            found.relabellable_by_language.setdefault(language, []).append(pk)
            if gone:
                found.survey_deleted.append(pk)
            if blank:
                found.default_blank.append(pk)
        else:
            found.buckets[CLASH_WITH_TEXT if has_text else CLASH_BLANK].append(pk)
    return found


def find_default_rows() -> list[TableFound]:
    """Every "default" row of the three translation tables in exactly one bucket, read and never
    written."""
    return [_find_table(spec) for spec in SPECS]


def _ids(ids: list[UUID]) -> str:
    shown = ", ".join(str(i) for i in ids[:MAX_IDS])
    return shown + (", …" if len(ids) > MAX_IDS else "")


def summary(found: list[TableFound]) -> list[str]:
    """The report as log lines: per table, the total, each bucket's count, the ids of the buckets
    that need a ruling, the relabellable count per primary language, then the informational
    counts."""
    lines: list[str] = []
    for t in found:
        lines.append(f"{t.table}: {t.total} labelled \"default\"")
        for bucket in BUCKETS:
            ids = t.buckets[bucket]
            lines.append(f"{t.table}: {bucket}: {len(ids)}")
            if bucket in RULING_BUCKETS and ids:
                lines.append(f"{t.table}: {bucket} ids: {_ids(ids)}")
        lines.extend(
            f"{t.table}: relabellable to {language}: {len(ids)}"
            for language, ids in sorted(t.relabellable_by_language.items())
        )
        lines.append(f"{t.table}: relabellable but the survey or option is deleted: {len(t.survey_deleted)}")
        lines.append(f"{t.table}: relabellable but the default text itself is blank: {len(t.default_blank)}")
        lines.append(f"{t.table}: labelled a \"default\" variant (other case or spaces), not counted above: {t.variants}")
    return lines
