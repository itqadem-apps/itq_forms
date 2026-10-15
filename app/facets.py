"""Shared facet utilities for building category tree and price range facets."""
from __future__ import annotations

import math
from typing import List, Optional

from django.conf import settings
from django.db.models import Count, Max, Min, QuerySet

from app.price_filter import CENTS_PER_UNIT
from app.schema_common import CategoryFacetNodeGQL, CategoryTranslationFacetGQL, PriceRangeFacetGQL
from taxonomy.models import Category
from taxonomy.projection import PATH_SEP


def build_price_range_facet(
    base_qs: QuerySet,
    currency: Optional[str],
    price_relation: str = "prices",
) -> PriceRangeFacetGQL:
    """
    Compute the min/max price, in EGP, of the prices related to the filtered queryset.

    The bounds are what a visitor types into the price filter, so they share its
    unit. min is floored and max ceiled so the range covers every listed price.

    Args:
        base_qs: The already-filtered queryset (Survey, SurveyCollection, etc.)
        currency: Currency code from X-Currency header. If None, uses all prices.
        price_relation: The related name for prices on the model.
    """
    lookup = {f"{price_relation}__amount_cents__isnull": False}
    if currency:
        lookup[f"{price_relation}__currency"] = currency

    agg = _listed_items(base_qs).filter(**lookup).aggregate(
        min_price=Min(f"{price_relation}__amount_cents"),
        max_price=Max(f"{price_relation}__amount_cents"),
    )
    return PriceRangeFacetGQL(
        min=math.floor((agg["min_price"] or 0) / CENTS_PER_UNIT),
        max=math.ceil((agg["max_price"] or 0) / CENTS_PER_UNIT),
    )


def build_category_tree_facet(base_qs: QuerySet, category_fk: str = "category_id") -> List[CategoryFacetNodeGQL]:
    """
    Build a nested category tree with item counts from a filtered queryset.

    Returns every live category of the projected tree. Categories with no
    matching items get count=0.
    """
    # 1. Count items per category from the filtered queryset, one row per item.
    counts_qs = (
        _listed_items(base_qs)
        .filter(**{f"{category_fk}__isnull": False})
        .values(category_fk)
        .annotate(count=Count("pk"))
    )
    count_map = {str(row[category_fk]): row["count"] for row in counts_qs}

    # 2. Fetch every live category of the projected tree, with translations.
    #    Tombstoned rows are excluded: a deleted category must stop appearing in
    #    facets even though its row survives as the projection's watermark.
    categories = Category.live(
        tree_id=getattr(settings, "CATEGORY_TREE_ID", None) or None
    ).prefetch_related("translations")

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

    # Taxonomy joins ancestry with dots, not " / ". Each category's own count
    # (from count_map, never a node's running total) is added to every
    # ancestor once, so the result does not depend on the read order.
    roots: list[CategoryFacetNodeGQL] = []
    for node in nodes.values():
        # Attach under the nearest live ancestor, so a category whose direct
        # parent is gone still sits under the node its count is rolled into.
        parent = _nearest_ancestor(path_to_node, node.path_text)
        if parent is not None:
            parent.children.append(node)
            own = count_map.get(node.id, 0)
            if own:
                _bubble_count(path_to_node, node.path_text, own, PATH_SEP)
        else:
            roots.append(node)

    return roots


def _listed_items(base_qs: QuerySet) -> QuerySet:
    """The listed items as a plain queryset, one row per item.

    `base_qs` may carry joins, ordering and search's per-item aggregates; a
    facet that groups or filters it directly would regroup those. Selecting by
    primary key leaves only the set of items.
    """
    return base_qs.model._base_manager.filter(pk__in=base_qs.order_by().values("pk"))


def _nearest_ancestor(
    path_to_node: dict[str, CategoryFacetNodeGQL], path: str | None
) -> CategoryFacetNodeGQL | None:
    while path and PATH_SEP in path:
        path = path.rsplit(PATH_SEP, 1)[0]
        ancestor = path_to_node.get(path)
        if ancestor is not None:
            return ancestor
    return None


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