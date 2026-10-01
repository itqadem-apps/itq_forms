"""A survey's time limit must survive the trip from the admin's minutes field.

`Survey.time_limit` is a DurationField, which GraphQL has no scalar for, so
`SurveyCreateInput`/`SurveyUpdateInput` declare it as a `"H:MM:SS"` string and
the resolver is the only place that can turn it back into a duration. Nothing
did: the string was assigned straight to the column, which Postgres casts for
itself and sqlite does not, and an unparseable value became a database error
instead of a field error. These tests pin the coercion rather than the cast.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError

from surveys.schemas.utils import coerce_duration


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0:30:00", datetime.timedelta(minutes=30)),
        ("01:00:00", datetime.timedelta(hours=1)),
        ("1:30:00", datetime.timedelta(minutes=90)),
        # What the admin's minutes field sends for "no limit", and what clearing
        # the switch sends: both must reach the column as NULL, not as 0.
        ("", None),
        (None, None),
        # Already a duration — the create path hands model defaults straight through.
        (datetime.timedelta(minutes=5), datetime.timedelta(minutes=5)),
    ],
)
def test_coerce_duration_accepts_what_the_admin_sends(value, expected):
    assert coerce_duration(value) == expected


def test_coerce_duration_rejects_a_typo_as_a_field_error():
    """A bad value must surface as `OperationInfo` the rail can toast, not as a
    cast failure deep in the driver — the admin has to be told which field."""
    with pytest.raises(ValidationError) as excinfo:
        coerce_duration("thirty minutes")
    assert "time_limit" in excinfo.value.message_dict


def test_time_limit_round_trips_through_the_column(survey):
    """The solver reads the column back as `"H:MM:SS"` and parses it
    (`useSolveTimer.parseDuration`), so the stored value has to be a real
    interval — storing the string would read back unchanged on Postgres and
    fail outright on sqlite."""
    survey.time_limit = coerce_duration("0:45:00")
    survey.save(update_fields=["time_limit"])
    survey.refresh_from_db()
    assert survey.time_limit == datetime.timedelta(minutes=45)
    assert str(survey.time_limit) == "0:45:00"
