"""Cognition mixin for CAVEAgent.

Exposes durable cognitive spaces and reified loop shapes as agent methods so
servers, hooks, and MCP clients can all use the same storage semantics.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from ..cognition import CognitionStore, write_cognitive_stop_hook

if TYPE_CHECKING:
    from ..config import CAVEConfig


class CognitionMixin:
    """Mixin that adds cognitive-space construction and stop checking."""

    config: "CAVEConfig"
    cognition_store: CognitionStore

    def _init_cognition(self) -> None:
        self.cognition_store = CognitionStore(self.config.data_dir)
        if hasattr(self, "_hook_state"):
            self._hook_state["cognition_data_dir"] = str(self.config.data_dir)

    def _get_cognition_store(self) -> CognitionStore:
        if not hasattr(self, "cognition_store"):
            self._init_cognition()
        return self.cognition_store

    def create_reified_loop(self, **data: Any) -> Dict[str, Any]:
        data = self._normalize_loop_payload(data)
        return self._get_cognition_store().create_loop_shape(**data)

    def get_reified_loop(self, loop_id: str) -> Dict[str, Any]:
        return self._get_cognition_store().load_loop(loop_id)

    def create_cognitive_space(self, **data: Any) -> Dict[str, Any]:
        data = self._normalize_space_payload(data)
        return self._get_cognition_store().create_space(**data)

    def get_cognitive_space(self, space_id: str) -> Dict[str, Any]:
        return self._get_cognition_store().load_space(space_id)

    def get_current_cognitive_space(self) -> Dict[str, Any]:
        space = self._get_cognition_store().get_current_space()
        return {"current": space, "path": space.get("path") if space else None}

    def set_current_cognitive_space(self, space_id: str) -> Dict[str, Any]:
        return self._get_cognition_store().set_current_space(space_id)

    def put_cognitive_kv(
        self,
        *,
        space_id: Optional[str] = None,
        key: Optional[str] = None,
        value: Any = None,
        updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._get_cognition_store().put_kv(
            space_id=space_id,
            key=key,
            value=value,
            updates=updates,
        )

    def add_cognitive_evidence_file(
        self,
        *,
        space_id: Optional[str] = None,
        path: str,
    ) -> Dict[str, Any]:
        return self._get_cognition_store().add_evidence_file(space_id=space_id, path=path)

    def cognition_stop_check(
        self,
        *,
        space_id: Optional[str] = None,
        hook_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._get_cognition_store().stop_check(
            space_id=space_id,
            hook_payload=hook_payload,
        )

    def install_cognition_stop_hook(
        self,
        *,
        activate: bool = False,
        hook_name: str = "cognitive_space_stop_check",
    ) -> Dict[str, Any]:
        path = write_cognitive_stop_hook(self.config.hook_dir)
        scan_result = self.scan_hooks() if hasattr(self, "scan_hooks") else {}

        active_hooks = self.config.main_agent_config.active_hooks
        if activate:
            stop_hooks = active_hooks.setdefault("stop", [])
            if hook_name not in stop_hooks:
                stop_hooks.append(hook_name)
            if hasattr(self.config, "save"):
                self.config.save()

        return {
            "hook_name": hook_name,
            "path": str(path),
            "activated": activate,
            "active_hooks": active_hooks,
            "scan": scan_result,
        }

    def _normalize_loop_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if "id" in data and "loop_id" not in data:
            data["loop_id"] = data.pop("id")
        return data

    def _normalize_space_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if "id" in data and "space_id" not in data:
            data["space_id"] = data.pop("id")
        return data
