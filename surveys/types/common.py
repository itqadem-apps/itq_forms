from __future__ import annotations

from typing import List, Optional

import strawberry


@strawberry.type
class QuestionsFiltersGQL:
    question_ids: Optional[List[int]]
    section_id: Optional[int]
    is_required: Optional[bool]
    question_type: Optional[str]
    answered: Optional[bool]
