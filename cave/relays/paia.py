"""PAIA hook relays for forwarding code-agent hooks into CAVE.

The relay pattern is intentionally thin:

1. A provider hook script reads one JSON object from stdin.
2. It adds `source=<provider>` and POSTs the payload to CAVE's `/hook/{type}`.
3. It translates CAVE's response back into the provider's hook contract.

Claude Code and Codex both support command hooks, but their output contracts
are not identical. Keep that translation here so generated `paia_*` scripts can
stay small and provider-neutral.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from cave.core.hooks import (
    CODEX_HOOK_TYPES,
    CLAUDE_CODE_HOOK_TYPES,
    HookProvider,
    HookType,
    canonical_hook_type,
    format_hook_response,
    hook_type_key,
    normalize_provider,
)


CLAUDE_CODE_RELAY_EVENTS: tuple[str, ...] = (
    HookType.SESSION_START.value,
    HookType.SETUP.value,
    HookType.INSTRUCTIONS_LOADED.value,
    HookType.USER_PROMPT_SUBMIT.value,
    HookType.USER_PROMPT_EXPANSION.value,
    HookType.MESSAGE_DISPLAY.value,
    HookType.PRE_TOOL_USE.value,
    HookType.PERMISSION_REQUEST.value,
    HookType.POST_TOOL_USE.value,
    HookType.POST_TOOL_USE_FAILURE.value,
    HookType.POST_TOOL_BATCH.value,
    HookType.PERMISSION_DENIED.value,
    HookType.NOTIFICATION.value,
    HookType.SUBAGENT_START.value,
    HookType.SUBAGENT_STOP.value,
    HookType.TASK_CREATED.value,
    HookType.TASK_COMPLETED.value,
    HookType.STOP.value,
    HookType.STOP_FAILURE.value,
    HookType.TEAMMATE_IDLE.value,
    HookType.CONFIG_CHANGE.value,
    HookType.CWD_CHANGED.value,
    HookType.FILE_CHANGED.value,
    HookType.WORKTREE_CREATE.value,
    HookType.WORKTREE_REMOVE.value,
    HookType.PRE_COMPACT.value,
    HookType.POST_COMPACT.value,
    HookType.SESSION_END.value,
    HookType.ELICITATION.value,
    HookType.ELICITATION_RESULT.value,
)

LEGACY_CLAUDE_CODE_RELAY_EVENTS: tuple[str, ...] = (
    HookType.SUBAGENT_SPAWN.value,
)

CODEX_RELAY_EVENTS: tuple[str, ...] = (
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
)

DEFAULT_CAVE_URL = "http://localhost:18765"
DEFAULT_TIMEOUT_SECONDS = 600
CLAUDE_FILE_CHANGED_MATCHER = (
    "CLAUDE.md|AGENTS.md|.env|.envrc|settings.json|settings.local.json|"
    "hooks.json|config.toml"
)


def relay_events_for_provider(provider: Any, include_legacy: bool = True) -> tuple[str, ...]:
    """Return the relay event set for a provider in stable docs order."""
    provider_name = normalize_provider(provider)
    if provider_name == HookProvider.CLAUDE_CODE.value:
        events = CLAUDE_CODE_RELAY_EVENTS
        if include_legacy:
            events = events + LEGACY_CLAUDE_CODE_RELAY_EVENTS
        return events
    if provider_name == HookProvider.CODEX.value:
        return CODEX_RELAY_EVENTS
    raise ValueError(f"Unsupported relay provider: {provider!r}")


def paia_script_name(hook_event: Any) -> str:
    """Return the conventional paia relay filename for a hook event."""
    return f"paia_{hook_type_key(hook_event)}.py"


def render_paia_script(
    provider: Any,
    hook_event: Any,
    *,
    cave_package_root: str | Path | None = None,
) -> str:
    """Render a thin paia relay script for one provider hook event."""
    provider_name = normalize_provider(provider)
    event_name = canonical_hook_type(hook_event)
    package_root = "" if cave_package_root is None else str(Path(cave_package_root))
    return (
        "#!/usr/bin/env python3\n"
        f'"""Forward {provider_name} {event_name} hook events into CAVE."""\n'
        "import sys\n"
        "\n"
        f"CAVE_PACKAGE_ROOT = {package_root!r}\n"
        "if CAVE_PACKAGE_ROOT and CAVE_PACKAGE_ROOT not in sys.path:\n"
        "    sys.path.insert(0, CAVE_PACKAGE_ROOT)\n"
        "\n"
        "from cave.relays.paia import relay_main\n"
        "\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        f"    relay_main(provider={provider_name!r}, hook_event={event_name!r})\n"
    )


def call_cave(
    hook_event: Any,
    data: Mapping[str, Any],
    *,
    cave_url: str | None = None,
    timeout: float | None = None,
) -> Dict[str, Any]:
    """POST a hook event to CAVE and fail open if CAVE is offline."""
    base_url = (cave_url or os.environ.get("CAVE_URL") or DEFAULT_CAVE_URL).rstrip("/")
    hook_endpoint = hook_type_key(hook_event)
    timeout_seconds = float(os.environ.get("CAVE_HOOK_TIMEOUT", timeout or DEFAULT_TIMEOUT_SECONDS))

    try:
        payload = json.dumps(dict(data)).encode()
        req = urllib.request.Request(
            f"{base_url}/hook/{hook_endpoint}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError:
        return {"result": "continue", "cave": "offline"}
    except Exception as exc:
        return {"result": "continue", "error": str(exc)}


def relay_main(provider: Any, hook_event: Any) -> None:
    """Entry point used by generated paia relay scripts."""
    provider_name = normalize_provider(provider)
    event_name = canonical_hook_type(hook_event)
    hook_input = _read_stdin_json()
    hook_input.setdefault("source", provider_name)
    hook_input.setdefault("hook_event_name", event_name)

    cave_result = call_cave(event_name, hook_input)

    if provider_name == HookProvider.CODEX.value:
        _emit_codex_result(event_name, cave_result)
    elif provider_name == HookProvider.CLAUDE_CODE.value:
        _emit_claude_code_result(event_name, cave_result)
    else:
        _emit_claude_code_result(event_name, cave_result)


def build_hooks_config(
    provider: Any,
    script_dir: str | Path,
    *,
    events: Sequence[str] | None = None,
    include_legacy: bool = True,
    file_changed_matcher: str = CLAUDE_FILE_CHANGED_MATCHER,
    status_prefix: str = "CAVE",
) -> Dict[str, Any]:
    """Build provider hook configuration pointing at generated paia scripts."""
    provider_name = normalize_provider(provider)
    relay_events = tuple(events or relay_events_for_provider(provider_name, include_legacy=include_legacy))
    scripts = Path(script_dir)

    config: Dict[str, Any] = {"hooks": {}}
    for event in relay_events:
        event_name = canonical_hook_type(event)
        hook_path = scripts / paia_script_name(event_name)
        hook_entry: Dict[str, Any] = {
            "hooks": [{
                "type": "command",
                "command": f"python3 {shlex.quote(str(hook_path))}",
                "statusMessage": f"{status_prefix}: {event_name}",
            }]
        }
        if provider_name == HookProvider.CLAUDE_CODE.value and event_name == HookType.FILE_CHANGED.value:
            hook_entry["matcher"] = file_changed_matcher
        config["hooks"].setdefault(event_name, []).append(hook_entry)

    return config


def write_relay_set(
    provider: Any,
    output_dir: str | Path,
    *,
    events: Sequence[str] | None = None,
    include_legacy: bool = True,
    cave_package_root: str | Path | None = None,
) -> list[Path]:
    """Write generated paia relay scripts for a provider."""
    provider_name = normalize_provider(provider)
    relay_events = tuple(events or relay_events_for_provider(provider_name, include_legacy=include_legacy))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for event in relay_events:
        path = destination / paia_script_name(event)
        path.write_text(
            render_paia_script(provider_name, event, cave_package_root=cave_package_root)
        )
        path.chmod(0o755)
        written.append(path)
    return written


def write_hooks_config(
    provider: Any,
    output_path: str | Path,
    script_dir: str | Path,
    *,
    events: Sequence[str] | None = None,
    include_legacy: bool = True,
) -> Path:
    """Write hooks.json for generated paia relays."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = build_hooks_config(
        provider,
        script_dir,
        events=events,
        include_legacy=include_legacy,
    )
    path.write_text(json.dumps(config, indent=2) + "\n")
    return path


def install_provider_relays(
    provider: Any,
    root: str | Path,
    *,
    cave_package_root: str | Path | None = None,
    include_legacy: bool = True,
) -> Dict[str, Any]:
    """Install provider-local paia scripts and hook config under a project root."""
    provider_name = normalize_provider(provider)
    root_path = Path(root)
    if provider_name == HookProvider.CODEX.value:
        config_dir = root_path / ".codex"
        hook_dir = config_dir / "hooks"
        config_path = config_dir / "hooks.json"
    elif provider_name == HookProvider.CLAUDE_CODE.value:
        config_dir = root_path / ".claude"
        hook_dir = config_dir / "hooks"
        config_path = config_dir / "settings.json"
    else:
        raise ValueError(f"Unsupported relay provider: {provider!r}")

    written = write_relay_set(
        provider_name,
        hook_dir,
        include_legacy=include_legacy,
        cave_package_root=cave_package_root,
    )
    write_hooks_config(
        provider_name,
        config_path,
        hook_dir,
        include_legacy=include_legacy,
    )
    return {
        "provider": provider_name,
        "root": str(root_path),
        "hook_dir": str(hook_dir),
        "config_path": str(config_path),
        "scripts": [str(path) for path in written],
    }


def _read_stdin_json() -> Dict[str, Any]:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _emit_codex_result(hook_event: str, cave_result: Mapping[str, Any]) -> None:
    response = dict(cave_result)
    if not _looks_like_provider_response(response):
        response = format_hook_response(response, HookProvider.CODEX, hook_event)

    if _has_meaningful_output(response):
        sys.stdout.write(json.dumps(response) + "\n")
    sys.exit(0)


def _emit_claude_code_result(hook_event: str, cave_result: Mapping[str, Any]) -> None:
    response = dict(cave_result)
    blocked = response.get("result") == "block" or response.get("decision") == "block"
    if blocked:
        reason = response.get("reason") or response.get("stopReason") or "Blocked by CAVE"
        context = response.get("additionalContext", "")
        sys.stderr.write(str(reason) + "\n")
        if context:
            sys.stderr.write(str(context) + "\n")
        sys.exit(2)

    output = _claude_json_output(hook_event, response)
    if output:
        sys.stdout.write(json.dumps(output) + "\n")
    sys.exit(0)


def _claude_json_output(hook_event: str, response: Mapping[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for key in ("systemMessage", "continue", "stopReason", "suppressOutput"):
        if key in response:
            output[key] = response[key]

    if "hookSpecificOutput" in response:
        output["hookSpecificOutput"] = response["hookSpecificOutput"]
    elif response.get("additionalContext"):
        output["hookSpecificOutput"] = {
            "hookEventName": canonical_hook_type(hook_event),
            "additionalContext": response["additionalContext"],
        }

    return output


def _looks_like_provider_response(response: Mapping[str, Any]) -> bool:
    return any(key in response for key in ("hookSpecificOutput", "systemMessage", "continue", "stopReason"))


def _has_meaningful_output(response: Mapping[str, Any]) -> bool:
    ignored = {"result", "hook_type", "active_hooks", "hooks_called", "dna", "cave"}
    return any(key not in ignored for key, value in response.items() if value not in (None, "", [], {}))


def _validate_event_sets() -> None:
    claude_events = set(CLAUDE_CODE_RELAY_EVENTS)
    if claude_events != set(CLAUDE_CODE_HOOK_TYPES):
        missing = sorted(set(CLAUDE_CODE_HOOK_TYPES) - claude_events)
        extra = sorted(claude_events - set(CLAUDE_CODE_HOOK_TYPES))
        raise RuntimeError(f"Claude relay set drift: missing={missing}, extra={extra}")
    if set(CODEX_RELAY_EVENTS) != set(CODEX_HOOK_TYPES):
        missing = sorted(set(CODEX_HOOK_TYPES) - set(CODEX_RELAY_EVENTS))
        extra = sorted(set(CODEX_RELAY_EVENTS) - set(CODEX_HOOK_TYPES))
        raise RuntimeError(f"Codex relay set drift: missing={missing}, extra={extra}")


def cli_main(argv: Iterable[str] | None = None) -> None:
    """CLI for installing paia relays into a project-local hook directory."""
    parser = argparse.ArgumentParser(description="Generate PAIA hook relays for CAVE.")
    parser.add_argument("provider", choices=("claude_code", "claude", "codex"))
    parser.add_argument("root", help="Project root where .claude/ or .codex/ should be written")
    parser.add_argument(
        "--cave-package-root",
        default=None,
        help="Path to the checkout containing the cave package, inserted into generated scripts.",
    )
    parser.add_argument(
        "--no-legacy",
        action="store_true",
        help="For Claude Code, omit legacy pre-2026 relay aliases such as SubagentSpawn.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    _validate_event_sets()
    result = install_provider_relays(
        args.provider,
        args.root,
        cave_package_root=args.cave_package_root,
        include_legacy=not args.no_legacy,
    )
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    cli_main()
