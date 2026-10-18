"""ASGI config for app project.

Web serves HTTP only and runs no messaging (forms:AD-26): the lifespan
handler acknowledges startup and shutdown and starts no broker, no relay
and no NATS connection. ``publisher.publish`` writes outbox rows, which
``manage.py relay`` publishes; ``manage.py consume`` binds the durables.
"""

import logging
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

_django_application = get_asgi_application()
logger = logging.getLogger(__name__)


async def application(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                logger.info("lifespan: startup acknowledged; web runs no messaging")
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                # Logged on entry: without it a pod that never got SIGTERM and
                # one that hung on shutdown leave identical (silent) logs.
                logger.info("lifespan: shutdown signal received")
                await send({"type": "lifespan.shutdown.complete"})
                return

    await _django_application(scope, receive, send)
