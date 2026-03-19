"""Shared facet utilities for building category tree facets from querysets."""
from __future__ import annotations

from typing import List

from django.db.models import Count, QuerySet

from app.schema_common import CategoryFacetNodeGQL, CategoryTranslationFacetGQL
from taxonomy.models import Category


def build_category_tree_facet(base_qs: QuerySet, category_fk: str = "category_id") -> List[CategoryFacetNodeGQL]:
    """
    Build a nested category tree with item counts from a filtered queryset.

    Returns ALL categories. Categories with no matching items get count=0.
    """
    # 1. Count items per category from the filtered queryset
    counts_qs = (
        base_qs.filter(**{f"{category_fk}__isnull": False})
        .values(category_fk)
        .annotate(count=Count("id"))
    )
    count_map = {str(row[category_fk]): row["count"] for row in counts_qs}

    # 2. Fetch ALL categories with translations
    categories = Category.objects.all().prefetch_related("translations")

    # 3. Build nodes (count=0 for categories without items)
    nodes: dict[str, CategoryFacetNodeGQL] = {}
    for cat in categories:
        cat_id = str(cat.category_id)
        nodes[cat_id] = CategoryFacetNodeGQL(
            id=cat_id,
            name=cat.name,
            count=count_map.get(cat_id, 0),
            path_text=cat.path_text,
            translations=[
                CategoryTranslationFacetGQL(
                    language=t.language,
                    name=t.name,
                    slug=t.slug,
                )
                for t in cat.translations.all()
            ],
            children=[],
        )

    # 4. Reconstruct tree from path_text
    path_to_node: dict[str, CategoryFacetNodeGQL] = {}
    for node in nodes.values():
        if node.path_text:
            path_to_node[node.path_text] = node

    roots: list[CategoryFacetNodeGQL] = []
    for node in nodes.values():
        if not node.path_text:
            roots.append(node)
            continue

        sep = " / "
        if sep in node.path_text:
            parent_path = node.path_text.rsplit(sep, 1)[0]
            parent = path_to_node.get(parent_path)
            if parent is not None:
                parent.children.append(node)
                parent.count += node.count
                _bubble_count(path_to_node, parent_path, node.count, sep)
                continue

        roots.append(node)

    return roots


def _bubble_count(
    path_to_node: dict[str, CategoryFacetNodeGQL],
    path: str,
    count: int,
    sep: str,
) -> None:
    """Walk up the path, adding count to each ancestor that exists in our map."""
    while sep in path:
        path = path.rsplit(sep, 1)[0]
        ancestor = path_to_node.get(path)
        if ancestor is not None:
            ancestor.count += count