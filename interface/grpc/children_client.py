from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

import grpc

from interface.grpc import children_pb2, children_pb2_grpc


@dataclass(frozen=True)
class ChildrenClientConfig:
    target: str = getattr(settings, "USERS_GRPC_TARGET", "localhost:50051")
    timeout_seconds: float = 5.0


class ChildrenClient:
    def __init__(self, config: ChildrenClientConfig | None = None) -> None:
        self._config = config or ChildrenClientConfig()
        self._channel = grpc.insecure_channel(self._config.target)
        self._stub = children_pb2_grpc.ChildServiceStub(self._channel)

    def close(self) -> None:
        self._channel.close()

    def __enter__(self) -> "ChildrenClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_children_by_guardian(self, guardian_user_id: str, status: str | None = None):
        if hasattr(children_pb2, "GetChildrenByGuardianRequest"):
            request = children_pb2.GetChildrenByGuardianRequest(
                guardian_user_id=guardian_user_id,
                status=status or "",
            )
            method = getattr(self._stub, "GetChildrenByGuardian", None)
            if method is None:
                raise RuntimeError("ChildService.GetChildrenByGuardian is not available in the stub.")
            return method(request, timeout=self._config.timeout_seconds)

        if hasattr(children_pb2, "GetChildrenByParentRequest"):
            request = children_pb2.GetChildrenByParentRequest(
                parent_id=guardian_user_id,
                status=status or "",
            )
            method = getattr(self._stub, "GetChildrenByParent", None)
            if method is None:
                raise RuntimeError("ChildService.GetChildrenByParent is not available in the stub.")
            return method(request, timeout=self._config.timeout_seconds)

        raise RuntimeError("Unsupported children proto version; regenerate stubs.")

    def get_children_by_parent(self, parent_id: str, status: str | None = None):
        return self.get_children_by_guardian(parent_id, status=status)
