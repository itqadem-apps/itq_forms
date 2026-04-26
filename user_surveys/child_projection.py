from __future__ import annotations

from accounts.models import Child, ChildGuardian


def get_active_child_for_user(user_id: str, child_id: str) -> Child | None:
    relation = (
        ChildGuardian.objects.select_related("child")
        .filter(
            user_id=str(user_id),
            child_id=str(child_id),
            status="active",
            child__status="active",
        )
        .first()
    )
    return relation.child if relation is not None else None
