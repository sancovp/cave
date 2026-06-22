"""Tests for CAVE's read-only SILAS AIOS bridge."""

from __future__ import annotations

from types import SimpleNamespace

from cave.core.aios import AIOSBridge, discover_aios_root
from cave.core.mixins.aios import AIOSMixin
from cave.server import http_server


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_aios_root(tmp_path):
    root = tmp_path / "project"
    required = [
        "silas_aios/AGENTS.md",
        "silas_aios/kernel/boot_protocol.md",
        "silas_aios/registries/term_nucleus.md",
        "silas_aios/registries/surface_registry.md",
        "silas_aios/search/skilltree.md",
        "silas_aios/skilltree/project_skilltree.md",
        "silas_aios/skilltree/test_lab.md",
        "silas_aios/adapters/codex_skilltree_adapter.md",
        "silas_aios/selector/policy.md",
        "silas_aios/selector/boundary_gate.md",
        "silas_aios/ledgers/context_ledger.md",
        "silas_aios/ledgers/budget_ledger.md",
        "silas_aios/maps/architecture_map.md",
        "silas_aios/maps/workflow_genome_map.md",
        "silas_aios/maps/evidence_map.md",
        "silas_aios/maps/drift_map.md",
        "silas_aios/queues/mutation_queue.md",
        "silas_aios/queues/promotion_queue.md",
        "silas_aios/runtime/current_mode.md",
        "silas_aios/runtime/next_action.md",
        "silas_aios/runtime/selector_decision.json",
        "silas_aios/runtime/skilltree_project_map.md",
        "silas_aios/runtime/skilltree_lab/report.md",
        "silas_aios/runtime/skilltree_coherence_report.md",
        ".codex/skills/sic-silas-aios/SKILL.md",
        ".codex/skills/sic-skilltree-coherence/SKILL.md",
        ".codex/skills/sic-silas-aios/references/boot-protocol.md",
        ".codex/skills/sic-silas-aios/scripts/aios_status.py",
        ".codex/skills/sic-silas-aios/scripts/aios_search.py",
        ".codex/skills/sic-silas-aios/scripts/aios_skilltree_project.py",
        ".codex/skills/sic-silas-aios/scripts/aios_skilltree_lab.py",
        ".codex/skills/sic-silas-aios/scripts/aios_skilltree_coherence.py",
        ".codex/skills/sic-silas-aios/scripts/aios_select.py",
        ".codex/skills/sic-silas-aios/scripts/aios_skilltree_adapter.py",
        ".codex/skills/sic-silas-aios/scripts/aios_gate.py",
    ]
    for rel in required:
        _write(root / rel, f"# {rel}\nAIOS searchable content\n")
    _write(root / "silas_aios/runtime/next_action.md", "# Next Action\nRun AIOS bridge assay\n")
    _write(root / "silas_aios/runtime/selector_decision.json", "{}\n")
    _write(
        root / "silas_aios/queues/mutation_queue.md",
        "Candidate future mutations:\n- Build a Codex adapter for skilltree.\n",
    )
    _write(
        root / ".codex/skills/sic-silas-aios/SKILL.md",
        "---\nname: sic-silas-aios\ndescription: AIOS boot bridge\n---\n\nSearch AIOS status.\n",
    )
    _write(
        root / "self_improving_coding_prompts/assessment/system_integration/aios_prompt.md",
        "PromptType: WorkPrompt\nConcreteContext: gene ontology AIOS search\n",
    )
    return root


def link_all_project_skills(root):
    view = root / "silas_aios" / "runtime" / "skilltree_codex_view" / ".claude" / "skills"
    view.mkdir(parents=True)
    skills_root = root / ".codex" / "skills"
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        if (skill_dir / "SKILL.md").is_file():
            (view / skill_dir.name).symlink_to(skill_dir, target_is_directory=True)


def test_discover_aios_root_walks_up_from_child(tmp_path):
    root = make_aios_root(tmp_path)
    child = root / "silas_aios" / "runtime"

    assert discover_aios_root(child) == root


def test_aios_bridge_status_next_action_and_fallback_search(tmp_path):
    root = make_aios_root(tmp_path)
    bridge = AIOSBridge(root=root, use_installed_skilltree=False)

    status = bridge.status()
    assert status["status"] == "ok"
    assert status["missing_count"] == 0
    assert status["files"][0]["sha256"]

    next_action = bridge.next_action()
    assert next_action["status"] == "ok"
    assert "Run AIOS bridge assay" in next_action["next_action"]

    aios_hits = bridge.search("bridge assay", domain="aios")
    assert aios_hits["engine"] == "fallback_lexical"
    assert aios_hits["results"][0]["path"] == "silas_aios/runtime/next_action.md"

    skill_hits = bridge.search("boot bridge", domain="skills")
    assert skill_hits["results"][0]["path"] == ".codex/skills/sic-silas-aios/SKILL.md"

    prompt_hits = bridge.search("gene ontology", domain="prompts")
    assert prompt_hits["results"][0]["path"].endswith("aios_prompt.md")


def test_aios_bridge_selects_advisory_dna_sequence(tmp_path):
    root = make_aios_root(tmp_path)
    bridge = AIOSBridge(root=root, use_installed_skilltree=False)

    selection = bridge.select_next()

    assert selection["status"] == "ok"
    assert selection["selected"]["id"] == "codex_skilltree_adapter"
    assert selection["selected"]["requires_approval"] is False
    assert selection["dna_sequence"]["mode"] == "advisory"
    assert selection["dna_sequence"]["metadata"]["selected_candidate"] == "codex_skilltree_adapter"
    assert [step["id"] for step in selection["dna_sequence"]["steps"]] == [
        "observe",
        "act",
        "assay",
        "checkpoint",
    ]


def test_aios_gate_allows_only_selected_non_approval_candidate(tmp_path):
    root = make_aios_root(tmp_path)
    bridge = AIOSBridge(root=root, use_installed_skilltree=False)

    selected_gate = bridge.gate()
    approval_gate = bridge.gate("live_cave_mcp_wiring")
    unknown_gate = bridge.gate("not_a_candidate")

    assert selected_gate["candidate_id"] == "codex_skilltree_adapter"
    assert selected_gate["decision"] == "allowed"
    assert selected_gate["allowed"] is True
    assert approval_gate["decision"] == "requires_approval"
    assert approval_gate["allowed"] is False
    assert unknown_gate["decision"] == "unknown"
    assert unknown_gate["allowed"] is False


def test_aios_bridge_checkpoints_after_adapter_view_is_current(tmp_path):
    root = make_aios_root(tmp_path)
    link_all_project_skills(root)
    bridge = AIOSBridge(root=root, use_installed_skilltree=False)

    selection = bridge.select_next()

    adapter = next(candidate for candidate in selection["candidates"] if candidate["id"] == "codex_skilltree_adapter")
    assert adapter["status"] == "completed"
    assert selection["selected"]["id"] == "human_checkpoint"
    assert selection["dna_sequence"]["metadata"]["selected_candidate"] == "human_checkpoint"


def test_aios_gate_blocks_checkpoint_and_completed_adapter(tmp_path):
    root = make_aios_root(tmp_path)
    link_all_project_skills(root)
    bridge = AIOSBridge(root=root, use_installed_skilltree=False)

    checkpoint_gate = bridge.gate()
    completed_gate = bridge.gate("codex_skilltree_adapter")

    assert checkpoint_gate["candidate_id"] == "human_checkpoint"
    assert checkpoint_gate["decision"] == "checkpoint"
    assert checkpoint_gate["allowed"] is False
    assert completed_gate["decision"] == "completed"
    assert completed_gate["allowed"] is False


def test_aios_bridge_reports_missing_root(tmp_path):
    bridge = AIOSBridge(root=tmp_path / "absent", use_installed_skilltree=False)

    assert bridge.status()["status"] == "drift"
    assert bridge.next_action()["status"] == "missing"


class FakeCave(AIOSMixin):
    def __init__(self, root):
        self.config = SimpleNamespace(aios_root=root, aios_skilltree_src=None)
        self._init_aios_bridge()


def test_aios_mixin_delegates_to_bridge(tmp_path):
    root = make_aios_root(tmp_path)
    cave = FakeCave(root)
    cave.aios_bridge.use_installed_skilltree = False

    assert cave.aios_status()["status"] == "ok"
    assert "Run AIOS bridge assay" in cave.aios_next_action()["next_action"]
    assert cave.aios_search("AIOS", domain="skills")["results"]
    assert cave.aios_select_next()["selected"]["id"] == "codex_skilltree_adapter"
    assert cave.aios_gate()["decision"] == "allowed"


def test_http_aios_routes_delegate_to_cave(monkeypatch):
    calls = []

    class HttpFakeCave:
        def aios_status(self):
            calls.append(("status", None))
            return {"status": "ok"}

        def aios_next_action(self):
            calls.append(("next", None))
            return {"next_action": "act"}

        def aios_search(self, **data):
            calls.append(("search", data))
            return {"results": []}

        def aios_select_next(self, **data):
            calls.append(("select", data))
            return {"selected": {"id": "candidate"}}

        def aios_gate(self, **data):
            calls.append(("gate", data))
            return {"decision": "checkpoint"}

        def aios_skilltree_project(self, **data):
            calls.append(("skilltree_project", data))
            return {"status": "ok", "command": data.get("command")}

        def aios_skilltree_lab(self, **data):
            calls.append(("skilltree_lab", data))
            return {"status": "ok", "command": data.get("command")}

        def aios_skilltree_coherence(self, **data):
            calls.append(("skilltree_coherence", data))
            return {"status": "ok", "command": data.get("command"), "gate_decision": "ok"}

    monkeypatch.setattr(http_server, "cave", HttpFakeCave())

    assert http_server.get_aios_status() == {"status": "ok"}
    assert http_server.get_aios_next_action() == {"next_action": "act"}
    assert http_server.search_aios({"query": "AIOS", "domain": "skills", "limit": 3}) == {"results": []}
    assert http_server.select_aios_next({"limit": 2}) == {"selected": {"id": "candidate"}}
    assert http_server.gate_aios_candidate({"candidate_id": "live_cave_mcp_wiring", "limit": 4}) == {"decision": "checkpoint"}
    assert http_server.run_aios_skilltree_project({"command": "doctor"}) == {"status": "ok", "command": "doctor"}
    assert http_server.run_aios_skilltree_lab({"command": "run"}) == {"status": "ok", "command": "run"}
    assert http_server.run_aios_skilltree_coherence({"command": "run"}) == {
        "status": "ok",
        "command": "run",
        "gate_decision": "ok",
    }
    assert calls == [
        ("status", None),
        ("next", None),
        ("search", {"query": "AIOS", "domain": "skills", "limit": 3}),
        ("select", {"limit": 2}),
        ("gate", {"candidate_id": "live_cave_mcp_wiring", "limit": 4}),
        ("skilltree_project", {"command": "doctor", "write_map": False}),
        ("skilltree_lab", {"command": "run"}),
        ("skilltree_coherence", {"command": "run"}),
    ]
