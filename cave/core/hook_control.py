"""Hook control via file flag.

Pattern: Toggle individual hooks on/off, hooks check before executing.
"""
import json
from pathlib import Path
from typing import Literal

HOOK_CONTROL_CONFIG = Path("/tmp/hook_control.json")

HookType = Literal[
    "pretooluse",
    "posttooluse",
    "userpromptsubmit",
    "notification",
    "stop",
    "subagentspawn"
]

ALL_HOOKS: list[HookType] = [
    "pretooluse",
    "posttooluse",
    "userpromptsubmit",
    "notification",
    "stop",
    "subagentspawn"
]


class HookControl:
    """Controls hook activation via config file."""

    @staticmethod
    def _load() -> dict[str, bool]:
        """Load hook config, defaulting all to False."""
        if HOOK_CONTROL_CONFIG.exists():
            return json.loads(HOOK_CONTROL_CONFIG.read_text())
        return {h: False for h in ALL_HOOKS}

    @staticmethod
    def _save(config: dict[str, bool]) -> None:
        """Save hook config."""
        HOOK_CONTROL_CONFIG.write_text(json.dumps(config, indent=2))

    @staticmethod
    def enable(hook_type: HookType) -> None:
        """Enable a specific hook."""
        config = HookControl._load()
        config[hook_type] = True
        HookControl._save(config)

    @staticmethod
    def disable(hook_type: HookType) -> None:
        """Disable a specific hook."""
        config = HookControl._load()
        config[hook_type] = False
        HookControl._save(config)

    @staticmethod
    def toggle(hook_type: HookType) -> bool:
        """Toggle a hook, return new state."""
        config = HookControl._load()
        config[hook_type] = not config.get(hook_type, False)
        HookControl._save(config)
        return config[hook_type]

    @staticmethod
    def is_enabled(hook_type: HookType) -> bool:
        """Check if a specific hook is enabled."""
        config = HookControl._load()
        return config.get(hook_type, False)

    @staticmethod
    def get_all() -> dict[str, bool]:
        """Get all hook states."""
        return HookControl._load()

    @staticmethod
    def enable_all() -> None:
        """Enable all hooks."""
        HookControl._save({h: True for h in ALL_HOOKS})

    @staticmethod
    def disable_all() -> None:
        """Disable all hooks."""
        HookControl._save({h: False for h in ALL_HOOKS})
