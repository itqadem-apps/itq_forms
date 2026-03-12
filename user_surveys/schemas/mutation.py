from strawberry.tools import merge_types

from .mutations import (
    AnswerQuestionMutation,
    EnrollAssessmentMutation,
    FinishAssessmentMutation,
    GenerateReportMutation,
    HeartbeatMutation,
    ManualEvaluationMutation,
    ReportTabSwitchMutation,
)

Mutation = merge_types(
    "UserSurveysMutation",
    (
        EnrollAssessmentMutation,
        AnswerQuestionMutation,
        FinishAssessmentMutation,
        GenerateReportMutation,
        HeartbeatMutation,
        ManualEvaluationMutation,
        ReportTabSwitchMutation,
    ),
)
