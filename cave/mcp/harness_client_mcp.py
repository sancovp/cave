"""PAIA Harness Client MCP - calls harness HTTP server.

Add to gnosys_kit or use standalone. Makes HTTP calls to harness server.
"""
import os
import requests
from typing import Optional
from fastmcp import FastMCP

mcp = FastMCP("paia-harness", "Control PAIA harness (hooks, persona, self commands)")

HARNESS_URL = os.environ.get("PAIA_HARNESS_URL", "http://localhost:8765")


def _get(endpoint: str) -> dict:
    """GET request to harness."""
    resp = requests.get(f"{HARNESS_URL}{endpoint}", timeout=10)
    return resp.json()


def _post(endpoint: str, data: Optional[dict] = None) -> dict:
    """POST request to harness."""
    resp = requests.post(f"{HARNESS_URL}{endpoint}", json=data or {}, timeout=30)
    return resp.json()


def _delete(endpoint: str) -> dict:
    """DELETE request to harness."""
    resp = requests.delete(f"{HARNESS_URL}{endpoint}", timeout=10)
    return resp.json()


# ==================== HOOKS ====================

@mcp.tool()
def hooks_list() -> dict:
    """Get all hook states."""
    return _get("/hooks")


@mcp.tool()
def hooks_enable(hook_type: str) -> dict:
    """Enable a hook. Types: pretooluse, posttooluse, userpromptsubmit, notification, stop, subagentspawn"""
    return _post(f"/hooks/{hook_type}/enable")


@mcp.tool()
def hooks_disable(hook_type: str) -> dict:
    """Disable a hook."""
    return _post(f"/hooks/{hook_type}/disable")


@mcp.tool()
def hooks_toggle(hook_type: str) -> dict:
    """Toggle a hook."""
    return _post(f"/hooks/{hook_type}/toggle")


# ==================== PERSONA ====================

@mcp.tool()
def persona_get() -> dict:
    """Get currently active persona."""
    return _get("/persona")


@mcp.tool()
def persona_activate(name: str) -> dict:
    """Activate a persona by name."""
    return _post(f"/persona/{name}")


@mcp.tool()
def persona_deactivate() -> dict:
    """Deactivate current persona."""
    return _delete("/persona")


# ==================== SELF COMMANDS ====================

@mcp.tool()
def self_restart(
    tmux_session: str = "claude",
    autopoiesis: bool = False,
    resume_enabled: bool = True,
    post_restart_message: str = "ALIVE! Hot restart complete."
) -> dict:
    """Execute configurable restart."""
    return _post("/self/restart", {
        "tmux_session": tmux_session,
        "autopoiesis": autopoiesis,
        "resume_enabled": resume_enabled,
        "post_restart_message": post_restart_message,
    })


@mcp.tool()
def self_compact(
    tmux_session: str = "claude",
    pre_compact_message: str = "",
    post_compact_message: str = ""
) -> dict:
    """Execute configurable compact."""
    return _post("/self/compact", {
        "tmux_session": tmux_session,
        "pre_compact_message": pre_compact_message,
        "post_compact_message": post_compact_message,
    })


@mcp.tool()
def self_inject(
    message: str,
    tmux_session: str = "claude",
    press_enter: bool = True
) -> dict:
    """Inject message into tmux session."""
    return _post("/self/inject", {
        "tmux_session": tmux_session,
        "message": message,
        "press_enter": press_enter,
    })


# ==================== HARNESS ====================

@mcp.tool()
def harness_status() -> dict:
    """Get harness status."""
    return _get("/status")


@mcp.tool()
def harness_spawn(
    agent_command: str = "claude",
    working_directory: str = "/home/GOD"
) -> dict:
    """Spawn agent with harness."""
    return _post("/spawn", {
        "agent_command": agent_command,
        "working_directory": working_directory,
    })


@mcp.tool()
def harness_send(prompt: str, timeout: Optional[float] = None) -> dict:
    """Send prompt to agent and get response."""
    return _post("/send", {"prompt": prompt, "timeout": timeout})


@mcp.tool()
def harness_capture() -> dict:
    """Capture current terminal content."""
    return _get("/capture")


@mcp.tool()
def harness_stop() -> dict:
    """Stop the harness."""
    return _post("/stop")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
