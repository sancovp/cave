"""HookRouter Mixin.

Receives hook signals from paia_* hooks, maintains state, decides responses.
This is the brain - hooks are just signals.
"""
import logging
import time
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from ..capability_resolver import get_capability_context_for_hook

if TYPE_CHECKING:
    from ..config import CAVEConfig
    from ..hooks import HookRegistry

logger = logging.getLogger(__name__)


class HookRouterMixin:
    """Mixin for hook signal routing and state management."""

    config: "CAVEConfig"
    hook_registry: "HookRegistry"
    _hook_state: Dict[str, Any]
    _hook_history: List[Dict[str, Any]]

    def _init_hook_router(self) -> None:
        """Initialize hook router state."""
        from ..hooks import HookRegistry

        self.hook_registry = HookRegistry(self.config.hook_dir)
        self.hook_registry.scan()  # Scan class-based hooks
        self.hook_registry.load_scripts_config()  # Load registered scripts from JSON
        self._hook_state = {}  # Persistent state across hook calls
        self._hook_history = []  # Recent hook events for analysis

        # Ensure inbox_notification is always in posttooluse (perception layer)
        existing = self.config.main_agent_config.active_hooks.get("posttooluse", [])
        if "inbox_notification" not in existing:
            existing.append("inbox_notification")
            self.config.main_agent_config.active_hooks["posttooluse"] = existing

    def handle_hook(self, hook_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming hook signal from paia_* hooks.

        This is the main entry point. Hooks call this, we decide what to do.

        Args:
            hook_type: Type of hook (pretooluse, posttooluse, stop, etc.)
            payload: Data from the hook (tool_name, tool_input, etc.)

        Returns:
            Response dict with at minimum {"result": "continue"|"block"}
            Can include "additionalContext" to inject into Claude
        """
        # Detect OpenClaw source and normalize payload format
        source = payload.pop("source", "claude_code")
        if source == "openclaw":
            payload = self._normalize_openclaw_payload(hook_type, payload)
            self._hook_state["current_source"] = "openclaw"
        else:
            self._hook_state["current_source"] = "claude_code"

        # Normalize hook type to lowercase
        hook_type_lower = hook_type.lower()

        # Get active hooks for this type from main agent config
        active_hook_names = self.config.main_agent_config.active_hooks.get(hook_type_lower, [])

        if not active_hook_names:
            return {"result": "continue", "hook_type": hook_type, "active_hooks": []}

        event = {
            "hook_type": hook_type,
            "payload": payload,
            "ts": time.time(),
        }

        # Record in history (keep last 100)
        self._hook_history.append(event)
        if len(self._hook_history) > 100:
            self._hook_history = self._hook_history[-100:]

        # Get hooks from registry, filtered by active names
        all_hooks = self.hook_registry.get_hooks_for_type(hook_type_lower)
        hooks = [h for h in all_hooks if h.name in active_hook_names]
        additional_context = []
        hooks_called = 0

        # Inject capability recommendations via RAG
        rag_enabled = self._hook_state.get("rag_enabled", True)
        cap_context = get_capability_context_for_hook(hook_type_lower, payload, enabled=rag_enabled)
        if cap_context:
            additional_context.append(cap_context)

        for hook in hooks:
            try:
                # ClaudeCodeHook.__call__ returns dict
                result = hook(payload, self._hook_state)
                hooks_called += 1

                # Collect any context injections
                if result.get("additionalContext"):
                    additional_context.append(result["additionalContext"])

                # Check for block signal
                if result.get("decision") == "block":
                    return {
                        "result": "block",
                        "reason": result.get("reason", "Hook blocked"),
                        "additionalContext": "\n".join(additional_context) if additional_context else None,
                    }
            except Exception as e:
                logger.error(f"Hook {hook.name} failed: {e}")
                continue

        # Check DNA transition (if auto mode active)
        dna_result = self.check_dna_transition()

        # Build response
        response = {
            "result": "continue",
            "hook_type": hook_type,
            "hooks_called": hooks_called,
            "dna": dna_result,
        }

        if additional_context:
            response["additionalContext"] = "\n".join(additional_context)

        return response

    def scan_hooks(self) -> Dict[str, Any]:
        """Rescan hooks directory and update registry."""
        return self.hook_registry.scan()

    def list_hooks(self) -> Dict[str, Any]:
        """List all hooks in registry."""
        return self.hook_registry.list()

    def get_hook_state(self) -> Dict[str, Any]:
        """Get the persistent hook state."""
        return self._hook_state.copy()

    def set_hook_state(self, key: str, value: Any) -> None:
        """Set a value in persistent hook state."""
        self._hook_state[key] = value

    def get_hook_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent hook history."""
        return self._hook_history[-limit:]

    def get_hook_status(self) -> Dict[str, Any]:
        """Get status of hook system."""
        from ..hook_control import HookControl

        return {
            "registry": self.hook_registry.list(),
            "enabled": HookControl.get_all(),
            "state_keys": list(self._hook_state.keys()),
            "history_count": len(self._hook_history),
        }

    def _normalize_openclaw_payload(self, hook_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize OpenClaw payload format to Claude Code format.

        OpenClaw uses pi-coding-agent format:
        - tool_call event: { toolName, toolCallId, input }
        - tool_result event: { toolName, toolCallId, input, content, isError }

        Claude Code format:
        - PreToolUse: { tool_name, tool_input, tool_call_id }
        - PostToolUse: { tool_name, tool_input, tool_result, is_error }
        """
        hook_type_lower = hook_type.lower()
        normalized = payload.copy()

        if hook_type_lower == "pretooluse":
            # OpenClaw: toolName, toolCallId, input
            # Claude: tool_name, tool_input, tool_call_id
            if "toolName" in payload:
                normalized["tool_name"] = payload.get("toolName")
            if "toolCallId" in payload:
                normalized["tool_call_id"] = payload.get("toolCallId")
            if "input" in payload and "tool_input" not in payload:
                normalized["tool_input"] = payload.get("input")

        elif hook_type_lower in ("posttooluse", "posttool"):
            # OpenClaw: toolName, toolCallId, input, content, isError
            # Claude: tool_name, tool_input, tool_result, is_error
            if "toolName" in payload:
                normalized["tool_name"] = payload.get("toolName")
            if "toolCallId" in payload:
                normalized["tool_call_id"] = payload.get("toolCallId")
            if "input" in payload and "tool_input" not in payload:
                normalized["tool_input"] = payload.get("input")
            if "content" in payload and "tool_result" not in payload:
                normalized["tool_result"] = payload.get("content")
            if "isError" in payload:
                normalized["is_error"] = payload.get("isError")

        elif hook_type_lower == "userpromptsubmit":
            # OpenClaw: text, images, source
            # Claude: user_input, images
            if "text" in payload and "user_input" not in payload:
                normalized["user_input"] = payload.get("text")

        # Log the normalization for debugging
        logger.debug(f"Normalized OpenClaw payload for {hook_type}: {list(normalized.keys())}")

        return normalized

    def get_current_source(self) -> str:
        """Get the source of the current/last hook call (openclaw or claude_code)."""
        return self._hook_state.get("current_source", "claude_code")
