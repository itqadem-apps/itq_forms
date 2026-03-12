from strawberry.tools import merge_types

from .queries import UserSurveyQuery, ShouldTerminateQuery

Query = merge_types(
    "UserSurveyQuery",
    (UserSurveyQuery, ShouldTerminateQuery),
)
