"""Batch `UserSurveyType.max_score` for a list resolver (`forms:AD-10`)."""

from collections.abc import Iterable, Sequence

from strawberry.types import Info
from strawberry.types.nodes import Selection, SelectedField

from user_surveys.models import UserSurvey
from user_surveys.services import max_scores


def _selects(selections: Sequence[Selection], path: tuple[str, ...]) -> bool:
    if not path:
        return True
    for selection in selections:
        if not isinstance(selection, SelectedField):  # a fragment: its fields sit at this level
            if _selects(selection.selections, path):
                return True
        elif selection.name == path[0] and _selects(selection.selections, path[1:]):
            return True
    return False


def prime_max_scores(items: Iterable[UserSurvey], info: Info, path: tuple[str, ...]) -> None:
    """When the request selects `maxScore` at `path` under the resolver's own field, compute it
    for every scored attempt in one batch; `UserSurveyType.max_score` reads the primed value.
    Attempts with scoring off are skipped: their field is null anyway."""
    if not any(_selects(field.selections, path) for field in info.selected_fields):
        return
    scored = [us for us in items if us.use_score]
    totals = max_scores(scored)
    for us in scored:
        us._primed_max_score = totals[us.id]
