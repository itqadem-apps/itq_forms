from __future__ import annotations

import strawberry_django
from strawberry import auto

from classifications.models import ClassificationTranslation


@strawberry_django.type(ClassificationTranslation)
class ClassificationTranslationType:
    id: auto
    language: auto
    name: auto
