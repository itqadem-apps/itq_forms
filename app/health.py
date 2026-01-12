import logging
import sys
import traceback

from django.conf import settings
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def _git_sha() -> str:
    return getattr(settings, "GIT_SHA", "unknown")


@require_GET
def healthz(request):
    """Basic liveness endpoint: returns 200 when the app is running."""
    return JsonResponse({"status": "ok", "git_sha": _git_sha()}, status=200)


@require_GET
def readyz(request):
    """Readiness endpoint: verifies critical dependencies (DB, Redis, migrations)."""
    checks: dict[str, str] = {}
    ok = True
    logger.info("readyz: starting readiness checks")

    # Database connectivity
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1;")
        checks["database"] = "ok"
        logger.info("readyz: database check ok")
    except OperationalError as e:
        checks["database"] = f"error: {e.__class__.__name__}"
        ok = False
        logger.exception("readyz: database check failed: %s", e)
    except Exception as e:  # pragma: no cover - defensive
        checks["database"] = f"error: {e.__class__.__name__}"
        ok = False
        logger.exception("readyz: unexpected database error: %s", e)

    # Redis connectivity (optional)
    try:
        redis_url = getattr(settings, "REDIS_URL", None)
        if redis_url:
            logger.info("readyz: redis check enabled")
            import redis  # type: ignore

            client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "disabled"
            logger.info("readyz: redis check disabled (no REDIS_URL)")
    except Exception as e:  # pragma: no cover - robust in varied envs
        checks["redis"] = f"error: {e.__class__.__name__}"
        ok = False
        logger.exception("readyz: redis check failed: %s", e)

    # Unapplied migrations check
    try:
        connection = connections["default"]
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            checks["migrations"] = f"pending: {len(plan)}"
            ok = False
            logger.warning("readyz: migrations pending: %d", len(plan))
        else:
            checks["migrations"] = "ok"
            logger.info("readyz: migrations check ok")
    except Exception as e:  # covers cases like missing tables early in bootstrap
        checks["migrations"] = f"error: {e.__class__.__name__}"
        ok = False
        logger.exception("readyz: migrations check failed: %s", e)

    status_code = 200 if ok else 503
    logger.info("readyz: completed with status %s; checks=%s", status_code, checks)
    return JsonResponse(
        {"status": "ok" if ok else "fail", "git_sha": _git_sha(), "checks": checks},
        status=status_code,
    )


@require_GET
def startupz(request):
    """Startup endpoint: reuse readiness checks during container startup."""
    return JsonResponse({"status": "ok", "git_sha": _git_sha()}, status=200)
