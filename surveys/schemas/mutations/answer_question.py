import strawberry
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction

from app.auth_utils import with_django_user
from surveys.models import AnswerSchemaOption, Question
from surveys.types import UserAnswerType
from user_surveys.models import UserAnswer, UserSurvey
from ..common import RequireAuth


@strawberry.type
class AnswerQuestionMutation:
    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def answer_question(
        self,
        info,
        user_survey_id: int,
        question_id: int,
        answer: list[str],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserAnswerType:
        with transaction.atomic():
            user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
            if not user_survey:
                raise ValueError("Assessment not found.")
            if user_survey.submitted_at:
                raise ValueError("This assessment is already submitted.")

            question = Question.objects.filter(id=question_id, survey_id=user_survey.survey_id).first()
            if not question:
                raise ValueError("Question not found.")

            user_answer, _created = UserAnswer.objects.get_or_create(
                user_survey=user_survey,
                question_id=question.id,
                defaults={
                    "user": django_user,
                    "survey_id": user_survey.survey_id,
                    "type": question.type,
                    "order": question.order,
                },
            )

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
                    raise ValueError("Answer schema not found.")

            def require_options(option_ids: list[int]) -> list[AnswerSchemaOption]:
                if not option_ids:
                    raise ValueError("No options provided.")
                options = list(question.answer_schema.options.filter(id__in=option_ids))
                if len(options) != len(set(option_ids)):
                    raise ValueError("One or more option IDs are invalid.")
                return options

            if question.type == Question.QUESTION_TYPE_CHECKBOX_MCQ:
                require_schema()
                option_ids = parse_ids(answer)
                options = require_options(option_ids)
                ending_count = sum(1 for opt in options if opt.ending_option)
                if ending_count:
                    user_survey.count_of_ending_options += ending_count
                elif user_survey.survey and user_survey.survey.end_based_on_answer_repeat_in_row:
                    user_survey.count_of_ending_options = 0
                user_answer.selected_options.set(options)
                user_answer.answer = ", ".join([opt.text for opt in options if opt.text])
            elif question.type in [Question.QUESTION_TYPE_RADIO_MCQ, Question.QUESTION_TYPE_DROPDOWN_MCQ]:
                require_schema()
                option_ids = parse_ids(answer)
                options = require_options(option_ids)
                option = options[0]
                if option.ending_option:
                    user_survey.count_of_ending_options += 1
                elif user_survey.survey and user_survey.survey.end_based_on_answer_repeat_in_row:
                    user_survey.count_of_ending_options = 0
                user_answer.selected_options.set([option])
                user_answer.answer = option.text
            elif question.type in [
                Question.QUESTION_TYPE_TEXT,
                Question.QUESTION_TYPE_TEXTAREA,
                Question.QUESTION_TYPE_DATE,
                Question.QUESTION_TYPE_TIME,
                Question.QUESTION_TYPE_DATETIME,
                Question.QUESTION_TYPE_NUMBER,
                Question.QUESTION_TYPE_FILE,
            ]:
                user_answer.selected_options.clear()
                user_answer.answer = answer[0] if answer else ""
            elif question.type in [Question.QUESTION_TYPE_RADIO_GRID, Question.QUESTION_TYPE_CHECKBOX_GRID]:
                require_schema()
                flat_ids: list[str] = []
                for token in answer:
                    flat_ids.extend(token.split("-"))
                option_ids = parse_ids(flat_ids)
                options = require_options(option_ids)
                user_answer.selected_options.set(options)
                user_answer.answer = ",".join(answer)
            else:
                raise ValueError("Unsupported question type.")

            user_survey.last_question_id = question.id
            user_survey.save(update_fields=["last_question", "count_of_ending_options"])
            user_answer.save()
            return user_answer
