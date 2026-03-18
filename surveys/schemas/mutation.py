from strawberry.tools import merge_types

from .mutations import (
    MeQuery,
    SurveyMutations,
    SectionMutations,
    QuestionMutations,
    AnswerSchemaMutations,
    TranslationMutations,
)
from classifications.schemas.mutations import (
    ClassificationMutations,
    ClassificationTranslationMutations,
)
from recommendations.schemas.mutations import (
    RecommendationMutations,
    ActionMutations,
    RecommendationTranslationMutations,
    ActionTranslationMutations,
    RecommendableMutations,
    MaterialMutations,
)
from survey_collections.schemas.mutations import (
    SurveyCollectionMutations,
    SurveyCollectionTranslationMutations,
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
from pricing.schemas.mutations import PriceMutations, DiscountMutations

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
        TranslationMutations,
        ClassificationMutations,
        ClassificationTranslationMutations,
        RecommendationMutations,
        ActionMutations,
        RecommendationTranslationMutations,
        ActionTranslationMutations,
        RecommendableMutations,
        MaterialMutations,
        SurveyCollectionMutations,
        SurveyCollectionTranslationMutations,
        PriceMutations,
        DiscountMutations,
    ),
)
