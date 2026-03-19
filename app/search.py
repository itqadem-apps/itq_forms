"""
Postgres full-text search + trigram fuzzy matching handler for pkg_filters pipelines.

Replaces DjangoSearchFilterHandler (icontains) with:
- SearchVector + SearchQuery for ranked full-text search (stemming, phrases)
- TrigramWordSimilarity as fallback for typo tolerance
- Results annotated with `search_rank` for optional ordering
"""
from __future__ import annotations

from typing import Any, Sequence

from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramWordSimilarity,
)
from django.db.models import Q, QuerySet, Value

from pkg_filters.core import BaseExactFilterHandler
from pkg_filters.integrations.django import DjangoQueryContext


class PostgresSearchHandler(BaseExactFilterHandler):
    """
    Full-text search + trigram similarity for Django + Postgres.

    Usage in a pipeline:
        PostgresSearchHandler(
            "q",
            fields=("translations__title", "translations__description"),
            weights=("A", "B"),
            config="simple",
            trigram_field="translations__title",
            rank_threshold=0.01,
            similarity_threshold=0.3,
        )

    The handler:
    1. Builds a SearchVector across `fields` with optional per-field weights.
    2. Runs a SearchQuery with `search_type="websearch"` (supports AND, OR, "phrases").
    3. Annotates with SearchRank.
    4. If `trigram_field` is set, also annotates with TrigramWordSimilarity.
    5. Filters rows where rank >= threshold OR similarity >= threshold.
    6. Orders by rank desc (higher relevance first).
    """

    skip_on_count: bool = False

    def __init__(
        self,
        filter_attr: str,
        *,
        fields: Sequence[str],
        weights: Sequence[str] | None = None,
        config: str = "simple",
        trigram_field: str | None = None,
        rank_threshold: float = 0.01,
        similarity_threshold: float = 0.3,
        min_len: int = 1,
    ) -> None:
        super().__init__(filter_attr)
        self._fields = tuple(fields)
        self._weights = tuple(weights) if weights else tuple("A" for _ in fields)
        self._config = config
        self._trigram_field = trigram_field
        self._rank_threshold = rank_threshold
        self._similarity_threshold = similarity_threshold
        self._min_len = min_len

    def apply_to_stmt(self, stmt: QuerySet, ctx: Any, value: Any) -> QuerySet:
        if value is None:
            return stmt
        term = str(value).strip()
        if len(term) < self._min_len:
            return stmt

        # Build search vector with weights
        vectors = []
        for field, weight in zip(self._fields, self._weights):
            vectors.append(SearchVector(field, weight=weight, config=self._config))

        vector = vectors[0]
        for v in vectors[1:]:
            vector = vector + v

        query = SearchQuery(term, search_type="websearch", config=self._config)

        stmt = stmt.annotate(
            search_rank=SearchRank(vector, query),
        )

        # Build filter: full-text match OR trigram similarity
        filter_q = Q(search_rank__gte=self._rank_threshold)

        if self._trigram_field:
            stmt = stmt.annotate(
                search_similarity=TrigramWordSimilarity(Value(term), self._trigram_field),
            )
            filter_q = filter_q | Q(search_similarity__gte=self._similarity_threshold)

        return stmt.filter(filter_q).order_by("-search_rank")
