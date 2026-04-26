from __future__ import annotations

from typing import List

import strawberry_django
from strawberry import auto

from classifications.models import Classification
from .translations import ClassificationTranslationType


@strawberry_django.type(Classification)
class ClassificationType:
    id: auto
    survey_id: auto
    score: auto
    created_at: auto
    updated_at: auto
    translations: List[ClassificationTranslationType]
