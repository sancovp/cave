"""AIOS mixin for CAVEAgent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from ..aios import AIOSBridge

if TYPE_CHECKING:
    from ..config import CAVEConfig


class AIOSMixin:
    """Adds read-only SILAS AIOS status, search, and next-action access."""

    config: "CAVEConfig"
    aios_bridge: AIOSBridge

    def _init_aios_bridge(self) -> None:
        root = getattr(self.config, "aios_root", None) or os.environ.get("SILAS_AIOS_ROOT")
        skilltree_src = (
            getattr(self.config, "aios_skilltree_src", None)
            or os.environ.get("SILAS_SKILLTREE_SRC")
        )
        self.aios_bridge = AIOSBridge(root=root, skilltree_src=skilltree_src)

    def _get_aios_bridge(self) -> AIOSBridge:
        if not hasattr(self, "aios_bridge"):
            self._init_aios_bridge()
        return self.aios_bridge

    def aios_status(self) -> Dict[str, Any]:
        return self._get_aios_bridge().status()

    def aios_next_action(self) -> Dict[str, Any]:
        return self._get_aios_bridge().next_action()

    def aios_search(
        self,
        query: str,
        *,
        domain: str = "all",
        limit: int = 8,
    ) -> Dict[str, Any]:
        return self._get_aios_bridge().search(query=query, domain=domain, limit=limit)

    def aios_select_next(self, *, limit: int = 8) -> Dict[str, Any]:
        return self._get_aios_bridge().select_next(limit=limit)

    def aios_gate(self, candidate_id: Optional[str] = None, *, limit: int = 8) -> Dict[str, Any]:
        return self._get_aios_bridge().gate(candidate_id=candidate_id, limit=limit)

    def aios_skilltree_project(self, *, command: str = "doctor", write_map: bool = False) -> Dict[str, Any]:
        return self._get_aios_bridge().skilltree_project(command=command, write_map=write_map)

    def aios_skilltree_lab(self, *, command: str = "run") -> Dict[str, Any]:
        return self._get_aios_bridge().skilltree_lab(command=command)

    def aios_skilltree_coherence(self, *, command: str = "run") -> Dict[str, Any]:
        return self._get_aios_bridge().skilltree_coherence(command=command)
