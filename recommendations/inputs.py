from typing import Optional, List

import strawberry
from strawberry import UNSET
from strawberry.scalars import JSON


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
    option_id: Optional[int] = UNSET
    translations: Optional[List[RecommendationTranslationInput]] = UNSET


@strawberry.input
class ActionInput:
    upper_limit: Optional[float] = UNSET
    lower_limit: Optional[float] = UNSET
    translations: Optional[List[ActionTranslationInput]] = UNSET


@strawberry.input
class RecommendableInput:
    source_service: Optional[str] = UNSET
    source_model: Optional[str] = UNSET
    source_id: Optional[str] = UNSET
    data: Optional[JSON] = UNSET


@strawberry.input
class MaterialInput:
    action_id: int
    recommendable_id: int
