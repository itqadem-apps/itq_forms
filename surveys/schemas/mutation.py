from strawberry.tools import merge_types

from .mutations import (
    AnswerQuestionMutation,
    EnrollAssessmentMutation,
    FinishAssessmentMutation,
    MeQuery,
    SurveyMutations,
    SectionMutations,
    QuestionMutations,
    AnswerSchemaMutations,
    SurveyCollectionMutations,
    EvaluationMutations,
    TranslationMutations,
)

Mutation = merge_types(
    "Mutation",
    (
        EnrollAssessmentMutation,
        AnswerQuestionMutation,
        FinishAssessmentMutation,
        MeQuery,
        SurveyMutations,
        SectionMutations,
        QuestionMutations,
        AnswerSchemaMutations,
        SurveyCollectionMutations,
        EvaluationMutations,
        TranslationMutations,
    ),
)
