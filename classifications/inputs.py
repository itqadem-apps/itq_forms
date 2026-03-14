from typing import List, Optional

import strawberry
from strawberry import UNSET


@strawberry.input
class ClassificationTranslationInput:
    language: str
    name: Optional[str] = None


@strawberry.input
class ClassificationInput:
    score: Optional[int] = UNSET
    translations: Optional[List[ClassificationTranslationInput]] = UNSET
