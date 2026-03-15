import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from recommendations.inputs import RecommendableInput
from recommendations.types import RecommendableType
from recommendations.models import Recommendable
from app.schema_common import RequireAuth, OperationResult
from surveys.schemas.utils import input_to_dict


@strawberry.type
class RecommendableMutations:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def create_recommendable(
        self,
        info: Info,
        input: RecommendableInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> RecommendableType:
        data = input_to_dict(input)
        recommendable = Recommendable.objects.create(**data)
        return recommendable

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def update_recommendable(
        self,
        info: Info,
        id: int,
        input: RecommendableInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> RecommendableType:
        recommendable = Recommendable.objects.get(pk=id)
        for field, value in input_to_dict(input).items():
            setattr(recommendable, field, value)
        recommendable.save()
        return recommendable

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def delete_recommendable(
        self,
        info: Info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        recommendable = Recommendable.objects.get(pk=id)
        recommendable.delete()
        return OperationResult(success=True)
