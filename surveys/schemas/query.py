from strawberry.tools import merge_types

from .queries import (
    CollectionsQuery,
    QuestionQuery,
    QuestionsQuery,
    SurveyQuery,
    SurveysQuery,
)
from user_surveys.schemas.queries import UserSurveyQuery, ShouldTerminateQuery
from classifications.schemas.queries import ClassificationsQuery
from recommendations.schemas.queries import (
    RecommendationsQuery,
    ActionsQuery,
    RecommendablesQuery,
    MaterialsQuery,
)

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
        ClassificationsQuery,
        RecommendationsQuery,
        ActionsQuery,
        RecommendablesQuery,
        MaterialsQuery,
    ),
)
