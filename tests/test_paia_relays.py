"""Tests for generated PAIA hook relays."""
import contextlib
import io
import json

import pytest

from cave.core.hooks import CODEX_HOOK_TYPES, CLAUDE_CODE_HOOK_TYPES, HookType
from cave.relays.paia import (
    CLAUDE_CODE_RELAY_EVENTS,
    CODEX_RELAY_EVENTS,
    DEFAULT_CAVE_URL,
    LEGACY_CLAUDE_CODE_RELAY_EVENTS,
    _emit_claude_code_result,
    _emit_codex_result,
    build_hooks_config,
    paia_script_name,
    render_paia_script,
    write_hooks_config,
    write_relay_set,
)
from cave.relays.loop_probe import run_probe_loop


def test_claude_relay_events_cover_current_docs_plus_legacy_aliases():
    assert set(CLAUDE_CODE_RELAY_EVENTS) == set(CLAUDE_CODE_HOOK_TYPES)
    assert LEGACY_CLAUDE_CODE_RELAY_EVENTS == ("SubagentSpawn",)


def test_codex_relay_events_cover_current_docs_subset():
    assert set(CODEX_RELAY_EVENTS) == set(CODEX_HOOK_TYPES)


def test_default_cave_url_uses_non_common_project_port():
    assert DEFAULT_CAVE_URL == "http://localhost:18765"
    assert not DEFAULT_CAVE_URL.endswith(":8080")


def test_paia_script_name_uses_canonical_hook_key():
    assert paia_script_name("PreToolUse") == "paia_pretooluse.py"
    assert paia_script_name(HookType.USER_PROMPT_SUBMIT) == "paia_userpromptsubmit.py"


def test_render_paia_script_is_thin_provider_forwarder():
    script = render_paia_script("codex", "PreToolUse", cave_package_root="/repo/cave")

    assert "CAVE_PACKAGE_ROOT = '/repo/cave'" in script
    assert "relay_main(provider='codex', hook_event='PreToolUse')" in script


def test_build_codex_hooks_config_points_every_event_at_script(tmp_path):
    config = build_hooks_config("codex", tmp_path)

    assert set(config["hooks"]) == set(CODEX_RELAY_EVENTS)
    for event, groups in config["hooks"].items():
        command = groups[0]["hooks"][0]["command"]
        assert f"paia_{event.lower()}.py" in command
        assert groups[0]["hooks"][0]["type"] == "command"


def test_build_claude_hooks_config_includes_file_changed_matcher(tmp_path):
    config = build_hooks_config("claude", tmp_path)

    assert set(config["hooks"]) == set(CLAUDE_CODE_RELAY_EVENTS + LEGACY_CLAUDE_CODE_RELAY_EVENTS)
    assert config["hooks"]["FileChanged"][0]["matcher"]


def test_write_relay_set_and_config(tmp_path):
    hook_dir = tmp_path / "hooks"
    config_path = tmp_path / "hooks.json"

    written = write_relay_set("codex", hook_dir, cave_package_root="/repo/cave")
    write_hooks_config("codex", config_path, hook_dir)

    assert {path.name for path in written} == {paia_script_name(event) for event in CODEX_RELAY_EVENTS}
    assert all(path.stat().st_mode & 0o111 for path in written)
    config = json.loads(config_path.read_text())
    assert set(config["hooks"]) == set(CODEX_RELAY_EVENTS)


def test_write_claude_relay_set_covers_full_paia_surface(tmp_path):
    written = write_relay_set("claude", tmp_path, cave_package_root="/repo/cave")

    expected_events = CLAUDE_CODE_RELAY_EVENTS + LEGACY_CLAUDE_CODE_RELAY_EVENTS
    assert {path.name for path in written} == {paia_script_name(event) for event in expected_events}
    assert (tmp_path / "paia_pretooluse.py").exists()
    assert (tmp_path / "paia_subagentspawn.py").exists()


def test_codex_relay_emits_json_and_exits_zero():
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        with pytest.raises(SystemExit) as exc:
            _emit_codex_result(
                "PreToolUse",
                {"result": "block", "reason": "blocked"},
            )

    assert exc.value.code == 0
    output = json.loads(stdout.getvalue())
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_claude_relay_block_uses_exit_code_two(capsys):
    with pytest.raises(SystemExit) as exc:
        _emit_claude_code_result(
            "Stop",
            {"result": "block", "reason": "keep working", "additionalContext": "context"},
        )

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "keep working" in captured.err
    assert "context" in captured.err


def test_loop_probe_is_bounded_and_records_responses(tmp_path):
    calls = []

    def fake_call(event, payload, *, cave_url):
        calls.append((event, payload, cave_url))
        return {"result": "continue", "observed": payload["loop_probe"]["iteration"]}

    output_path = tmp_path / "probe.jsonl"
    records = run_probe_loop(
        iterations=3,
        delay=0,
        output_path=output_path,
        call=fake_call,
    )

    assert len(calls) == 3
    assert [record["iteration"] for record in records] == [1, 2, 3]
    assert records[-1]["response"]["observed"] == 3
    assert len(output_path.read_text().splitlines()) == 3
