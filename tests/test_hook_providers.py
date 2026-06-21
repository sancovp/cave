"""Tests for provider-neutral hook routing."""
from types import SimpleNamespace

from cave.core.hooks import (
    CODEX_HOOK_TYPES,
    CLAUDE_CODE_HOOK_TYPES,
    CodeAgentHook,
    CodexHook,
    HookDecision,
    HookProvider,
    HookRegistry,
    HookResult,
    HookType,
    canonical_hook_type,
    format_hook_response,
    get_hook_types_for_provider,
    hook_type_key,
    normalize_provider,
)
from cave.core.mixins.hook_router import HookRouterMixin
from cave.server import http_server


CLAUDE_CODE_DOC_EVENTS = {
    "SessionStart",
    "Setup",
    "InstructionsLoaded",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "MessageDisplay",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "PermissionDenied",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "TaskCreated",
    "TaskCompleted",
    "Stop",
    "StopFailure",
    "TeammateIdle",
    "ConfigChange",
    "CwdChanged",
    "FileChanged",
    "WorktreeCreate",
    "WorktreeRemove",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
    "Elicitation",
    "ElicitationResult",
}


CODEX_DOC_EVENTS = {
    "SessionStart",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "Stop",
}


def test_claude_code_event_set_matches_current_docs():
    assert CLAUDE_CODE_DOC_EVENTS.issubset(CLAUDE_CODE_HOOK_TYPES)
    assert get_hook_types_for_provider("claude") == CLAUDE_CODE_HOOK_TYPES


def test_codex_event_set_matches_current_docs_subset():
    assert CODEX_HOOK_TYPES == CODEX_DOC_EVENTS
    assert get_hook_types_for_provider(HookProvider.CODEX) == CODEX_DOC_EVENTS


def test_hook_type_and_provider_normalization():
    assert canonical_hook_type("pretooluse") == "PreToolUse"
    assert hook_type_key(HookType.USER_PROMPT_SUBMIT) == "userpromptsubmit"
    assert normalize_provider("claude-code") == "claude_code"
    assert normalize_provider("openai-codex") == "codex"


def test_codex_pretooluse_block_formats_permission_deny():
    response = format_hook_response(
        {"result": "block", "reason": "No destructive commands"},
        "codex",
        HookType.PRE_TOOL_USE,
    )

    assert response == {
        "decision": "block",
        "reason": "No destructive commands",
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "No destructive commands",
        },
    }


def test_codex_permission_request_block_uses_decision_shape():
    response = format_hook_response(
        {"result": "block", "reason": "Escalation denied"},
        "codex",
        HookType.PERMISSION_REQUEST,
    )

    assert response["hookSpecificOutput"] == {
        "hookEventName": "PermissionRequest",
        "decision": {
            "behavior": "deny",
            "message": "Escalation denied",
        },
    }


def test_codex_pretooluse_updated_input_formats_allow():
    response = format_hook_response(
        {
            "result": "continue",
            "decision": "approve",
            "updatedInput": {"command": "echo rewritten"},
        },
        "codex",
        "PreToolUse",
    )

    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": "echo rewritten"},
        },
    }


def test_registry_loads_provider_neutral_and_codex_hooks(tmp_path):
    neutral_file = tmp_path / "neutral_hook.py"
    neutral_file.write_text(
        """
from cave.core.hooks import CodeAgentHook, HookDecision, HookResult, HookType

class NeutralHook(CodeAgentHook):
    hook_type = HookType.POST_COMPACT

    def handle(self, payload, state):
        return HookResult(HookDecision.CONTINUE)
"""
    )
    codex_file = tmp_path / "codex_hook.py"
    codex_file.write_text(
        """
from cave.core.hooks import CodexHook, HookDecision, HookResult, HookType

class ProviderHook(CodexHook):
    hook_type = HookType.STOP

    def handle(self, payload, state):
        return HookResult(HookDecision.BLOCK, reason="continue")
"""
    )

    registry = HookRegistry(tmp_path)
    result = registry.scan()

    assert result["found"] == 2
    neutral_hooks = registry.get_hooks_for_type("PostCompact")
    codex_hooks = registry.get_hooks_for_type("Stop")
    assert isinstance(neutral_hooks[0], CodeAgentHook)
    assert isinstance(codex_hooks[0], CodexHook)


class FakeRouter(HookRouterMixin):
    def __init__(self, hooks_dir, active_hooks):
        self.config = SimpleNamespace(
            hook_dir=hooks_dir,
            main_agent_config=SimpleNamespace(active_hooks=active_hooks),
        )
        self._init_hook_router()

    def check_dna_transition(self):
        return {"status": "inactive"}


def test_router_normalizes_codex_prompt_and_formats_context(tmp_path):
    hook_file = tmp_path / "prompt_context.py"
    hook_file.write_text(
        """
from cave.core.hooks import CodeAgentHook, HookDecision, HookResult, HookType

class PromptContextHook(CodeAgentHook):
    hook_type = HookType.USER_PROMPT_SUBMIT

    def __init__(self):
        super().__init__(name="prompt_context")

    def handle(self, payload, state):
        state["last_prompt"] = payload["user_input"]
        return HookResult(
            HookDecision.CONTINUE,
            additional_context=f"Observed: {payload['user_input']}",
        )
"""
    )
    router = FakeRouter(tmp_path, {"userpromptsubmit": ["prompt_context"]})

    response = router.handle_hook(
        "UserPromptSubmit",
        {"source": "codex", "prompt": "wire CAVE"},
    )

    assert router.get_hook_state()["last_prompt"] == "wire CAVE"
    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Observed: wire CAVE",
        }
    }


def test_router_records_codex_signals_even_without_active_hooks(tmp_path):
    router = FakeRouter(tmp_path, {})

    response = router.handle_hook(
        "UserPromptSubmit",
        {"source": "codex", "prompt": "observe me"},
    )

    history = router.get_hook_history()
    assert len(history) == 1
    assert history[0]["source"] == "codex"
    assert history[0]["payload"]["user_input"] == "observe me"
    assert response == {}


def test_http_hook_endpoint_skips_omnisanc_for_codex(monkeypatch):
    calls = []

    class FakeCave:
        def run_omnisanc(self):
            calls.append("omnisanc")

        def handle_hook(self, hook_type, data):
            calls.append(("handle", hook_type, data["source"]))
            return {"ok": True}

    monkeypatch.setattr(http_server, "cave", FakeCave())

    response = http_server.handle_hook_signal(
        "userpromptsubmit",
        {"source": "codex"},
    )

    assert response == {"ok": True}
    assert calls == [("handle", "userpromptsubmit", "codex")]


def test_http_hook_endpoint_keeps_omnisanc_for_non_codex(monkeypatch):
    calls = []

    class FakeCave:
        def run_omnisanc(self):
            calls.append("omnisanc")

        def handle_hook(self, hook_type, data):
            calls.append(("handle", hook_type, data.get("source", "default")))
            return {"ok": True}

    monkeypatch.setattr(http_server, "cave", FakeCave())

    response = http_server.handle_hook_signal(
        "stop",
        {"source": "claude_code"},
    )

    assert response == {"ok": True}
    assert calls == ["omnisanc", ("handle", "stop", "claude_code")]
