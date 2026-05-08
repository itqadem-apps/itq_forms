from typing import Optional

import strawberry


@strawberry.input
class ExternalReferenceFilterInput:
    source_service: Optional[str] = None
    source_model: Optional[str] = None
    source_id: Optional[str] = None


@strawberry.input
class ExternalReferenceInput:
    """Identifies a single external entity by its canonical triple.

    Used in mutations that need to resolve the local target a row tied to an
    external entity (e.g. attaching a new survey to a course's collection).
    """

    source_service: str
    source_model: str
    source_id: str
