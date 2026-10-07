import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.timezone import now

from app.auth_utils import with_django_user
from user_surveys.types import UserAnswerType
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.flow import ROUTING_TERMINATE, ending_count, recalculate_on_path
from user_surveys.services import check_time_expired, finish_assessment as finish_assessment_service
from ..common import RequireAuth
from app.graphql_ids import as_pk


def _opt_text(opt: UserAnswerOption) -> str | None:
    """Get the first available text value from the option's translations JSONB."""
    translations = opt.translations or {}
    for lang_data in translations.values():
        if isinstance(lang_data, dict) and lang_data.get("text"):
            return lang_data["text"]
    return None


def _get_client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@strawberry.type
class AnswerQuestionMutation:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def answer_question(
        self,
        info: Info,
        user_survey_id: strawberry.ID,
        question_id: strawberry.ID,
        answer: list[str],
        session_token: str | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserAnswerType:
        user_survey_id = as_pk(user_survey_id)
        question_id = as_pk(question_id)
        with transaction.atomic():
            # Serialises with `finish_assessment`, which locks the same row (`forms:AD-19`).
            user_survey = UserSurvey.objects.select_for_update().filter(id=user_survey_id, user=django_user).first()
            if not user_survey:
                raise ValidationError("Assessment not found.")
            if user_survey.submitted_at:
                raise ValidationError("This assessment is already submitted.")

            # ── anti-cheat checks (only when enabled) ──
            if user_survey.enable_anti_cheat:
                if user_survey.session_token and session_token:
                    if str(user_survey.session_token) != session_token:
                        raise ValidationError("Session conflict detected. This assessment is open in another window.")

            # ── time expiry (always enforced for timed surveys) ──
            if check_time_expired(user_survey):
                finish_assessment_service(user_survey, reason=UserSurvey.TERMINATION_TIME_EXPIRED)
                raise ValidationError("Time has expired for this assessment.")

            question = UserQuestion.objects.filter(id=question_id, user_survey=user_survey).first()
            if not question:
                raise ValidationError("Question not found.")

            user_answer, _created = UserAnswer.objects.get_or_create(
                user_survey=user_survey,
                question=question,
                defaults={
                    "user": django_user,
                    "type": question.type,
                    "order": question.order,
                },
            )

            # ── anti-cheat: lock answers ──
            if user_survey.enable_anti_cheat and not _created and user_survey.lock_answers:
                raise ValidationError("This question has already been answered and cannot be changed.")

            def parse_ids(values: list[str]) -> list[int]:
                ids: list[int] = []
                for raw in values:
                    try:
                        ids.append(int(raw))
                    except (TypeError, ValueError):
                        continue
                return ids

            def require_schema():
                if not hasattr(question, "answer_schema"):
                    raise ValidationError("Answer schema not found.")

            def require_options(option_ids: list[int]) -> list[UserAnswerOption]:
                if not option_ids:
                    raise ValidationError("No options provided.")
                options = list(question.answer_schema.options.filter(id__in=option_ids))
                if len(options) != len(set(option_ids)):
                    raise ValidationError("One or more option IDs are invalid.")
                return options

            Q = UserQuestion  # type constants

            if question.type in Q.MULTI_SELECT_TYPES:
                require_schema()
                option_ids = parse_ids(answer)
                options = require_options(option_ids)
                user_answer.selected_options.set(options)
                user_answer.answer = ", ".join([_opt_text(opt) for opt in options if _opt_text(opt)])
            elif question.type in Q.SINGLE_SELECT_TYPES:
                require_schema()
                option_ids = parse_ids(answer)
                options = require_options(option_ids)
                option = options[0]
                user_answer.selected_options.set([option])
                user_answer.answer = _opt_text(option)
            elif question.type in Q.FREE_INPUT_TYPES:
                user_answer.selected_options.clear()
                user_answer.answer = answer[0] if answer else ""
            elif question.type in Q.GRID_TYPES:
                require_schema()
                flat_ids: list[str] = []
                for token in answer:
                    flat_ids.extend(token.split("-"))
                option_ids = parse_ids(flat_ids)
                options = require_options(option_ids)
                user_answer.selected_options.set(options)
                user_answer.answer = ",".join(answer)
            else:
                raise ValidationError("Unsupported question type.")

            # ── anti-cheat: tracking (only when enabled) ──
            current_time = now()
            if user_survey.enable_anti_cheat:
                user_answer.answered_at = current_time
                prev_answer = (
                    UserAnswer.objects.filter(user_survey=user_survey, answered_at__isnull=False)
                    .exclude(id=user_answer.id)
                    .order_by("-answered_at")
                    .first()
                )
                if prev_answer:
                    user_answer.time_spent = current_time - prev_answer.answered_at
                elif user_survey.started_at:
                    user_answer.time_spent = current_time - user_survey.started_at

                request = info.context.request
                user_answer.ip_address = _get_client_ip(request)
                user_answer.user_agent = request.META.get("HTTP_USER_AGENT", "")

            # ── update survey state ──
            update_fields = ["last_question"]
            if not user_survey.started_at:
                user_survey.started_at = current_time
                update_fields.append("started_at")
            user_survey.last_question = question
            user_survey.save(update_fields=update_fields)
            user_answer.save()

            # `forms:AD-17`; a routing terminate ends the attempt here, on the write (`forms:AD-7`).
            walk = recalculate_on_path(user_survey)
            # Derived from the path, never accumulated, so going back or branching away uncounts it.
            if user_survey.allow_end_based_on_answer_repeat:
                count = ending_count(user_survey, walk.path)
                if count != user_survey.count_of_ending_options:
                    user_survey.count_of_ending_options = count
                    user_survey.save(update_fields=["count_of_ending_options"])
            if walk.end == ROUTING_TERMINATE and walk.path[-1] == question.id:
                finish_assessment_service(user_survey, reason=UserSurvey.TERMINATION_ROUTING)
            return user_answer
