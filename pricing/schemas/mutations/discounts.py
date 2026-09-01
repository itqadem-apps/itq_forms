import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from app.schema_common import RequireAuth, OperationResult
from pricing.inputs import DiscountInput, DiscountUpdateInput
from pricing.models import Discount
from pricing.types import DiscountType
from surveys.schemas.utils import input_to_dict
from app.graphql_ids import as_pk


@strawberry.type
class DiscountMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def create_discount(
        self,
        info: Info,
        input: DiscountInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> DiscountType:
        data = input_to_dict(input)
        return Discount.objects.create(**data)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def update_discount(
        self,
        info: Info,
        id: strawberry.ID,
        input: DiscountUpdateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> DiscountType:
        id = as_pk(id)
        discount = Discount.objects.get(pk=id)
        for field, value in input_to_dict(input).items():
            setattr(discount, field, value)
        discount.save()
        return discount

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def delete_discount(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        Discount.objects.filter(pk=id).delete()
        return OperationResult(success=True)
