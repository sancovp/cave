"""OmnisancMixin - Omnisanc state detection and metabrainhook management.

Provides CAVEAgent access to:
1. Omnisanc course state (HOME/JOURNEY/etc)
2. Metabrainhook state (on/off)
3. Metabrainhook prompt file (injected content)
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# File paths
OMNISANC_STATE_FILE = Path("/tmp/heaven_data/omnisanc_core/.course_state")
OMNISANC_DISABLED_FILE = Path("/tmp/heaven_data/omnisanc_core/.omnisanc_disabled")
METABRAINHOOK_STATE_FILE = Path("/tmp/metabrainhook_state.txt")
METABRAINHOOK_PROMPT_FILE = Path("/tmp/heaven_data/metabrainhook_config.json")


class OmnisancMixin:
    """Mixin for omnisanc state detection and metabrainhook management."""

    def _init_omnisanc(self) -> None:
        """Initialize omnisanc mixin."""
        # Ensure directories exist
        OMNISANC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        METABRAINHOOK_PROMPT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Omnisanc State
    # =========================================================================

    def get_omnisanc_state(self) -> Dict[str, Any]:
        """Read current omnisanc course state.

        Returns dict with keys like:
        - course_plotted: bool
        - projects: list[str]
        - mission_active: bool
        - mission_id: str
        - domain: str
        - subdomain: str
        - fly_called: bool
        - flight_selected: bool
        - was_compacted: bool
        - oriented: bool
        """
        try:
            if OMNISANC_STATE_FILE.exists():
                return json.loads(OMNISANC_STATE_FILE.read_text())
        except Exception as e:
            logger.error(f"Error reading omnisanc state: {e}")
        return {}

    def get_omnisanc_zone(self) -> str:
        """Get current omnisanc zone based on state.

        Returns one of: HOME, STARPORT, LAUNCH, SESSION, LANDING, MISSION
        """
        state = self.get_omnisanc_state()

        if not state.get("course_plotted"):
            return "HOME"

        if state.get("flight_selected") or state.get("session_active"):
            if state.get("needs_review"):
                return "LANDING"
            return "SESSION"

        if state.get("fly_called"):
            return "LAUNCH"

        if state.get("mission_active"):
            return "MISSION"

        return "STARPORT"

    def is_home(self) -> bool:
        """Check if in HOME state (no course plotted)."""
        return not self.get_omnisanc_state().get("course_plotted", False)

    def is_mission_active(self) -> bool:
        """Check if a mission is currently active."""
        return self.get_omnisanc_state().get("mission_active", False)

    # =========================================================================
    # Omnisanc Enable/Disable
    # =========================================================================

    def is_omnisanc_enabled(self) -> bool:
        """Check if omnisanc logic is enabled.

        Omnisanc is ENABLED when the disabled file does NOT exist.
        """
        return not OMNISANC_DISABLED_FILE.exists()

    def enable_omnisanc(self) -> Dict[str, Any]:
        """Enable omnisanc by deleting the disabled file."""
        was_enabled = self.is_omnisanc_enabled()
        try:
            if OMNISANC_DISABLED_FILE.exists():
                OMNISANC_DISABLED_FILE.unlink()
            return {
                "success": True,
                "was_enabled": was_enabled,
                "now_enabled": True,
            }
        except Exception as e:
            logger.error(f"Error enabling omnisanc: {e}")
            return {
                "success": False,
                "error": str(e),
                "was_enabled": was_enabled,
            }

    def disable_omnisanc(self) -> Dict[str, Any]:
        """Disable omnisanc by creating the disabled file."""
        was_enabled = self.is_omnisanc_enabled()
        try:
            OMNISANC_DISABLED_FILE.parent.mkdir(parents=True, exist_ok=True)
            OMNISANC_DISABLED_FILE.write_text("disabled")
            return {
                "success": True,
                "was_enabled": was_enabled,
                "now_enabled": False,
            }
        except Exception as e:
            logger.error(f"Error disabling omnisanc: {e}")
            return {
                "success": False,
                "error": str(e),
                "was_enabled": was_enabled,
            }

    # =========================================================================
    # Metabrainhook State
    # =========================================================================

    def get_metabrainhook_state(self) -> bool:
        """Check if metabrainhook is enabled (on/off)."""
        try:
            if METABRAINHOOK_STATE_FILE.exists():
                return METABRAINHOOK_STATE_FILE.read_text().strip().lower() == "on"
        except Exception as e:
            logger.error(f"Error reading metabrainhook state: {e}")
        return False

    def set_metabrainhook_state(self, on: bool) -> Dict[str, Any]:
        """Set metabrainhook state (on/off).

        Args:
            on: True to enable, False to disable

        Returns:
            Status dict with previous and new state
        """
        previous = self.get_metabrainhook_state()
        try:
            METABRAINHOOK_STATE_FILE.write_text("on" if on else "off")
            return {
                "success": True,
                "previous": previous,
                "current": on,
            }
        except Exception as e:
            logger.error(f"Error writing metabrainhook state: {e}")
            return {
                "success": False,
                "error": str(e),
                "previous": previous,
            }

    # =========================================================================
    # Metabrainhook Prompt
    # =========================================================================

    def get_metabrainhook_prompt(self) -> Optional[str]:
        """Read metabrainhook prompt file content.

        This is the content that gets injected when metabrainhook fires.
        """
        try:
            if METABRAINHOOK_PROMPT_FILE.exists():
                return METABRAINHOOK_PROMPT_FILE.read_text()
        except Exception as e:
            logger.error(f"Error reading metabrainhook prompt: {e}")
        return None

    def set_metabrainhook_prompt(self, content: str) -> Dict[str, Any]:
        """Write metabrainhook prompt file content.

        Args:
            content: The prompt content to inject when metabrainhook fires

        Returns:
            Status dict
        """
        try:
            METABRAINHOOK_PROMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
            METABRAINHOOK_PROMPT_FILE.write_text(content)
            return {
                "success": True,
                "path": str(METABRAINHOOK_PROMPT_FILE),
                "size": len(content),
            }
        except Exception as e:
            logger.error(f"Error writing metabrainhook prompt: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    # =========================================================================
    # Combined Status
    # =========================================================================

    def get_omnisanc_status(self) -> Dict[str, Any]:
        """Get complete omnisanc + metabrainhook status."""
        state = self.get_omnisanc_state()
        return {
            "omnisanc_enabled": self.is_omnisanc_enabled(),
            "zone": self.get_omnisanc_zone(),
            "is_home": self.is_home(),
            "course_plotted": state.get("course_plotted", False),
            "mission_active": state.get("mission_active", False),
            "mission_id": state.get("mission_id"),
            "domain": state.get("domain"),
            "subdomain": state.get("subdomain"),
            "metabrainhook": {
                "enabled": self.get_metabrainhook_state(),
                "prompt_exists": METABRAINHOOK_PROMPT_FILE.exists(),
            },
            "raw_state": state,
        }
