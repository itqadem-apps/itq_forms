from strawberry.tools import merge_types

from .mutations import (
    AnswerQuestionMutation,
    EnrollAssessmentMutation,
    FinishAssessmentMutation,
    MeQuery,
)

Mutation = merge_types(
    "Mutation",
    (
        EnrollAssessmentMutation,
        AnswerQuestionMutation,
        FinishAssessmentMutation,
        MeQuery,
    ),
)
