"""Ordering by publication state.

`status` is a CharField, so ordering by the column itself is alphabetical —
`archived, draft, pending, published, suspended` — which is meaningless to a
human reading a listing. Admin screens want the rows they can act on first, so
the sort inputs expose `status` and this module is what it actually orders by:
a rank annotation over the shared vocabulary, ascending = published first.

Both `Survey` and `SurveyCollection` declare the same five values, so one rank
serves both listings.
"""

from django.db.models import Case, IntegerField, QuerySet, Value, When

#: Publication states, most to least prominent. Ascending rank = published first.
STATUS_SORT_ORDER = ("published", "pending", "draft", "suspended", "archived")

#: The annotation name the sort maps point at.
STATUS_RANK_FIELD = "status_rank"


def annotate_status_rank(qs: QuerySet) -> QuerySet:
    """Add the ``status_rank`` annotation the ``status`` sort orders by.

    Anything outside the vocabulary sorts last rather than raising — a row in a
    state this list has not caught up with should fall to the bottom of a
    listing, not break the query.
    """
    return qs.annotate(
        **{
            STATUS_RANK_FIELD: Case(
                *(
                    When(status=status, then=Value(rank))
                    for rank, status in enumerate(STATUS_SORT_ORDER)
                ),
                default=Value(len(STATUS_SORT_ORDER)),
                output_field=IntegerField(),
            )
        }
    )
