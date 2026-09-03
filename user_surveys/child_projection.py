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


def supervised_child_ids_for_org(organization_id: str):
    """Child ids the given organization currently supervises.

    An organization's only link to a child is the supervisor relation, which
    exists because the guardian approved it and disappears when they revoke
    it. Deriving access from the relation at read time — rather than stamping
    an organization onto the submission — is what makes revocation retroactive.

    There is deliberately no date bound: once the relation is active the
    organization reads the child's whole submission history, including
    submissions predating the relation.
    """
    return ChildGuardian.objects.filter(
        organization_id=str(organization_id),
        role="supervisor",
        status="active",
    ).values_list("child_id", flat=True)
