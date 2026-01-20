from strawberry.tools import merge_types

from .queries import (
    CollectionsQuery,
    QuestionQuery,
    QuestionsQuery,
    SurveyQuery,
    SurveysQuery,
    UserSurveysQuery,
)

Query = merge_types(
    "Query",
    (
        SurveysQuery,
        CollectionsQuery,
        SurveyQuery,
        UserSurveysQuery,
        QuestionQuery,
        QuestionsQuery,
    ),
)
