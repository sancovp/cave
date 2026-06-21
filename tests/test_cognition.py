"""Tests for CAVE cognitive spaces and reified loop shapes."""

from pathlib import Path
from types import SimpleNamespace

from cave.core.cognition import (
    CognitiveSpaceStopHook,
    CognitionStore,
    write_cognitive_stop_hook,
)
from cave.core.config import CAVEConfig
from cave.core.dna import DNAConfigStore
from cave.core.mixins.cognition import CognitionMixin
from cave.server import http_server


def test_store_creates_loop_space_current_pointer_and_persistent_kv(tmp_path):
    store = CognitionStore(tmp_path)

    loop = store.create_loop_shape(
        name="silas_agent_inference_loop",
        prompt="observe -> atomize -> synthesize -> verify",
        output_override={"type": "agent_inbox", "to_agent": "codex"},
        kv_defaults={"phase_seen": "observe"},
        verification_gates=["verified"],
    )
    space = store.create_space(
        name="codex_turn",
        loop_id=loop["id"],
        kv={"verified": False},
    )

    assert Path(loop["path"]).exists()
    assert Path(space["path"]).exists()
    assert store.get_current_space()["id"] == space["id"]
    assert store.get_current_space()["kv"] == {
        "phase_seen": "observe",
        "verified": False,
    }

    updated = store.put_kv(space_id=space["id"], key="verified", value=True)

    assert updated["kv"]["verified"] is True
    assert store.load_space(space["id"])["kv"]["verified"] is True
    assert store.stop_check(space_id=space["id"])["ok"] is True


def test_stop_check_reports_current_space_path_and_missing_file_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = CognitionStore(tmp_path / "runtime")
    proof_path = tmp_path / "proof.json"
    space = store.create_space(
        name="needs_file",
        verification_gates=[{
            "name": "proof_file",
            "type": "file_exists",
            "path": "proof.json",
        }],
    )

    check = store.stop_check()

    assert check["current_space"] == space["id"]
    assert check["current_space_path"] == space["path"]
    assert check["ok"] is False
    assert check["result"] == "continue"
    assert check["missing_gates"][0]["name"] == "proof_file"
    assert space["path"] in check["additionalContext"]

    proof_path.write_text("{}")
    assert store.stop_check()["ok"] is True


def test_stop_hook_blocks_only_when_space_is_strict(tmp_path):
    store = CognitionStore(tmp_path)
    space = store.create_space(
        name="strict_space",
        verification_gates=["done"],
        stop_conditions={"mode": "blocking", "strict": True},
    )
    hook = CognitiveSpaceStopHook(data_dir=tmp_path)

    result = hook.handle({"hook_event_name": "Stop"}, {})
    payload = result.to_dict()

    assert payload["decision"] == "block"
    assert payload["stopReason"] == "CAVE stop-check has unmet DNA sequence or cognitive-space gates"
    assert space["path"] in payload["additionalContext"]

    store.put_kv(space_id=space["id"], key="done", value=True)
    payload = hook.handle({"hook_event_name": "Stop"}, {}).to_dict()

    assert payload["decision"] == "continue"
    assert "Passed gates: done" in payload["additionalContext"]


def test_stop_hook_reports_and_blocks_strict_dna_sequence_without_cognitive_space(tmp_path):
    DNAConfigStore(tmp_path).set_sequence(
        name="strict_followthrough",
        mode="blocking",
        steps=[{
            "id": "patch",
            "title": "Patch the DNA sequence API",
            "prompt": "Implement set/get/clear/next DNA sequence calls.",
        }],
    )
    hook = CognitiveSpaceStopHook(data_dir=tmp_path)

    payload = hook.handle({"hook_event_name": "Stop"}, {}).to_dict()

    assert payload["decision"] == "block"
    assert "CAVE DNA follow-through: incomplete" in payload["additionalContext"]
    assert "Next DNA step [patch]" in payload["additionalContext"]
    assert "Next prompt: Implement set/get/clear/next DNA sequence calls." in payload["additionalContext"]

    DNAConfigStore(tmp_path).complete_step(step_id="patch")
    payload = hook.handle({"hook_event_name": "Stop"}, {}).to_dict()

    assert payload["decision"] == "continue"
    assert "CAVE DNA follow-through: green" in payload["additionalContext"]


class FakeConfig:
    def __init__(self, data_dir, hook_dir):
        self.data_dir = data_dir
        self.hook_dir = hook_dir
        self.main_agent_config = SimpleNamespace(active_hooks={})
        self.saved = False

    def save(self):
        self.saved = True


class FakeCave(CognitionMixin):
    def __init__(self, tmp_path):
        self.config = FakeConfig(tmp_path / "data", tmp_path / "hooks")
        self._hook_state = {}
        self.scans = 0
        self._init_cognition()

    def scan_hooks(self):
        self.scans += 1
        return {"found": self.scans}


def test_cognition_mixin_installs_stop_hook_and_marks_hook_state(tmp_path):
    cave = FakeCave(tmp_path)
    loop = cave.create_reified_loop(
        name="shape",
        verification_gates=[{"type": "kv_truthy", "key": "green"}],
    )
    space = cave.create_cognitive_space(name="space", loop_id=loop["id"])

    install = cave.install_cognition_stop_hook(activate=True)

    assert cave._hook_state["cognition_data_dir"] == str(cave.config.data_dir)
    assert install["activated"] is True
    assert "cognitive_space_stop_check" in cave.config.main_agent_config.active_hooks["stop"]
    assert Path(install["path"]).exists()
    assert cave.config.saved is True
    assert cave.cognition_stop_check()["current_space_path"] == space["path"]


def test_source_controlled_stop_hook_template_is_registry_loadable(tmp_path):
    path = write_cognitive_stop_hook(tmp_path)
    content = path.read_text()

    assert "CognitiveSpaceStopHook" in content
    assert "CaveCognitiveSpaceStopHook" in content


def test_http_cognition_routes_delegate_to_cave(monkeypatch):
    calls = []

    class HttpFakeCave:
        def create_reified_loop(self, **data):
            calls.append(("create_loop", data))
            return {"id": "loop"}

        def get_reified_loop(self, loop_id):
            calls.append(("get_loop", loop_id))
            return {"id": loop_id}

        def create_cognitive_space(self, **data):
            calls.append(("create_space", data))
            return {"id": "space"}

        def get_current_cognitive_space(self):
            calls.append(("current", None))
            return {"path": "/tmp/current.json"}

        def put_cognitive_kv(self, **data):
            calls.append(("kv", data))
            return {"kv": True}

        def cognition_stop_check(self, **data):
            calls.append(("stop_check", data))
            return {"ok": True}

    monkeypatch.setattr(http_server, "cave", HttpFakeCave())

    assert http_server.create_reified_loop({"name": "shape"}) == {"id": "loop"}
    assert http_server.get_reified_loop("loop") == {"id": "loop"}
    assert http_server.create_cognitive_space({"name": "space"}) == {"id": "space"}
    assert http_server.get_current_cognitive_space() == {"path": "/tmp/current.json"}
    assert http_server.put_current_cognitive_space_kv({"key": "done", "value": True}) == {"kv": True}
    assert http_server.cognition_stop_check({"space_id": "space"}) == {"ok": True}
    assert calls == [
        ("create_loop", {"name": "shape"}),
        ("get_loop", "loop"),
        ("create_space", {"name": "space"}),
        ("current", None),
        ("kv", {"key": "done", "value": True, "updates": None}),
        ("stop_check", {"space_id": "space", "hook_payload": None}),
    ]


def test_config_migrates_only_legacy_default_data_dir(tmp_path, monkeypatch):
    env_dir = tmp_path / "env_heaven"
    monkeypatch.setenv("HEAVEN_DATA_DIR", str(env_dir))

    legacy = CAVEConfig(data_dir=Path("/tmp/heaven_data"))
    legacy._migrate_legacy_data_dir()

    custom_dir = tmp_path / "custom"
    custom = CAVEConfig(data_dir=custom_dir)
    custom._migrate_legacy_data_dir()

    assert legacy.data_dir == env_dir
    assert custom.data_dir == custom_dir
