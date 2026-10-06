"""Story autism-merge 1.1: surveys and collections on التوحد move to اضطراب طيف التوحد (report #64).

Report half of `estate:AD-20`. `plan()` only reads; `describe()` renders the plan as deploy-log
lines holding ids and counts, never learner data. The apply migration that writes ships in its own
release, built from the ids this report prints. Category rows are projections that only taxonomy
events change (`estate:AD-15`), so nothing here, nor in the apply, touches them.

Arabic names live in `CategoryTranslation(language="ar")`; `Category.name` prefers English
(`taxonomy/projection.py` `_display_name`), so it is matched only as a fallback.
"""

from taxonomy.models import Category, CategoryTranslation
from taxonomy.projection import PATH_SEP

SOURCE_NAME = "التوحد"
TARGET_NAME = "اضطراب طيف التوحد"


def _named(name):
    ids = set(
        CategoryTranslation.objects.filter(language__iexact="ar", name=name).values_list("category_id", flat=True)
    )
    ids |= set(Category.objects.filter(name=name).values_list("category_id", flat=True))
    return Category.objects.filter(category_id__in=ids).order_by("tree_id", "path_text", "category_id")


def _items(category_id):
    from survey_collections.models import SurveyCollection
    from surveys.models import Survey

    return {
        "surveys": sorted(str(i) for i in Survey.objects.filter(category_id=category_id).values_list("id", flat=True)),
        "collections": sorted(
            str(i) for i in SurveyCollection.objects.filter(category_id=category_id).values_list("id", flat=True)
        ),
    }


def _row(cat):
    return {
        "id": str(cat.category_id),
        "tree_id": str(cat.tree_id),
        "path": cat.path_text,
        "tombstoned": cat.deleted_at is not None,
    }


def plan():
    """Everything the apply would need, read and never written."""
    targets = list(_named(TARGET_NAME))
    sources = []
    for cat in _named(SOURCE_NAME):
        entry = _row(cat)
        entry["items"] = _items(cat.category_id)
        entry["targets"] = [_row(t) for t in targets if t.tree_id == cat.tree_id and t.deleted_at is None]
        # A taxonomy delete takes the subtree, so children and their items are part of the plan.
        entry["children"] = []
        if cat.path_text:
            for child in Category.objects.filter(path_text__startswith=cat.path_text + PATH_SEP).order_by(
                "path_text", "category_id"
            ):
                child_row = _row(child)
                child_row["items"] = _items(child.category_id)
                entry["children"].append(child_row)
        sources.append(entry)
    return {"sources": sources, "all_targets": [_row(t) for t in targets]}


def _flag(row):
    return "tombstoned" if row["tombstoned"] else "live"


def _item_lines(prefix, items):
    return [
        f"{prefix}surveys: {len(items['surveys'])} {items['surveys']}",
        f"{prefix}collections: {len(items['collections'])} {items['collections']}",
    ]


def describe(p):
    lines = []
    lines.append(f"targets named {TARGET_NAME} (any tree): {len(p['all_targets'])}")
    for t in p["all_targets"]:
        lines.append(f"  target {t['id']} tree={t['tree_id']} path={t['path']} {_flag(t)}")
    if not p["sources"]:
        lines.append(f"no category named {SOURCE_NAME} in the projection: nothing to move")
        return lines

    moving = 0
    under_children = 0
    for s in p["sources"]:
        lines.append(f"source {s['id']} tree={s['tree_id']} path={s['path']} {_flag(s)}")
        if len(s["targets"]) == 1:
            lines.append(f"  target: {s['targets'][0]['id']}")
        elif not s["targets"]:
            lines.append("  target: NONE live in this tree (apply would refuse)")
        else:
            lines.append(f"  target: AMBIGUOUS {[t['id'] for t in s['targets']]} (apply would refuse)")
        lines.extend(_item_lines("  ", s["items"]))
        moving += len(s["items"]["surveys"]) + len(s["items"]["collections"])
        lines.append(f"  children: {len(s['children'])}")
        for c in s["children"]:
            lines.append(f"    child {c['id']} path={c['path']} {_flag(c)}")
            lines.extend(_item_lines("      ", c["items"]))
            under_children += len(c["items"]["surveys"]) + len(c["items"]["collections"])
    if under_children:
        lines.append(f"items on children of {SOURCE_NAME}: {under_children} (a taxonomy delete takes them too)")
    if moving == 0:
        lines.append(f"no survey or collection references a category named {SOURCE_NAME}: nothing to move")
    else:
        lines.append(f"items that would move: {moving}")
    return lines


# --- Apply release (estate:AD-20). The plan below is the report read from Loki on 2026-10-06
# (forms-migrate-75d668b56f, surveys.0053), saved as the undo record in
# .agent/implementation/spec-autism-merge-1-1-repoint-forms.md. The apply moves exactly these ids
# or nothing.
APPLY_SOURCE = "7878f298-ee3c-40ba-88f3-9cecfe841b14"
APPLY_TARGET = "6684c538-b347-446a-b4fe-993176be6335"
APPLY_SURVEYS = frozenset({"189", "5"})
APPLY_COLLECTIONS = frozenset({"1", "2", "3", "4", "5", "6", "7"})


class PlanMismatch(RuntimeError):
    """Live data no longer matches the reported plan; the apply writes nothing."""


def _ids(qs):
    return {str(i) for i in qs.values_list("id", flat=True)}


def _check(source, target, on_source):
    problems = []
    for label, cat in (("source", source), ("target", target)):
        if cat is None:
            problems.append(f"{label} category missing")
        elif cat.deleted_at is not None:
            problems.append(f"{label} {cat.category_id} is tombstoned")
    if source is not None and target is not None and source.tree_id != target.tree_id:
        problems.append(f"source tree {source.tree_id} != target tree {target.tree_id}")
    if source is not None and source.path_text:
        children = sorted(
            str(c)
            for c in Category.objects.filter(
                tree_id=source.tree_id, path_text__startswith=source.path_text + PATH_SEP
            ).values_list("category_id", flat=True)
        )
        if children:
            problems.append(f"source has children {children}")
    for kind, planned in (("surveys", APPLY_SURVEYS), ("collections", APPLY_COLLECTIONS)):
        live = on_source[kind]
        if live != planned:
            problems.append(
                f"{kind} on source differ from the report: extra {sorted(live - planned)} "
                f"missing {sorted(planned - live)}"
            )
    return problems


def apply(echo=print):
    """Move the reported surveys and collections from APPLY_SOURCE to APPLY_TARGET, or raise.

    Writes item rows' category only, never Category / CategoryTranslation (`estate:AD-15`). Callers
    run it inside the migration's transaction, so a raise leaves every row as it was.
    """
    from survey_collections.models import SurveyCollection
    from surveys.models import Survey

    kinds = {"surveys": Survey, "collections": SurveyCollection}
    planned = {"surveys": APPLY_SURVEYS, "collections": APPLY_COLLECTIONS}
    source = Category.objects.filter(category_id=APPLY_SOURCE).first()
    target = Category.objects.filter(category_id=APPLY_TARGET).first()

    if source is None and target is None:
        # Neither category was ever projected here (a fresh or non-prod database). Prod holds both:
        # the projection tombstones, it never deletes rows.
        echo(f"source {APPLY_SOURCE} and target {APPLY_TARGET} not in this database: nothing to move")
        echo("moved: 0")
        return 0

    on_source = {k: _ids(m.objects.filter(category_id=APPLY_SOURCE)) for k, m in kinds.items()}
    if not any(on_source.values()) and target is not None and target.deleted_at is None:
        on_target = {k: _ids(m.objects.filter(category_id=APPLY_TARGET)) for k, m in kinds.items()}
        if all(planned[k] <= on_target[k] for k in kinds):
            echo(f"already applied: every reported item is on {APPLY_TARGET} and none on {APPLY_SOURCE}")
            echo("moved: 0")
            return 0

    problems = _check(source, target, on_source)
    if problems:
        for p in problems:
            echo(f"MISMATCH {p}")
        raise PlanMismatch("autism-merge apply refused, nothing written: " + "; ".join(problems))

    moved = 0
    for kind, model in kinds.items():
        ids = sorted(planned[kind], key=int)
        n = model.objects.filter(category_id=APPLY_SOURCE, id__in=ids).update(category_id=APPLY_TARGET)
        if n != len(ids):
            raise PlanMismatch(f"autism-merge apply: {kind} moved {n}, expected {len(ids)}")
        echo(f"{kind} moved {APPLY_SOURCE} -> {APPLY_TARGET}: {n} {ids}")
        moved += n

    _republish({"survey": [int(i) for i in APPLY_SURVEYS], "collection": [int(i) for i in APPLY_COLLECTIONS]})
    echo(f"republished: surveys {len(APPLY_SURVEYS)}, collections {len(APPLY_COLLECTIONS)}")
    echo(f"moved: {moved}")
    return moved


def _republish(changed):
    # Survey and collection events carry category_id; consumers (search, orders) refresh from them.
    # Same events an admin edit emits, through the egp_only migration's republish.
    from importlib import import_module

    import_module("pricing.migrations.0005_egp_only")._republish(changed)
