import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from app.graphql_metrics import PrometheusExtension
from .query import Query
from .mutation import Mutation

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
        PrometheusExtension,
    ],
)
