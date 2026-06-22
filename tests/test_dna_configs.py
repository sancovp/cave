"""Tests for selectable AutoModeDNA configs."""

from types import SimpleNamespace

import pytest

from cave.core.cave_agent import CAVEAgent
from cave.core.dna import DNAConfigStore
from cave.core.loops import AVAILABLE_LOOPS
from cave.server import http_server


def test_dna_config_store_persists_selects_and_builds_dna(tmp_path):
    store = DNAConfigStore(tmp_path)

    config = store.create_config(
        name="silas_default",
        description="SILAS default selectable behavior chain",
        loop_names=["autopoiesis", "guru"],
        exit_behavior="cycle",
        set_current=True,
    )

    listing = store.list_configs()
    current = store.get_current_config()
    dna = store.build_dna()

    assert config["path"].endswith("silas_default.json")
    assert listing["current"]["name"] == "silas_default"
    assert listing["count"] == 1
    assert current["loop_names"] == ["autopoiesis", "guru"]
    assert dna.name == "silas_default"
    assert dna.exit_behavior.value == "cycle"
    assert [loop.name for loop in dna.loops] == ["autopoiesis", "guru"]


def test_dna_config_store_flattens_nested_dna_refs(tmp_path):
    store = DNAConfigStore(tmp_path)

    store.create_config(
        name="base",
        loop_names=["autopoiesis", "guru"],
    )
    store.create_config(
        name="nested",
        loop_names=["dna:base", "autopoiesis"],
        set_current=True,
    )

    current = store.get_current_config()
    dna = store.build_dna()

    assert current["loop_names"] == ["dna:base", "autopoiesis"]
    assert store.resolve_loop_names(current["loop_names"], seen=["nested"]) == [
        "autopoiesis",
        "guru",
        "autopoiesis",
    ]
    assert [loop.name for loop in dna.loops] == ["autopoiesis", "guru", "autopoiesis"]


def test_silas_coreflow_loops_are_loadable_and_recursively_composable(tmp_path):
    expected = [
        "silas_observe",
        "silas_select",
        "silas_execute",
        "silas_assay",
        "silas_persist",
        "silas_publish_preview",
    ]
    assert all(name in AVAILABLE_LOOPS for name in expected)

    store = DNAConfigStore(tmp_path)
    store.create_config(
        name="silas_core_tick",
        description="One bounded SILAS run-once-and-learn cycle",
        loop_names=[
            "silas_observe",
            "silas_select",
            "silas_execute",
            "silas_assay",
            "silas_persist",
        ],
    )
    store.create_config(
        name="silas_attention_tick",
        description="Core tick plus proof-gated preview publishing",
        loop_names=["dna:silas_core_tick", "silas_publish_preview"],
    )
    store.create_config(
        name="silas_launch_cycle",
        description="Larger launch loop assembled from repeated attention ticks",
        loop_names=["dna:silas_attention_tick", "dna:silas_core_tick"],
        exit_behavior="cycle",
        set_current=True,
    )

    dna = store.build_dna("silas_launch_cycle")

    assert [loop.name for loop in dna.loops] == [
        "silas_observe",
        "silas_select",
        "silas_execute",
        "silas_assay",
        "silas_persist",
        "silas_publish_preview",
        "silas_observe",
        "silas_select",
        "silas_execute",
        "silas_assay",
        "silas_persist",
    ]
    assert dna.exit_behavior.value == "cycle"


def test_dna_config_store_rejects_unknown_loop_names(tmp_path):
    store = DNAConfigStore(tmp_path)

    with pytest.raises(ValueError, match="Unknown AgentInferenceLoop names"):
        store.create_config(
            name="bad_dna",
            loop_names=["autopoiesis", "missing_loop"],
        )


def test_dna_config_store_rejects_missing_nested_dna_refs(tmp_path):
    store = DNAConfigStore(tmp_path)

    with pytest.raises(ValueError, match="Unknown AutoModeDNA config references"):
        store.create_config(
            name="bad_dna",
            loop_names=["dna:missing"],
        )


def test_dna_config_store_rejects_recursive_dna_refs(tmp_path):
    store = DNAConfigStore(tmp_path)

    store.create_config(name="a", loop_names=["autopoiesis"])
    store.create_config(name="b", loop_names=["dna:a"])

    with pytest.raises(ValueError, match="Recursive AutoModeDNA config reference detected: a -> b -> a"):
        store.create_config(name="a", loop_names=["dna:b"])


class FakeDnaCave:
    start_auto_mode = CAVEAgent.start_auto_mode
    create_dna_config = CAVEAgent.create_dna_config
    select_dna_config = CAVEAgent.select_dna_config
    start_dna_config = CAVEAgent.start_dna_config
    get_selected_dna_config = CAVEAgent.get_selected_dna_config
    set_dna_sequence = CAVEAgent.set_dna_sequence
    get_dna_sequence = CAVEAgent.get_dna_sequence
    clear_dna_sequence = CAVEAgent.clear_dna_sequence
    get_next_dna_step = CAVEAgent.get_next_dna_step
    complete_dna_step = CAVEAgent.complete_dna_step
    get_dna_sequence_stop_check = CAVEAgent.get_dna_sequence_stop_check

    def __init__(self, tmp_path):
        self.config = SimpleNamespace(
            main_agent_config=SimpleNamespace(active_hooks={}),
        )
        self.main_agent = None
        self._hook_state = {}
        self.dna = None
        self.dna_config_store = DNAConfigStore(tmp_path)


def test_cave_methods_start_selected_dna_config(tmp_path):
    cave = FakeDnaCave(tmp_path)
    cave.create_dna_config(
        name="silas_cycle",
        loop_names=["autopoiesis", "guru"],
        exit_behavior="cycle",
        set_current=True,
    )

    result = cave.start_dna_config()

    assert result["status"] == "started"
    assert result["dna"] == "silas_cycle"
    assert result["current_loop"] == "autopoiesis"
    assert cave.dna.active is True
    assert cave.config.main_agent_config.active_hooks == {"stop": ["autopoiesis_stop"]}
    assert cave.get_selected_dna_config()["current"]["name"] == "silas_cycle"


def test_dna_sequence_set_next_complete_and_clear(tmp_path):
    store = DNAConfigStore(tmp_path)
    sequence = store.set_sequence(
        name="sprint",
        mode="blocking",
        steps=[
            {"id": "inspect", "title": "Inspect current hooks", "prompt": "Read hook code"},
            {"id": "verify", "title": "Verify tests", "prompt": "Run focused tests"},
        ],
    )

    next_step = store.get_next_step()
    stop_check = store.sequence_stop_check()

    assert sequence["path"].endswith("sequence.json")
    assert next_step["next_step"]["id"] == "inspect"
    assert stop_check["blocked"] is True
    assert [step["id"] for step in stop_check["missing_steps"]] == ["inspect", "verify"]

    updated = store.complete_step(step_id="inspect", summary="hooks inspected")
    assert updated["steps"][0]["status"] == "completed"
    assert updated["steps"][0]["summary"] == "hooks inspected"
    assert store.get_next_step()["next_step"]["id"] == "verify"

    store.complete_step(step_id="verify")
    assert store.sequence_stop_check()["ok"] is True
    assert store.sequence_stop_check()["blocked"] is False
    assert store.clear_sequence()["cleared"] is True
    assert store.get_next_step()["active"] is False


def test_cave_methods_control_dna_sequence(tmp_path):
    cave = FakeDnaCave(tmp_path)

    sequence = cave.set_dna_sequence(
        name="codex_followthrough",
        steps=["Persist prompt", {"id": "test", "title": "Run tests"}],
    )

    assert cave.get_dna_sequence()["path"] == sequence["path"]
    assert cave.get_next_dna_step()["next_step"]["title"] == "Persist prompt"
    assert cave.get_dna_sequence_stop_check()["blocked"] is False
    cave.complete_dna_step(status="completed")
    assert cave.get_next_dna_step()["next_step"]["id"] == "test"
    assert cave.clear_dna_sequence()["cleared"] is True


def test_http_dna_config_routes_delegate_to_cave(monkeypatch):
    calls = []

    class HttpFakeCave:
        def list_dna_configs(self):
            calls.append(("list", None))
            return {"configs": []}

        def create_dna_config(self, **data):
            calls.append(("create", data))
            return {"name": data["name"]}

        def get_selected_dna_config(self):
            calls.append(("current", None))
            return {"current": {"name": "selected"}}

        def start_dna_config(self, name=None):
            calls.append(("start", name))
            return {"started": name or "current"}

        def get_dna_config(self, name):
            calls.append(("get", name))
            return {"name": name}

        def select_dna_config(self, name):
            calls.append(("select", name))
            return {"name": name}

        def get_dna_sequence(self):
            calls.append(("sequence", None))
            return {"sequence": {}}

        def set_dna_sequence(self, **data):
            calls.append(("set_sequence", data))
            return {"sequence": data}

        def clear_dna_sequence(self):
            calls.append(("clear_sequence", None))
            return {"cleared": True}

        def get_next_dna_step(self):
            calls.append(("next_step", None))
            return {"next_step": {"id": "a"}}

        def complete_dna_step(self, **data):
            calls.append(("complete_step", data))
            return {"completed": data}

        def get_dna_sequence_stop_check(self):
            calls.append(("sequence_stop_check", None))
            return {"ok": True}

    monkeypatch.setattr(http_server, "cave", HttpFakeCave())

    assert http_server.list_dna_configs() == {"configs": []}
    assert http_server.create_dna_config({"name": "shape", "loop_names": ["autopoiesis"]}) == {"name": "shape"}
    assert http_server.get_selected_dna_config() == {"current": {"name": "selected"}}
    assert http_server.start_selected_dna_config() == {"started": "current"}
    assert http_server.get_dna_config("shape") == {"name": "shape"}
    assert http_server.select_dna_config("shape") == {"name": "shape"}
    assert http_server.start_named_dna_config("shape") == {"started": "shape"}
    assert http_server.get_dna_sequence() == {"sequence": {}}
    assert http_server.set_dna_sequence({"steps": ["a"]}) == {"sequence": {"steps": ["a"]}}
    assert http_server.get_next_dna_step() == {"next_step": {"id": "a"}}
    assert http_server.complete_dna_step({"step_id": "a"}) == {"completed": {"step_id": "a"}}
    assert http_server.get_dna_sequence_stop_check() == {"ok": True}
    assert http_server.clear_dna_sequence() == {"cleared": True}
    assert calls == [
        ("list", None),
        ("create", {"name": "shape", "loop_names": ["autopoiesis"]}),
        ("current", None),
        ("start", None),
        ("get", "shape"),
        ("select", "shape"),
        ("start", "shape"),
        ("sequence", None),
        ("set_sequence", {"steps": ["a"]}),
        ("next_step", None),
        ("complete_step", {"step_id": "a"}),
        ("sequence_stop_check", None),
        ("clear_sequence", None),
    ]
