import enum
from functools import wraps
from typing import Literal, Callable, Any, Union

from pkg_auth.authorization import MissingPermission

from app.platform import is_platform_context


class Permission(enum.Enum):
    # Survey permissions
    SURVEY_CREATE = 'surveys:create'
    SURVEY_READ = 'surveys:read'
    SURVEY_UPDATE = 'surveys:update'
    SURVEY_DELETE = 'surveys:delete'

    # Assessment permissions
    ASSESSMENT_CREATE = 'assessments:create'
    ASSESSMENT_READ = 'assessments:read'
    ASSESSMENT_UPDATE = 'assessments:update'
    ASSESSMENT_DELETE = 'assessments:delete'

    # Curriculum permissions
    CURRICULUM_CREATE = 'curriculums:create'
    CURRICULUM_READ = 'curriculums:read'
    CURRICULUM_UPDATE = 'curriculums:update'
    CURRICULUM_DELETE = 'curriculums:delete'

    # Exam permissions
    EXAM_CREATE = 'exams:create'
    EXAM_READ = 'exams:read'
    EXAM_UPDATE = 'exams:update'
    EXAM_DELETE = 'exams:delete'

    # Form permissions
    FORM_CREATE = 'forms:create'
    FORM_READ = 'forms:read'
    FORM_UPDATE = 'forms:update'
    FORM_DELETE = 'forms:delete'

    # Collection permissions
    COLLECTION_CREATE = 'collections:create'
    COLLECTION_READ = 'collections:read'
    COLLECTION_UPDATE = 'collections:update'
    COLLECTION_DELETE = 'collections:delete'

    # Submission permissions (cross-cutting; not tied to an assessment kind)
    SUBMISSION_READ = 'submissions:read'


# Assessment type constants (matching Survey.ASSESSMENT_TYPES)
AssessmentType = Literal['survey', 'assessment', 'curriculum', 'exam', 'form']
ActionType = Literal['create', 'read', 'update', 'delete']

# Map assessment types to their permissions
PERMISSION_MAP: dict[AssessmentType, dict[ActionType, Permission]] = {
    'survey': {
        'create': Permission.SURVEY_CREATE,
        'read': Permission.SURVEY_READ,
        'update': Permission.SURVEY_UPDATE,
        'delete': Permission.SURVEY_DELETE,
    },
    'assessment': {
        'create': Permission.ASSESSMENT_CREATE,
        'read': Permission.ASSESSMENT_READ,
        'update': Permission.ASSESSMENT_UPDATE,
        'delete': Permission.ASSESSMENT_DELETE,
    },
    'curriculum': {
        'create': Permission.CURRICULUM_CREATE,
        'read': Permission.CURRICULUM_READ,
        'update': Permission.CURRICULUM_UPDATE,
        'delete': Permission.CURRICULUM_DELETE,
    },
    'exam': {
        'create': Permission.EXAM_CREATE,
        'read': Permission.EXAM_READ,
        'update': Permission.EXAM_UPDATE,
        'delete': Permission.EXAM_DELETE,
    },
    'form': {
        'create': Permission.FORM_CREATE,
        'read': Permission.FORM_READ,
        'update': Permission.FORM_UPDATE,
        'delete': Permission.FORM_DELETE,
    },
}


def get_permission_for_kind(assessment_type: AssessmentType, action: ActionType) -> Permission:
    return PERMISSION_MAP[assessment_type][action]


def check_permission(assessment_type: Union[str, Callable], action: ActionType) -> Callable:
    """
    Decorator to check permissions for GraphQL mutations using pkg_auth.

    Supports both static and dynamic assessment types:

    Static (type known at decoration time):
        @check_permission('survey', 'create')
        def create_survey(self, info, input):
            ...

    Dynamic (type resolved at runtime via callable):
        def _survey_type(info, **kwargs):
            return Survey.objects.values_list('survey_type', flat=True).get(pk=kwargs['id'])

        @check_permission(_survey_type, 'update')
        def update_survey(self, info, id, input):
            ...

    Args:
        assessment_type: Static type string, or a callable(info, **kwargs) -> str
            that resolves the assessment type at runtime.
        action: Action to perform ('create', 'read', 'update', 'delete')

    Raises:
        PermissionError: If user doesn't have required permission
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, info, *args, **kwargs) -> Any:
            auth_ctx = getattr(info.context, "auth_context", None)
            if auth_ctx is None:
                identity = getattr(info.context, "identity", None)
                if identity is None:
                    raise PermissionError("Authentication required")
                raise PermissionError("Missing X-Organization-Id header")

            if is_platform_context(auth_ctx):
                return func(self, info, *args, **kwargs)

            if callable(assessment_type):
                resolved_type = assessment_type(info, **kwargs)
            else:
                resolved_type = assessment_type

            required_permission = get_permission_for_kind(resolved_type, action)
            try:
                auth_ctx.require(required_permission.value)
            except MissingPermission:
                raise PermissionError(
                    f"Permission denied. Required permission: {required_permission.value}"
                )

            return func(self, info, *args, **kwargs)

        return wrapper
    return decorator