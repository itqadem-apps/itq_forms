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
