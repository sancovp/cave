"""ClaudeCodeHook - Define hooks in code.

Hooks receive signals from Claude Code (via HTTP relay) and return decisions.
This lets you define hook behavior as Python classes in CAVE.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class HookType(str, Enum):
    """Claude Code hook types."""
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    NOTIFICATION = "Notification"
    STOP = "Stop"
    SUBAGENT_SPAWN = "SubagentSpawn"


class HookDecision(str, Enum):
    """What the hook decides."""
    APPROVE = "approve"    # Let it proceed
    BLOCK = "block"        # Stop/reject
    CONTINUE = "continue"  # Continue (for non-stop hooks)


@dataclass
class HookResult:
    """Result from a hook."""
    decision: HookDecision
    reason: Optional[str] = None
    additional_context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Claude Code response format."""
        result = {"decision": self.decision.value}
        if self.reason:
            result["reason"] = self.reason
        if self.additional_context:
            result["additionalContext"] = self.additional_context
        return result


class ClaudeCodeHook(ABC):
    """Base class for hooks defined in code.

    Subclass this to create hooks:

        class MyStopHook(ClaudeCodeHook):
            hook_type = HookType.STOP

            def handle(self, payload, state):
                if some_condition:
                    return HookResult(HookDecision.BLOCK, reason="Not yet")
                return HookResult(HookDecision.APPROVE)
    """

    hook_type: HookType = None  # Override in subclass
    name: str = None  # Optional name, defaults to class name

    def __init__(self, name: str = None):
        self.name = name or self.__class__.__name__
        if self.hook_type is None:
            raise ValueError(f"{self.__class__.__name__} must define hook_type")

    @abstractmethod
    def handle(self, payload: Dict[str, Any], state: Dict[str, Any]) -> HookResult:
        """Handle the hook. Override this.

        Args:
            payload: Data from Claude Code (tool_name, tool_input, etc.)
            state: Persistent state dict (shared across hook calls)

        Returns:
            HookResult with decision and optional reason/context
        """
        pass

    def __call__(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        """Make hook callable, returns dict for HTTP response."""
        result = self.handle(payload, state)
        return result.to_dict()


# =============================================================================
# SCRIPT HOOK ADAPTER
# =============================================================================

import json
import subprocess


class ScriptHookAdapter:
    """Wraps a standalone script (with main()) to be callable like ClaudeCodeHook.

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
                timeout=5,  # Don't let hooks hang forever
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
    instance: Optional[ClaudeCodeHook] = None
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

            # Find ClaudeCodeHook subclass
            hook_class = None
            for member_name, obj in inspect.getmembers(module):
                if (isinstance(obj, type) and
                    issubclass(obj, ClaudeCodeHook) and
                    obj != ClaudeCodeHook):
                    hook_class = obj
                    break

            if hook_class is None:
                return RegistryEntry(
                    name=name, path=py_file, hook_type="unknown",
                    hook_class=None, error="No ClaudeCodeHook subclass found"
                )

            # Get hook type (normalize to lowercase)
            hook_type_value = hook_class.hook_type
            if isinstance(hook_type_value, HookType):
                hook_type_str = hook_type_value.value.lower()
            elif isinstance(hook_type_value, str):
                hook_type_str = hook_type_value.lower()
            else:
                hook_type_str = "unknown"

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
            List of callable hooks (ClaudeCodeHook instances or ScriptHookAdapters)
        """
        hook_type_lower = hook_type.lower()
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

        hook_type_lower = hook_type.lower()
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
