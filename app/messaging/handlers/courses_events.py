"""Handler for ``courses.course.{created,updated,deleted}`` events.

Note: ``courses.>`` is already consumed by ``RecommendableEventSubscriber``
for catalog purposes. The unimessaging registry routes one handler per
subject, so :func:`handle_courses_event` is invoked from inside the
recommendable subscriber rather than registered as a separate consumer.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from external_references.courses import (
    handle_course_created,
    handle_course_deleted,
    handle_course_updated,
)

logger = logging.getLogger(__name__)

_DISPATCH = {
    "courses.course.created": handle_course_created,
    "courses.course.updated": handle_course_updated,
    "courses.course.deleted": handle_course_deleted,
}


async def handle_courses_event(payload: Any, subject: str) -> None:
    fn = _DISPATCH.get(subject)
    if fn is None:
        return
    if not isinstance(payload, dict):
        logger.warning("courses event skip subject=%s reason=non_dict_payload", subject)
        return
    await sync_to_async(fn, thread_sensitive=True)(payload)
