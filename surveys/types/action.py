from __future__ import annotations

from typing import List

import strawberry_django
from strawberry import auto

from surveys.models import Action
from .translations import ActionTranslationType


@strawberry_django.type(Action)
class ActionType:
    id: auto
    title: auto
    description: auto
    survey_id: auto
    upper_limit: auto
    lower_limit: auto
    translations: List[ActionTranslationType]
