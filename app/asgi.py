"""ASGI config for app project.

Wraps the Django ASGI application with a lifespan handler that starts
the unified messaging runtime on server startup and shuts it down on
exit. WSGI, management commands and tests never import this module, so
they don't connect to NATS.
"""

import logging
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

_django_application = get_asgi_application()
logger = logging.getLogger(__name__)


async def application(scope, receive, send):
    if scope["type"] == "lifespan":
        from app.messaging.runtime import start_all, stop_all

        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await start_all()
                except Exception as exc:
                    logger.exception("Messaging runtime failed to start")
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    await stop_all()
                except Exception as exc:
                    logger.exception("Messaging runtime failed to stop cleanly")
                    await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.shutdown.complete"})
                return
        return

    await _django_application(scope, receive, send)