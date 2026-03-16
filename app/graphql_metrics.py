"""
Strawberry extension that instruments all GraphQL operations with Prometheus metrics.

Tracks:
- graphql_requests_total (counter) — by operation type, name, and status
- graphql_request_duration_seconds (histogram) — by operation type and name
- graphql_errors_total (counter) — by operation type and name
"""
import time
from typing import Any, Generator

from prometheus_client import Counter, Histogram
from strawberry.extensions import SchemaExtension
from strawberry.types import ExecutionContext


graphql_requests_total = Counter(
    "graphql_requests_total",
    "Total GraphQL operations",
    ["operation_type", "operation_name", "status"],
)

graphql_request_duration_seconds = Histogram(
    "graphql_request_duration_seconds",
    "GraphQL operation duration in seconds",
    ["operation_type", "operation_name"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

graphql_errors_total = Counter(
    "graphql_errors_total",
    "Total GraphQL errors",
    ["operation_type", "operation_name"],
)


class PrometheusExtension(SchemaExtension):
    def on_execute(self) -> Generator[None, None, None]:
        context: ExecutionContext = self.execution_context
        operation_type = (context.operation_type or "unknown").value if context.operation_type else "unknown"
        operation_name = context.operation_name or "anonymous"

        start = time.perf_counter()
        yield
        duration = time.perf_counter() - start

        result = context.result
        has_errors = result is not None and result.errors

        graphql_request_duration_seconds.labels(
            operation_type=operation_type,
            operation_name=operation_name,
        ).observe(duration)

        graphql_requests_total.labels(
            operation_type=operation_type,
            operation_name=operation_name,
            status="error" if has_errors else "success",
        ).inc()

        if has_errors:
            graphql_errors_total.labels(
                operation_type=operation_type,
                operation_name=operation_name,
            ).inc(len(result.errors))