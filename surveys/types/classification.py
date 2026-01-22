from __future__ import annotations

from typing import List

import strawberry_django
from strawberry import auto

from surveys.models import Classification
from .translations import ClassificationTranslationType


@strawberry_django.type(Classification)
class ClassificationType:
    id: auto
    name: auto
    score: auto
    translations: List[ClassificationTranslationType]
