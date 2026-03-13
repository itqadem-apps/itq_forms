from strawberry.tools import merge_types

from .mutations import (
    MeQuery,
    SurveyMutations,
    SectionMutations,
    QuestionMutations,
    AnswerSchemaMutations,
    SurveyCollectionMutations,
    EvaluationMutations,
    TranslationMutations,
)
from classifications.schemas.mutations import (
    ClassificationMutations,
    ClassificationTranslationMutations,
)
from user_surveys.schemas.mutations import (
    EnrollAssessmentMutation,
    AnswerQuestionMutation,
    FinishAssessmentMutation,
    GenerateReportMutation,
    HeartbeatMutation,
    ManualEvaluationMutation,
    ReportTabSwitchMutation,
)

Mutation = merge_types(
    "Mutation",
    (
        EnrollAssessmentMutation,
        AnswerQuestionMutation,
        FinishAssessmentMutation,
        GenerateReportMutation,
        HeartbeatMutation,
        ManualEvaluationMutation,
        ReportTabSwitchMutation,
        MeQuery,
        SurveyMutations,
        SectionMutations,
        QuestionMutations,
        AnswerSchemaMutations,
        SurveyCollectionMutations,
        EvaluationMutations,
        TranslationMutations,
        ClassificationMutations,
        ClassificationTranslationMutations,
    ),
)
