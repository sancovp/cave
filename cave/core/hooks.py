"""Provider-neutral code-agent hooks.

Hooks receive lifecycle signals from terminal code agents via HTTP relay and
return decisions. Claude Code remains the first supported provider, but the
base classes and event vocabulary are intentionally provider-neutral so CAVE
can route Codex and other agent hooks through the same registry.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class HookProvider(str, Enum):
    """Known hook-producing code-agent providers."""
    CAVE = "cave"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    OPENCLAW = "openclaw"


class HookType(str, Enum):
    """Provider-neutral hook event names.

    Values intentionally use provider wire names where possible. Claude Code's
    current hook reference has the widest event vocabulary, so this enum is the
    superset CAVE routes through. Providers can support a subset.
    """
    SESSION_START = "SessionStart"
    SETUP = "Setup"
    INSTRUCTIONS_LOADED = "InstructionsLoaded"
    PRE_TOOL_USE = "PreToolUse"
    PERMISSION_REQUEST = "PermissionRequest"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    POST_TOOL_BATCH = "PostToolBatch"
    PERMISSION_DENIED = "PermissionDenied"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    USER_PROMPT_EXPANSION = "UserPromptExpansion"
    MESSAGE_DISPLAY = "MessageDisplay"
    NOTIFICATION = "Notification"
    SUBAGENT_START = "SubagentStart"
    SUBAGENT_STOP = "SubagentStop"
    TASK_CREATED = "TaskCreated"
    TASK_COMPLETED = "TaskCompleted"
    STOP = "Stop"
    STOP_FAILURE = "StopFailure"
    TEAMMATE_IDLE = "TeammateIdle"
    CONFIG_CHANGE = "ConfigChange"
    CWD_CHANGED = "CwdChanged"
    FILE_CHANGED = "FileChanged"
    WORKTREE_CREATE = "WorktreeCreate"
    WORKTREE_REMOVE = "WorktreeRemove"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    SESSION_END = "SessionEnd"
    ELICITATION = "Elicitation"
    ELICITATION_RESULT = "ElicitationResult"
    # Legacy CAVE/Claude-era name kept so old hook files still load.
    SUBAGENT_SPAWN = "SubagentSpawn"


class HookDecision(str, Enum):
    """Provider-neutral hook decision vocabulary."""
    APPROVE = "approve"    # Let it proceed
    BLOCK = "block"        # Stop/reject
    CONTINUE = "continue"  # Continue (for non-stop hooks)


@dataclass
class HookResult:
    """Provider-neutral result from a code-agent hook."""
    decision: HookDecision
    reason: Optional[str] = None
    additional_context: Optional[str] = None
    system_message: Optional[str] = None
    continue_: Optional[bool] = None
    stop_reason: Optional[str] = None
    suppress_output: Optional[bool] = None
    updated_input: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to CAVE's internal hook response format."""
        result = {"decision": self.decision.value}
        if self.reason:
            result["reason"] = self.reason
        if self.additional_context:
            result["additionalContext"] = self.additional_context
        if self.system_message:
            result["systemMessage"] = self.system_message
        if self.continue_ is not None:
            result["continue"] = self.continue_
        if self.stop_reason:
            result["stopReason"] = self.stop_reason
        if self.suppress_output is not None:
            result["suppressOutput"] = self.suppress_output
        if self.updated_input is not None:
            result["updatedInput"] = self.updated_input
        if self.metadata:
            result["metadata"] = self.metadata
        return result


class CodeAgentHook(ABC):
    """Base class for hooks defined in code.

    Subclass this to create hooks:

        class MyStopHook(CodeAgentHook):
            hook_type = HookType.STOP

            def handle(self, payload, state):
                if some_condition:
                    return HookResult(HookDecision.BLOCK, reason="Not yet")
                return HookResult(HookDecision.APPROVE)
    """

    provider: Optional[HookProvider] = None
    hook_type: Optional[HookType] = None  # Override in subclass
    name: str = None  # Optional name, defaults to class name

    def __init__(self, name: str = None):
        self.name = name or self.__class__.__name__
        if self.hook_type is None:
            raise ValueError(f"{self.__class__.__name__} must define hook_type")

    @abstractmethod
    def handle(self, payload: Dict[str, Any], state: Dict[str, Any]) -> HookResult:
        """Handle the hook. Override this.

        Args:
            payload: Normalized provider event payload.
            state: Persistent state dict (shared across hook calls)

        Returns:
            HookResult with decision and optional reason/context
        """
        pass

    def __call__(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        """Make hook callable, returns dict for HTTP response."""
        result = self.handle(payload, state)
        return result.to_dict()


class ClaudeCodeHook(CodeAgentHook):
    """Compatibility base for existing Claude Code hooks."""

    provider = HookProvider.CLAUDE_CODE


class CodexHook(CodeAgentHook):
    """Base class for Codex-specific hooks when provider behavior matters."""

    provider = HookProvider.CODEX


CLAUDE_CODE_HOOK_TYPES = frozenset(
    hook.value
    for hook in HookType
    if hook is not HookType.SUBAGENT_SPAWN
)

CODEX_HOOK_TYPES = frozenset({
    HookType.SESSION_START.value,
    HookType.PRE_TOOL_USE.value,
    HookType.PERMISSION_REQUEST.value,
    HookType.POST_TOOL_USE.value,
    HookType.PRE_COMPACT.value,
    HookType.POST_COMPACT.value,
    HookType.USER_PROMPT_SUBMIT.value,
    HookType.SUBAGENT_START.value,
    HookType.SUBAGENT_STOP.value,
    HookType.STOP.value,
})

PROVIDER_HOOK_TYPES = {
    HookProvider.CLAUDE_CODE.value: CLAUDE_CODE_HOOK_TYPES,
    HookProvider.CODEX.value: CODEX_HOOK_TYPES,
}


def canonical_hook_type(hook_type: Any) -> str:
    """Return the canonical wire name for a hook event."""
    if isinstance(hook_type, HookType):
        return hook_type.value

    hook_type_str = str(hook_type)
    for known in HookType:
        if known.value.lower() == hook_type_str.lower():
            return known.value
    return hook_type_str


def hook_type_key(hook_type: Any) -> str:
    """Normalize hook event names for registry/config keys."""
    return canonical_hook_type(hook_type).lower()


def normalize_provider(provider: Any) -> str:
    """Normalize provider names used by hook relays."""
    if isinstance(provider, HookProvider):
        return provider.value
    provider_str = str(provider or HookProvider.CLAUDE_CODE.value).lower()
    if provider_str in ("claude", "claude-code", "claude_code"):
        return HookProvider.CLAUDE_CODE.value
    if provider_str in ("codex", "openai_codex", "openai-codex"):
        return HookProvider.CODEX.value
    if provider_str in ("openclaw", "open_claw"):
        return HookProvider.OPENCLAW.value
    return provider_str


def get_hook_types_for_provider(provider: Any) -> frozenset:
    """Return the hook event set supported by a provider."""
    return PROVIDER_HOOK_TYPES.get(normalize_provider(provider), frozenset())


def format_hook_response(response: Dict[str, Any], provider: Any, hook_type: Any) -> Dict[str, Any]:
    """Translate CAVE's internal hook response to provider-facing JSON."""
    provider_name = normalize_provider(provider)
    if provider_name == HookProvider.CODEX.value:
        return _format_codex_response(response, hook_type)
    return response


def _format_codex_response(response: Dict[str, Any], hook_type: Any) -> Dict[str, Any]:
    """Translate CAVE hook results to Codex stdout JSON shape."""
    event_name = canonical_hook_type(hook_type)
    decision = response.get("decision")
    blocked = response.get("result") == "block" or decision == HookDecision.BLOCK.value
    additional_context = response.get("additionalContext")
    reason = response.get("reason") or response.get("stopReason")

    result: Dict[str, Any] = {}
    if response.get("systemMessage"):
        result["systemMessage"] = response["systemMessage"]
    if "continue" in response:
        result["continue"] = response["continue"]
    if response.get("stopReason"):
        result["stopReason"] = response["stopReason"]
    if response.get("suppressOutput") is not None:
        result["suppressOutput"] = response["suppressOutput"]

    if blocked:
        result["decision"] = "block"
        if reason:
            result["reason"] = reason

    if event_name == HookType.PERMISSION_REQUEST.value:
        if blocked:
            result["hookSpecificOutput"] = {
                "hookEventName": event_name,
                "decision": {
                    "behavior": "deny",
                    "message": reason or "Blocked by CAVE hook",
                },
            }
        elif decision == HookDecision.APPROVE.value:
            result["hookSpecificOutput"] = {
                "hookEventName": event_name,
                "decision": {"behavior": "allow"},
            }
        return result

    if event_name == HookType.PRE_TOOL_USE.value and response.get("updatedInput") is not None:
        result["hookSpecificOutput"] = {
            "hookEventName": event_name,
            "permissionDecision": "allow",
            "updatedInput": response["updatedInput"],
        }
        return result

    if event_name == HookType.PRE_TOOL_USE.value and blocked:
        result["hookSpecificOutput"] = {
            "hookEventName": event_name,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason or "Blocked by CAVE hook",
        }
        return result

    if additional_context:
        result["hookSpecificOutput"] = {
            "hookEventName": event_name,
            "additionalContext": additional_context,
        }

    return result


# =============================================================================
# SCRIPT HOOK ADAPTER
# =============================================================================

import json
import subprocess


class ScriptHookAdapter:
    """Wraps a standalone script (with main()) to be callable like CodeAgentHook.

    This enables backwards compatibility - existing scripts that read JSON from
    stdin and print JSON to stdout can be registered and called the same way
    as class-based hooks.
    """

    def __init__(self, name: str, hook_type: str, script_path: Path):
        self.name = name
        self.hook_type = hook_type
        self.script_path = script_path

    def __call__(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        """Run the script as subprocess, passing payload as JSON stdin."""
        try:
            result = subprocess.run(
                ["python3", str(self.script_path)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes — dragonbones compilation can be slow
            )

            if result.returncode == 2:
                # Exit code 2 = BLOCK signal (Claude Code hook convention)
                return {"decision": "block", "reason": result.stderr.strip() if result.stderr else "Blocked by script"}
            elif result.returncode != 0:
                # Other non-zero = script error, approve to not break things
                return {"decision": "approve", "error": result.stderr[:200] if result.stderr else "Script failed"}

            # Parse stdout as JSON
            if result.stdout.strip():
                return json.loads(result.stdout)
            return {"decision": "approve"}

        except subprocess.TimeoutExpired:
            return {"decision": "approve", "error": "Script timed out"}
        except json.JSONDecodeError as e:
            return {"decision": "approve", "error": f"Invalid JSON from script: {e}"}
        except Exception as e:
            return {"decision": "approve", "error": str(e)}


# =============================================================================
# HOOK REGISTRY
# =============================================================================

import importlib.util
import inspect
import logging
import os
import traceback
from dataclasses import field as dataclass_field

logger = logging.getLogger(__name__)


@dataclass
class RegistryEntry:
    """Entry in the hook registry."""
    name: str
    path: Path
    hook_type: str  # lowercase: "stop", "pretooluse", etc.
    hook_class: type
    instance: Optional[CodeAgentHook] = None
    error: Optional[str] = None


class HookRegistry:
    """Registry of hook files in cave_hooks/ directory.

    Scans on startup and on-demand via scan().
    Caches hook instances for reuse.
    Supports both class-based hooks and registered scripts.
    """

    def __init__(self, hooks_dir: Path = None):
        self.hooks_dir = hooks_dir or Path(
            os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
        ) / "cave_hooks"
        self._registry: Dict[str, RegistryEntry] = {}
        self._scripts: Dict[str, ScriptHookAdapter] = {}  # Registered script hooks
        self._scripts_config_path = self.hooks_dir / "scripts.json"

    def scan(self) -> Dict[str, Any]:
        """Scan hooks directory and rebuild registry.

        Returns summary of what was found.
        """
        self._registry.clear()

        if not self.hooks_dir.exists():
            self.hooks_dir.mkdir(parents=True, exist_ok=True)
            return {"scanned": 0, "found": 0, "errors": [], "hooks": {}}

        scanned = 0
        found = 0
        errors = []

        for py_file in self.hooks_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            scanned += 1
            entry = self._load_entry(py_file)

            if entry.error:
                errors.append({"file": py_file.name, "error": entry.error})
            else:
                found += 1

            self._registry[entry.name] = entry

        # Also load script registrations from scripts.json
        scripts_result = self.load_scripts_config()

        return {
            "scanned": scanned,
            "found": found,
            "errors": errors + scripts_result.get("errors", []),
            "scripts_loaded": scripts_result.get("loaded", 0),
            "hooks": {
                name: {
                    "path": str(e.path),
                    "hook_type": e.hook_type,
                    "loaded": e.instance is not None,
                    "error": e.error,
                }
                for name, e in self._registry.items()
            }
        }

    def _load_entry(self, py_file: Path) -> RegistryEntry:
        """Load a single hook file into a registry entry."""
        name = py_file.stem

        try:
            spec = importlib.util.spec_from_file_location(name, py_file)
            if spec is None or spec.loader is None:
                return RegistryEntry(
                    name=name, path=py_file, hook_type="unknown",
                    hook_class=None, error="Could not load module spec"
                )

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find CodeAgentHook subclass
            hook_class = None
            for member_name, obj in inspect.getmembers(module):
                if (isinstance(obj, type) and
                    issubclass(obj, CodeAgentHook) and
                    obj not in (CodeAgentHook, ClaudeCodeHook, CodexHook) and
                    not inspect.isabstract(obj)):
                    hook_class = obj
                    break

            if hook_class is None:
                return RegistryEntry(
                    name=name, path=py_file, hook_type="unknown",
                    hook_class=None, error="No CodeAgentHook subclass found"
                )

            # Get hook type (normalize to lowercase)
            hook_type_value = hook_class.hook_type
            hook_type_str = hook_type_key(hook_type_value) if hook_type_value else "unknown"

            return RegistryEntry(
                name=name,
                path=py_file,
                hook_type=hook_type_str,
                hook_class=hook_class,
                instance=None,
                error=None,
            )

        except Exception as e:
            logger.error(f"Failed to load hook {py_file}: {e}\n{traceback.format_exc()}")
            return RegistryEntry(
                name=name, path=py_file, hook_type="unknown",
                hook_class=None, error=str(e)
            )

    def get_hooks_for_type(self, hook_type: str) -> List:
        """Get all hooks matching a hook type, instantiating if needed.

        Args:
            hook_type: lowercase hook type ("stop", "pretooluse", etc.)

        Returns:
            List of callable hooks (CodeAgentHook instances or ScriptHookAdapters)
        """
        hook_type_lower = hook_type_key(hook_type)
        matching = []

        # Class-based hooks from registry
        for entry in self._registry.values():
            if entry.hook_type == hook_type_lower and entry.hook_class is not None:
                # Lazy instantiation
                if entry.instance is None:
                    try:
                        entry.instance = entry.hook_class()
                    except Exception as e:
                        logger.error(f"Failed to instantiate {entry.name}: {e}")
                        entry.error = f"Instantiation failed: {e}"
                        continue

                matching.append(entry.instance)

        # Script hooks (already instantiated adapters)
        for adapter in self._scripts.values():
            if adapter.hook_type == hook_type_lower:
                matching.append(adapter)

        return matching

    def list(self) -> Dict[str, Any]:
        """List all hooks in registry."""
        return {
            "hooks_dir": str(self.hooks_dir),
            "count": len(self._registry),
            "hooks": {
                name: {
                    "path": str(e.path),
                    "hook_type": e.hook_type,
                    "loaded": e.instance is not None,
                    "error": e.error,
                }
                for name, e in self._registry.items()
            }
        }

    def get(self, name: str) -> Optional[RegistryEntry]:
        """Get a specific registry entry by name."""
        return self._registry.get(name)

    def register_script(
        self,
        name: str,
        hook_type: str,
        path: str,
    ) -> Dict[str, Any]:
        """Register a standalone script as a hook.

        This enables backwards compatibility with existing scripts that use
        the stdin/stdout JSON contract (main() reads JSON, prints JSON).

        Args:
            name: Unique name for this hook (used in active_hooks)
            hook_type: Hook type ("stop", "pretooluse", etc.)
            path: Path to the Python script

        Returns:
            Registration result dict
        """
        script_path = Path(path)
        if not script_path.exists():
            return {"success": False, "error": f"Script not found: {path}"}

        hook_type_lower = hook_type_key(hook_type)
        adapter = ScriptHookAdapter(name, hook_type_lower, script_path)
        self._scripts[name] = adapter

        return {
            "success": True,
            "name": name,
            "hook_type": hook_type_lower,
            "path": str(script_path),
        }

    def unregister_script(self, name: str) -> Dict[str, Any]:
        """Unregister a script hook."""
        if name in self._scripts:
            del self._scripts[name]
            return {"success": True, "name": name}
        return {"success": False, "error": f"Script not registered: {name}"}

    def list_scripts(self) -> Dict[str, Any]:
        """List all registered script hooks."""
        return {
            "count": len(self._scripts),
            "scripts": {
                name: {
                    "hook_type": adapter.hook_type,
                    "path": str(adapter.script_path),
                }
                for name, adapter in self._scripts.items()
            }
        }

    def load_scripts_config(self) -> Dict[str, Any]:
        """Load script registrations from JSON config file.

        Config format:
        {
            "hook_name": {"hook_type": "stop", "path": "/path/to/script.py"},
            ...
        }
        """
        if not self._scripts_config_path.exists():
            return {"loaded": 0, "errors": []}

        try:
            config = json.loads(self._scripts_config_path.read_text())
        except json.JSONDecodeError as e:
            return {"loaded": 0, "errors": [f"Invalid JSON: {e}"]}

        loaded = 0
        errors = []

        for name, entry in config.items():
            hook_type = entry.get("hook_type")
            path = entry.get("path")

            if not hook_type or not path:
                errors.append(f"{name}: missing hook_type or path")
                continue

            result = self.register_script(name, hook_type, path)
            if result.get("success"):
                loaded += 1
            else:
                errors.append(f"{name}: {result.get('error')}")

        return {"loaded": loaded, "errors": errors}

    def save_scripts_config(self) -> Dict[str, Any]:
        """Save current script registrations to JSON config file."""
        config = {
            name: {
                "hook_type": adapter.hook_type,
                "path": str(adapter.script_path),
            }
            for name, adapter in self._scripts.items()
        }

        self._scripts_config_path.parent.mkdir(parents=True, exist_ok=True)
        self._scripts_config_path.write_text(json.dumps(config, indent=2))

        return {"saved": len(config), "path": str(self._scripts_config_path)}
