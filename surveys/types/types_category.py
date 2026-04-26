from __future__ import annotations

from typing import List

import strawberry_django
from strawberry import auto

from taxonomy.models import Category
from .translations import CategoryTranslationType


@strawberry_django.type(Category)
class CategoryType:
    category_id: auto
    tree_id: auto
    name: auto
    path_text: auto
    translations: List[CategoryTranslationType]
