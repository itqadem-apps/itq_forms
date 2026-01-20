import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from .query import Query
from .mutation import Mutation

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
    ],
)
