import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from app.schema_common import RequireAuth, OperationResult
from pricing.inputs import PriceInput, PriceUpdateInput
from pricing.models import Price
from pricing.signals import backfill_zero_prices
from pricing.types import PriceType
from surveys.schemas.utils import input_to_dict
from app.graphql_ids import as_pk


@strawberry.type
class PriceMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def create_price(
        self,
        info: Info,
        input: PriceInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> PriceType:
        data = input_to_dict(input)
        price = Price.objects.create(**data)
        backfill_zero_prices(survey=price.survey, collection=price.collection)
        return price

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def update_price(
        self,
        info: Info,
        id: strawberry.ID,
        input: PriceUpdateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> PriceType:
        id = as_pk(id)
        price = Price.objects.get(pk=id)
        for field, value in input_to_dict(input).items():
            setattr(price, field, value)
        price.save()
        backfill_zero_prices(survey=price.survey, collection=price.collection)
        return price

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def delete_price(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        Price.objects.filter(pk=id).delete()
        return OperationResult(success=True)
