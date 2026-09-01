import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from app.permissions import check_permission
from recommendations.inputs import MaterialInput
from recommendations.types import MaterialType
from recommendations.models import Action, Material, Recommendable
from app.schema_common import RequireAuth, OperationResult
from app.graphql_ids import as_pk


def _type_from_action_id(info, action_id, **kw):
    return Action.objects.select_related('survey').get(pk=action_id).survey.survey_type


def _type_from_material_id(info, id, **kw):
    return Material.objects.select_related('action__survey').get(pk=id).action.survey.survey_type


@strawberry.type
class MaterialMutations:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_action_id, 'update')
    def create_material(
        self,
        info: Info,
        action_id: strawberry.ID,
        recommendable_id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> MaterialType:
        action_id = as_pk(action_id)
        recommendable_id = as_pk(recommendable_id)
        action = Action.objects.get(pk=action_id)
        recommendable = Recommendable.objects.get(pk=recommendable_id)
        material = Material.objects.create(action=action, recommendable=recommendable)
        return material

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_material_id, 'update')
    def update_material(
        self,
        info: Info,
        id: strawberry.ID,
        input: MaterialInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> MaterialType:
        id = as_pk(id)
        material = Material.objects.get(pk=id)
        material.action = Action.objects.get(pk=input.action_id)
        material.recommendable = Recommendable.objects.get(pk=input.recommendable_id)
        material.save()
        return material

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_material_id, 'update')
    def delete_material(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        material = Material.objects.get(pk=id)
        material.delete()
        return OperationResult(success=True)
