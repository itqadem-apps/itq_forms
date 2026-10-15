"""Category filter that matches the selected category and its whole subtree.

A visitor picks a node from the category facet, which rolls each item up into
every ancestor, so picking a parent must return the items filed beneath it too
(report #98, F2). Descendants are found with the projection's own ancestry rule:
a descendant's `path_text` starts with its ancestor's path plus `PATH_SEP`.
"""
from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db.models import Q, QuerySet

from pkg_filters.core import BaseExactFilterHandler
from taxonomy.models import Category
from taxonomy.projection import PATH_SEP


class CategorySubtreeFilterHandler(BaseExactFilterHandler):
    def __init__(self, filter_attr: str, *, lookup: str = "category_id") -> None:
        super().__init__(filter_attr)
        self._lookup = lookup

    def apply_to_stmt(self, stmt: QuerySet, ctx: Any, value: Any) -> QuerySet:
        raw = str(value).strip()
        if not raw:
            return stmt
        try:
            category_id = uuid.UUID(raw)
        except ValueError:
            # Not a UUID: it names no category, so it matches nothing.
            return stmt.none()

        # Outside the try: a misconfigured tree id must fail loudly, not read
        # as "no such category".
        live = Category.live(tree_id=getattr(settings, "CATEGORY_TREE_ID", None) or None)
        selected = live.filter(category_id=category_id).values("tree_id", "path_text").first()
        if selected is None:
            return stmt.none()

        subtree = Q(category_id=category_id)
        if selected["path_text"]:
            subtree |= Q(path_text__startswith=selected["path_text"] + PATH_SEP)
        descendants = live.filter(subtree, tree_id=selected["tree_id"])
        return stmt.filter(**{f"{self._lookup}__in": descendants.values("category_id")})
