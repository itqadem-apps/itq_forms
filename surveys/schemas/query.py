from strawberry.tools import merge_types

from .queries import (
    CollectionsQuery,
    QuestionQuery,
    QuestionsQuery,
    SurveyQuery,
    SurveysQuery,
)
from user_surveys.schemas.queries import UserSurveyQuery, ShouldTerminateQuery

Query = merge_types(
    "Query",
    (
        SurveysQuery,
        CollectionsQuery,
        SurveyQuery,
        UserSurveyQuery,
        ShouldTerminateQuery,
        QuestionQuery,
        QuestionsQuery,
    ),
)
