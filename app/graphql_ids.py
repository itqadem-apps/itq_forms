"""Ids on the wire.

Every model pk this service exposes comes back as GraphQL ``ID`` — a string —
because ``id: auto`` on a strawberry-django type maps that way. The mutations
and queries, meanwhile, used to declare their id arguments as ``Int!``, so a
client that read an id from us and handed it straight back was rejected every
time. ``UserSurveyType.id`` is one of the few declared ``int``, which is why
``answerQuestion`` accepted ``userSurveyId`` and refused ``questionId`` in the
same request, and why the mismatch went unnoticed for as long as it did.

Arguments now take ``ID``. That is backward compatible in both directions:
``ID`` coerces integer literals as well as strings, so callers already passing
numbers are unaffected, and callers passing the id we gave them finally work.
The output types are untouched — changing those would break every client that
stores ids as strings.

Resolvers still want a real ``int`` for ORM lookups and comparisons, so they
run the argument through :func:`as_pk` before using it.
"""

from typing import Optional, Union

import strawberry
from django.core.exceptions import ValidationError


def as_pk(value: Union[strawberry.ID, int, str, None]) -> Optional[int]:
    """Coerce an ``ID`` argument to the integer pk it names.

    ``None`` passes through so optional arguments stay optional. Anything that
    is not a whole number is a client error, not a lookup miss — surfacing it
    as one keeps a typo from being reported as "not found".
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Invalid id: {value!r}")
