"""Relay scripts and installers for forwarding provider hooks into CAVE."""

__all__ = [
    "CLAUDE_CODE_RELAY_EVENTS",
    "CODEX_RELAY_EVENTS",
    "LEGACY_CLAUDE_CODE_RELAY_EVENTS",
    "build_hooks_config",
    "paia_script_name",
    "render_paia_script",
    "relay_main",
    "write_hooks_config",
    "write_relay_set",
]


def __getattr__(name: str):
    """Load PAIA relay helpers lazily so `python -m cave.relays.paia` stays clean."""
    if name in __all__:
        from . import paia

        return getattr(paia, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
