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
        ".codex/skills/sic-silas-aios/SKILL.md",
        ".codex/skills/sic-silas-aios/references/boot-protocol.md",
        ".codex/skills/sic-silas-aios/scripts/aios_status.py",
        ".codex/skills/sic-silas-aios/scripts/aios_search.py",
    ]
    for rel in required:
        _write(root / rel, f"# {rel}\nAIOS searchable content\n")
    _write(root / "silas_aios/runtime/next_action.md", "# Next Action\nRun AIOS bridge assay\n")
    _write(
        root / ".codex/skills/sic-silas-aios/SKILL.md",
        "---\nname: sic-silas-aios\ndescription: AIOS boot bridge\n---\n\nSearch AIOS status.\n",
    )
    _write(
        root / "self_improving_coding_prompts/assessment/system_integration/aios_prompt.md",
        "PromptType: WorkPrompt\nConcreteContext: gene ontology AIOS search\n",
    )
    return root


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

    monkeypatch.setattr(http_server, "cave", HttpFakeCave())

    assert http_server.get_aios_status() == {"status": "ok"}
    assert http_server.get_aios_next_action() == {"next_action": "act"}
    assert http_server.search_aios({"query": "AIOS", "domain": "skills", "limit": 3}) == {"results": []}
    assert calls == [
        ("status", None),
        ("next", None),
        ("search", {"query": "AIOS", "domain": "skills", "limit": 3}),
    ]
