from typing import Optional, List

import strawberry
from strawberry import UNSET


@strawberry.input
class RecommendationTranslationInput:
    language: str
    description: Optional[str] = None


@strawberry.input
class ActionTranslationInput:
    language: str
    title: Optional[str] = None
    description: Optional[str] = None


@strawberry.input
class RecommendationInput:
    description: str
    option_id: Optional[int] = UNSET
    translations: Optional[List[RecommendationTranslationInput]] = UNSET


@strawberry.input
class ActionInput:
    title: Optional[str] = UNSET
    description: Optional[str] = UNSET
    upper_limit: Optional[float] = UNSET
    lower_limit: Optional[float] = UNSET
    translations: Optional[List[ActionTranslationInput]] = UNSET
