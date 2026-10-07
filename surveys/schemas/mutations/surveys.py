import strawberry
import strawberry_django
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Q
from strawberry import UNSET
from strawberry.types import Info

from app.auth_utils import with_django_user
from app.permissions import check_permission
from app.platform import ensure_in_org
from surveys.flow import check_display_option
from surveys.inputs import SurveyCreateInput, SurveyUpdateInput
from surveys.question_order import flat_question_ids, renumber_questions
from surveys.types import SurveyType
from surveys.types.survey import SurveyPayload
from app.messaging import publish
from external_references.models import ExternalReference
from pricing.services import upsert_prices_for_parent
from surveys.events import (
    SurveyCreated,
    SurveyDeleted,
    SurveyPublished,
    SurveyUnpublished,
    SurveyUpdated,
)
from surveys.messaging import build_survey_payload_or_log
from classifications.models import Classification, ClassificationTranslation
from recommendations.models import Recommendation, RecommendationTranslation, Action, ActionTranslation
from surveys.models import (
    AnswerSchema,
    AnswerSchemaTranslation,
    Survey,
    SurveyTranslation,
    Section,
    SectionTranslation,
    Question,
    QuestionTranslation,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
    FlowAction,
    ScoreBasis,
    ShuffleScope,
)
from taxonomy.models import Category
from ..common import RequireAuth, OperationResult
from ..utils import coerce_duration, input_to_dict, clone_instance
from app.graphql_ids import as_pk


def _check_shuffle_scope(data: dict) -> None:
    scope = data.get('shuffle_scope')
    if scope is not None and scope not in ShuffleScope.values:
        raise ValidationError({'shuffle_scope': [f"\"{scope}\" is not a shuffle scope; use one of {', '.join(ShuffleScope.values)}."]})


def _check_score_basis(data: dict) -> None:
    basis = data.get('score_basis')
    if basis is not None and basis not in ScoreBasis.values:
        raise ValidationError({'score_basis': [f"\"{basis}\" is not a score basis; use one of {', '.join(ScoreBasis.values)}."]})


def _type_from_input(info, input, **kw):
    return input.survey_type or 'survey'


def _type_from_survey_id(info, id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=id)


def _type_from_update_input(info, input, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=input.id)


@strawberry.type
class SurveyMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_input, 'create')
    @transaction.atomic
    def create_survey(
        self,
        info: Info,
        input: SurveyCreateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        data = input_to_dict(input, exclude=['category_id', 'translations', 'external_reference', 'prices'])
        _check_shuffle_scope(data)
        _check_score_basis(data)
        if 'time_limit' in data:
            data['time_limit'] = coerce_duration(data['time_limit'])

        # The owning organization is bound from the caller's auth context, never
        # taken from client input — see SPEC-forms-permission-gates CAP-1.
        data['organization_id'] = info.context.auth_context.organization_id.value

        if input.category_id is not UNSET and input.category_id is not None:
            try:
                data['category'] = Category.objects.get(category_id=input.category_id)
            except Category.DoesNotExist:
                raise ObjectDoesNotExist(f"Category not found: {input.category_id}")

        target_collection = None
        if input.external_reference is not UNSET and input.external_reference is not None:
            ref = (
                ExternalReference.objects
                .select_related("collection")
                .filter(
                    source_service=input.external_reference.source_service,
                    source_model=input.external_reference.source_model,
                    source_id=input.external_reference.source_id,
                    collection__isnull=False,
                )
                .first()
            )
            if ref is None:
                raise ObjectDoesNotExist(
                    f"External reference not found or has no collection: "
                    f"{input.external_reference.source_service}:"
                    f"{input.external_reference.source_model}:"
                    f"{input.external_reference.source_id}"
                )
            target_collection = ref.collection

        # The column default pre-empts SurveyTranslation.save's claim, so set the
        # primary here, in the same INSERT, so it never has to move (forms:AD-1).
        # Arabic wins whenever it is authored: the admin form sends translations
        # in locale order, [en, ar], so "the first one" would file every
        # bilingual survey under English.
        if not data.get('primary_language'):
            languages = [t.language for t in input.translations or []]
            data['primary_language'] = (
                Survey.PRIMARY_LANGUAGE_DEFAULT
                if not languages or Survey.PRIMARY_LANGUAGE_DEFAULT in languages
                else languages[0]
            )

        survey = Survey.objects.create(**data)

        if target_collection is not None:
            target_collection.assessments.add(survey)

        if input.translations is not UNSET and input.translations:
            for t in input.translations:
                SurveyTranslation.objects.create(survey=survey, **input_to_dict(t))

        if input.prices is not UNSET and input.prices:
            upsert_prices_for_parent(survey, input.prices)

        payload = build_survey_payload_or_log(survey, "SurveyCreated")
        if payload is not None:
            publish(SurveyCreated(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))

        return SurveyPayload(success=True, message=None, survey=survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_update_input, 'update')
    @transaction.atomic
    def update_survey(
        self,
        info: Info,
        input: SurveyUpdateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        survey = Survey.objects.get(pk=input.id)
        ensure_in_org(survey, info.context.auth_context)

        data = input_to_dict(input, exclude=['id', 'category_id', 'translations', 'prices'])
        _check_shuffle_scope(data)
        _check_score_basis(data)
        if 'display_option' in data:
            check_display_option(survey, data['display_option'])
        if 'time_limit' in data:
            data['time_limit'] = coerce_duration(data['time_limit'])
        for field, value in data.items():
            setattr(survey, field, value)

        if input.category_id is not UNSET:
            if input.category_id:
                try:
                    survey.category = Category.objects.get(category_id=input.category_id)
                except Category.DoesNotExist:
                    raise ObjectDoesNotExist(f"Category not found: {input.category_id}")
            else:
                survey.category = None

        survey.save()

        if input.translations is not UNSET and input.translations:
            for t in input.translations:
                t_data = input_to_dict(t, exclude=['id'])
                language = t_data.pop('language', None)
                if language:
                    SurveyTranslation.objects.update_or_create(
                        survey=survey, language=language, defaults=t_data
                    )

        if input.prices is not UNSET and input.prices:
            upsert_prices_for_parent(survey, input.prices)

        payload = build_survey_payload_or_log(survey, "SurveyUpdated")
        if payload is not None:
            publish(SurveyUpdated(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))

        return SurveyPayload(success=True, message=None, survey=survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'delete')
    def delete_survey(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        survey = Survey.objects.get(pk=id)
        ensure_in_org(survey, info.context.auth_context)
        payload = build_survey_payload_or_log(survey, "SurveyDeleted")
        if payload is not None:
            publish(SurveyDeleted(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))
        survey.delete()
        return OperationResult(success=True)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'create')
    @transaction.atomic
    def duplicate_survey(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        id = as_pk(id)
        original = Survey.objects.get(pk=id)
        ensure_in_org(original, info.context.auth_context)

        new_survey = clone_instance(original)

        # Duplicate survey translations
        for t in original.translations.all():
            clone_instance(
                t,
                survey=new_survey,
                title=f"{t.title} (Copy)" if t.title else None,
                slug=f"{t.slug}-copy" if t.slug else None,
            )

        # Classifications first: the copy's options are re-pointed at them as they are cloned.
        classification_map: dict[int, Classification] = {}
        for classification in original.classifications.all():
            new_classification = clone_instance(classification, survey=new_survey)
            classification_map[classification.pk] = new_classification
            for t in ClassificationTranslation.objects.filter(classification=classification):
                clone_instance(t, classification=new_classification)

        section_map: dict[int, Section] = {}

        def clone_section(section: Section) -> Section:
            new_section = clone_instance(section, survey=new_survey, submit_action_target=None)
            # The post_save signal gives every new section a blank question; the copy's
            # questions are the original's, no more.
            for blank in Question.objects.filter(section=new_section):
                blank.delete()
            for t in SectionTranslation.objects.filter(section=section):
                clone_instance(t, section=new_section)
            section_map[section.pk] = new_section
            return new_section

        # Questions are cloned in the original's flat order, each unplaced (`order` null), so
        # `renumber_questions` appends it after the questions already copied and the copy reads
        # in the same sequence, sections contiguous and sectionless questions between them
        # (`forms:AD-4`). A section is cloned when its first question is reached, so its blank
        # question is gone before anything is placed around it.
        original_questions = Question.objects.filter(Q(survey=original) | Q(section__survey=original))
        questions_by_id = {q.pk: q for q in original_questions}
        question_map: dict[int, Question] = {}
        option_map: dict[int, AnswerSchemaOption] = {}
        routed: list[tuple[AnswerSchemaOption, int]] = []
        for question_id in flat_question_ids(original_questions):
            question = questions_by_id[question_id]
            new_section = None
            if question.section_id is not None:
                new_section = section_map.get(question.section_id) or clone_section(question.section)
            new_question = clone_instance(question, survey=new_survey, section=new_section, order=None)
            question_map[question.pk] = new_question

            for t in QuestionTranslation.objects.filter(question=question):
                clone_instance(t, question=new_question)

            # Reshape the schema the post_save signal made for the copy, as `duplicate_question`
            # does: AnswerSchema.question is one-to-one, so a second insert is refused.
            old_schema = AnswerSchema.objects.filter(question=question).first()
            new_schema = AnswerSchema.objects.filter(question=new_question).first()
            if new_schema is None:
                continue
            if old_schema is None:
                new_schema.delete()
                continue
            new_schema.type = old_schema.type
            new_schema.with_file = old_schema.with_file
            new_schema.is_mcq = old_schema.is_mcq
            new_schema.is_grid = old_schema.is_grid
            new_schema.section = new_section
            new_schema.save()
            for t in AnswerSchemaTranslation.objects.filter(schema=old_schema):
                clone_instance(t, schema=new_schema)

            # The signal seeds a blank option (or one per classification); the copy takes the
            # original's instead.
            new_schema.options.all().delete()
            for option in old_schema.options.all():
                new_option = clone_instance(
                    option,
                    survey=new_survey,
                    section=new_section,
                    question=new_question,
                    schema=new_schema,
                    # A classification outside this survey is kept by id, unloaded.
                    classification=classification_map.get(option.classification_id)
                    or (Classification(pk=option.classification_id) if option.classification_id else None),
                    flow_target=None,
                    flow_action=FlowAction.FALL_THROUGH if option.flow_action == FlowAction.GO_TO else option.flow_action,
                )
                option_map[option.pk] = new_option
                if option.flow_action == FlowAction.GO_TO and option.flow_target_id:
                    routed.append((new_option, option.flow_target_id))
                for t in AnswerSchemaOptionTranslation.objects.filter(option=option):
                    clone_instance(t, option=new_option)

        for section in original.sections.all():
            if section.pk not in section_map:
                clone_section(section)
        for section in original.sections.filter(submit_action_target__isnull=False):
            target = section_map.get(section.submit_action_target_id)
            if target is not None:
                Section.objects.filter(pk=section_map[section.pk].pk).update(submit_action_target=target)
        renumber_questions(new_survey.id)

        # An edge is re-pointed at the copy's own question once every question exists; one whose
        # target was not copied falls through (`forms:AD-3`).
        for new_option, old_target in routed:
            if old_target in question_map:
                new_option.flow_action = FlowAction.GO_TO
                new_option.flow_target = question_map[old_target]
                new_option.save(update_fields=["flow_action", "flow_target"])

        # Duplicate recommendations, each on the copy's own option.
        for recommendation in Recommendation.objects.filter(Q(survey=original) | Q(option__survey=original)):
            new_recommendation = clone_instance(
                recommendation,
                survey=new_survey if recommendation.survey_id is not None else None,
                option=option_map[recommendation.option_id]
                if recommendation.option_id in option_map
                else recommendation.option,
            )
            for t in RecommendationTranslation.objects.filter(recommendation=recommendation):
                clone_instance(t, recommendation=new_recommendation)

        # Duplicate actions
        for action in original.actions.all():
            new_action = clone_instance(action, survey=new_survey)
            for t in ActionTranslation.objects.filter(action=action):
                clone_instance(t, action=new_action)

        return SurveyPayload(success=True, message=None, survey=new_survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def update_survey_status(
        self,
        info: Info,
        id: strawberry.ID,
        status: str,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyType:
        id = as_pk(id)
        survey = Survey.objects.get(pk=id)
        ensure_in_org(survey, info.context.auth_context)
        old_status = survey.status
        survey.status = status
        survey.save(update_fields=["status"])
        if survey.status == Survey.STATUS_PUBLISHED:
            event_cls = SurveyPublished
            event_name = "SurveyPublished"
        elif survey.status in {Survey.STATUS_DRAFT, Survey.STATUS_ARCHIVED, Survey.STATUS_SUSPENDED}:
            event_cls = SurveyUnpublished
            event_name = "SurveyUnpublished"
        else:
            event_cls = SurveyUpdated
            event_name = "SurveyUpdated"
        payload = build_survey_payload_or_log(survey, event_name)
        if payload is not None:
            publish(event_cls(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))

        if old_status != survey.status:
            from surveys.media_access import promote_survey_assets, demote_survey_assets
            if survey.status == Survey.STATUS_PUBLISHED:
                promote_survey_assets(survey.pk)
            elif survey.status in {Survey.STATUS_DRAFT, Survey.STATUS_ARCHIVED, Survey.STATUS_SUSPENDED}:
                demote_survey_assets(survey.pk)

        return survey
