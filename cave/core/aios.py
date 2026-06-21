"""Read-only bridge from CAVE into a SILAS AIOS filesystem scaffold."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_REQUIRED_PATHS = [
    "silas_aios/AGENTS.md",
    "silas_aios/kernel/boot_protocol.md",
    "silas_aios/registries/term_nucleus.md",
    "silas_aios/registries/surface_registry.md",
    "silas_aios/search/skilltree.md",
    "silas_aios/adapters/codex_skilltree_adapter.md",
    "silas_aios/selector/policy.md",
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
    ".codex/skills/sic-silas-aios/SKILL.md",
    ".codex/skills/sic-silas-aios/references/boot-protocol.md",
    ".codex/skills/sic-silas-aios/scripts/aios_status.py",
    ".codex/skills/sic-silas-aios/scripts/aios_search.py",
    ".codex/skills/sic-silas-aios/scripts/aios_select.py",
    ".codex/skills/sic-silas-aios/scripts/aios_skilltree_adapter.py",
]

DEFAULT_EXTS = (".md", ".txt", ".mdx", ".rst")


def discover_aios_root(start: str | Path | None = None) -> Optional[Path]:
    """Walk upward from start until a `silas_aios/AGENTS.md` root is found."""
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "silas_aios" / "AGENTS.md").is_file():
            return candidate
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("---"):
            return stripped.lstrip("# ").strip()[:120]
    return fallback


def _iter_text_files(root: Path, exts: Iterable[str] = DEFAULT_EXTS) -> Iterable[Path]:
    extensions = tuple(ext.lower() for ext in exts)
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            yield path


def _lexical_search(root: Path, query: str, *, limit: int, exts: Iterable[str] = DEFAULT_EXTS) -> List[Dict[str, Any]]:
    terms = [term.lower() for term in query.split() if term.strip()]
    hits: List[Dict[str, Any]] = []
    for path in _iter_text_files(root, exts):
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        score = sum(lowered.count(term) for term in terms) if terms else 0
        if score <= 0:
            continue
        hits.append({
            "name": _first_title(text, path.stem),
            "coord": "",
            "description": "",
            "path": str(path),
            "score": -float(score),
        })
    hits.sort(key=lambda item: (item["score"], item["path"]))
    return hits[:limit]


@dataclass
class AIOSBridge:
    """Read-only AIOS inspector/search adapter for CAVE.

    Markdown remains AIOS source of truth. Search results identify files to read;
    they are not evidence by themselves.
    """

    root: Optional[Path | str] = None
    skilltree_src: Optional[Path | str] = None
    use_installed_skilltree: bool = True
    required_paths: List[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED_PATHS))

    def __post_init__(self) -> None:
        if self.root is not None:
            self.root = Path(self.root).resolve()
        if self.skilltree_src is not None:
            self.skilltree_src = Path(self.skilltree_src).resolve()

    @property
    def resolved_root(self) -> Optional[Path]:
        if self.root is not None:
            return Path(self.root)
        return discover_aios_root()

    def status(self) -> Dict[str, Any]:
        root = self.resolved_root
        if root is None:
            return {
                "status": "missing",
                "root": None,
                "required_count": len(self.required_paths),
                "missing_count": len(self.required_paths),
                "missing": list(self.required_paths),
                "files": [],
            }

        files = []
        missing = []
        for rel in self.required_paths:
            path = root / rel
            exists = path.is_file()
            entry: Dict[str, Any] = {"path": rel, "exists": exists}
            if exists:
                entry["size_bytes"] = path.stat().st_size
                entry["sha256"] = _sha256(path)
            else:
                missing.append(rel)
            files.append(entry)
        return {
            "status": "ok" if not missing else "drift",
            "root": str(root),
            "required_count": len(self.required_paths),
            "missing_count": len(missing),
            "missing": missing,
            "files": files,
        }

    def next_action(self) -> Dict[str, Any]:
        root = self.resolved_root
        if root is None:
            return {"status": "missing", "root": None, "next_action": None, "path": None}
        rel = "silas_aios/runtime/next_action.md"
        path = root / rel
        if not path.is_file():
            return {"status": "missing", "root": str(root), "next_action": None, "path": rel}
        return {
            "status": "ok",
            "root": str(root),
            "path": rel,
            "next_action": path.read_text(encoding="utf-8").strip(),
        }

    def search(self, query: str, *, domain: str = "all", limit: int = 8) -> Dict[str, Any]:
        root = self.resolved_root
        if root is None:
            return {"status": "missing", "root": None, "domain": domain, "query": query, "results": []}
        if domain == "all":
            return {
                "status": "ok",
                "root": str(root),
                "domain": "all",
                "query": query,
                "groups": [
                    self.search(query, domain="aios", limit=limit),
                    self.search(query, domain="skills", limit=limit),
                    self.search(query, domain="prompts", limit=limit),
                ],
            }
        if domain not in {"aios", "skills", "prompts"}:
            return {"status": "error", "error": f"unknown AIOS search domain: {domain}", "domain": domain}

        searcher = self._load_skilltree()
        base = {
            "aios": root / "silas_aios",
            "skills": root / ".codex" / "skills",
            "prompts": root / "self_improving_coding_prompts",
        }[domain]
        if not base.is_dir():
            return {"status": "missing", "root": str(root), "domain": domain, "query": query, "results": []}

        if searcher:
            results = self._skilltree_search(searcher, root, base, query, domain=domain, limit=limit)
            engine = searcher["source"]
        else:
            results = self._fallback_search(root, base, query, domain=domain, limit=limit)
            engine = "fallback_lexical"

        return {
            "status": "ok",
            "root": str(root),
            "domain": domain,
            "query": query,
            "engine": engine,
            "results": results,
        }

    def select_next(self, *, limit: int = 8) -> Dict[str, Any]:
        """Select the next lawful AIOS move and emit an advisory DNASequence candidate."""
        root = self.resolved_root
        status = self.status()
        if root is None:
            selected = self._candidate(
                "repair_aios_root",
                "Repair missing AIOS root",
                "Create or point CAVE at a project root containing silas_aios/AGENTS.md.",
                100,
                category="repair",
                required=True,
                evidence_files=[],
                reason="AIOS root could not be discovered.",
            )
            return self._selection_payload(None, status, selected, [selected], limit=limit)

        candidates = self._build_candidates(root, status)
        candidates.sort(key=lambda item: (-item["score"], item["id"]))
        selected = next(
            (item for item in candidates if not item.get("requires_approval") and item.get("status") != "completed"),
            self._candidate(
                "human_checkpoint",
                "Stop at human checkpoint",
                "All non-approval AIOS moves are complete; ask Isaac before global promotion, live wiring, store migration, or mutating skilltree operations.",
                0,
                category="checkpoint",
                status="checkpoint",
                reason="Only completed or approval-bound candidates remain.",
            ),
        )
        return self._selection_payload(root, status, selected, candidates, limit=limit)

    def _build_candidates(self, root: Path, status: Dict[str, Any]) -> List[Dict[str, Any]]:
        missing = status.get("missing", [])
        if missing:
            return [
                self._candidate(
                    "repair_aios_drift",
                    "Repair AIOS required-surface drift",
                    "Restore missing AIOS files before adding new organs.",
                    100,
                    category="repair",
                    evidence_files=["silas_aios/maps/drift_map.md"],
                    reason=f"AIOS status reports {len(missing)} missing required surface(s).",
                    metadata={"missing": missing},
                )
            ]

        next_text = self._read(root, "silas_aios/runtime/next_action.md")
        mutation_text = self._read(root, "silas_aios/queues/mutation_queue.md")
        promotion_text = self._read(root, "silas_aios/queues/promotion_queue.md")
        selector_exists = (root / "silas_aios" / "runtime" / "selector_decision.json").is_file()
        adapter_complete = self._codex_skilltree_adapter_complete(root)

        candidates = [
            self._candidate(
                "codex_skilltree_adapter",
                "Design Codex adapter for skilltree tree/coherence operations",
                "Design and assay a Codex-safe adapter for skilltree tree/coherence operations without mutating .codex/skills yet.",
                20 if adapter_complete else 86,
                category="adapter",
                status="completed" if adapter_complete else "candidate",
                evidence_files=[
                    "silas_aios/search/skilltree.md",
                    "silas_aios/adapters/codex_skilltree_adapter.md",
                    "silas_aios/maps/drift_map.md",
                    "silas_aios/queues/mutation_queue.md",
                ],
                reason=(
                    "AIOS-local Codex skilltree view is current."
                    if adapter_complete
                    else "This is inside the AIOS/CAVE boundary and advances skilltree integration without live mutation."
                ),
                metadata={"boundary": "no mutating skilltree commands without approval"},
            ),
            self._candidate(
                "live_cave_mcp_wiring",
                "Wire AIOS bridge into live CAVE/MCP runtime",
                "Start or configure live daemon/MCP access to the AIOS bridge after approval.",
                70,
                category="wiring",
                requires_approval=True,
                evidence_files=["cave/cave/mcp/cognition_mcp.py", "cave/cave/server/http_server.py"],
                reason="Live daemon or hook wiring is outside the current no-surprises boundary.",
            ),
            self._candidate(
                "global_aios_promotion",
                "Promote tiny AIOS definition into global SILAS rules",
                "Patch global SILAS rules with the minimal AIOS definition after approval.",
                30,
                category="promotion",
                requires_approval=True,
                evidence_files=["silas_aios/queues/promotion_queue.md"],
                reason="Global rules are outside the AIOS/CAVE write boundary.",
            ),
            self._candidate(
                "state_store_migration",
                "Evaluate authoritative AIOS state-store migration",
                "Decide whether Markdown remains source of truth or SQLite becomes canonical after more retrieval evidence.",
                40,
                category="store",
                requires_approval=True,
                evidence_files=["silas_aios/ledgers/context_ledger.md"],
                reason="Making a store authoritative is an architectural boundary decision.",
            ),
        ]

        if selector_exists:
            candidates.append(
                self._candidate(
                    "selector_policy",
                    "Selector policy is installed",
                    "Maintain selector policy and use it to choose the next bounded organ.",
                    10,
                    category="selector",
                    status="completed",
                    evidence_files=["silas_aios/runtime/selector_decision.json"],
                    reason="Selector output already exists.",
                )
            )
        else:
            candidates.append(
                self._candidate(
                    "selector_policy",
                    "Install selector policy",
                    "Create selector policy and persist the first selector decision.",
                    95,
                    category="selector",
                    evidence_files=["silas_aios/selector/policy.md"],
                    reason="AIOS lacks a persisted selector decision.",
                )
            )

        if "Codex adapter" in next_text or "skilltree" in mutation_text:
            self._boost(candidates, "codex_skilltree_adapter", 8, "runtime/queues name the skilltree Codex adapter as a frontier.")
        if "global" in promotion_text.lower():
            self._boost(candidates, "global_aios_promotion", 5, "promotion queue contains global AIOS promotion.")
        return candidates

    def _selection_payload(
        self,
        root: Optional[Path],
        status: Dict[str, Any],
        selected: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        *,
        limit: int,
    ) -> Dict[str, Any]:
        limited = candidates[:limit]
        dna_sequence = self._dna_sequence_for(selected)
        return {
            "status": "ok" if status.get("status") == "ok" else "drift",
            "root": str(root) if root else None,
            "selected": selected,
            "candidates": limited,
            "dna_sequence": dna_sequence,
            "note": "Advisory selection only; no action has been executed.",
        }

    def _dna_sequence_for(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        candidate_id = candidate["id"]
        return {
            "name": f"aios_{candidate_id}",
            "description": f"Advisory DNASequence for {candidate['title']}",
            "mode": "advisory",
            "metadata": {
                "source": "AIOSBridge.select_next",
                "selected_candidate": candidate_id,
                "requires_approval": candidate.get("requires_approval", False),
                "category": candidate.get("category"),
            },
            "steps": [
                {
                    "id": "observe",
                    "title": "Observe selected candidate context",
                    "prompt": f"Inspect the evidence files for `{candidate_id}` and confirm the boundary conditions before editing.",
                    "required": True,
                    "evidence_files": candidate.get("evidence_files", []),
                    "metadata": {"operator": "observe", "candidate": candidate_id},
                },
                {
                    "id": "act",
                    "title": candidate["title"],
                    "prompt": candidate["prompt"],
                    "required": True,
                    "evidence_files": candidate.get("evidence_files", []),
                    "metadata": {
                        "operator": "act",
                        "candidate": candidate_id,
                        "requires_approval": candidate.get("requires_approval", False),
                    },
                },
                {
                    "id": "assay",
                    "title": "Assay selected move",
                    "prompt": "Run focused verification and record evidence in AIOS maps/ledgers.",
                    "required": True,
                    "metadata": {"operator": "assay", "candidate": candidate_id},
                },
                {
                    "id": "checkpoint",
                    "title": "Checkpoint with Isaac",
                    "prompt": "Summarize evidence, update AIOS next action, and stop before crossing any approval boundary.",
                    "required": True,
                    "metadata": {"operator": "checkpoint", "candidate": candidate_id},
                },
            ],
        }

    def _candidate(
        self,
        candidate_id: str,
        title: str,
        prompt: str,
        score: int,
        *,
        category: str,
        status: str = "candidate",
        requires_approval: bool = False,
        required: bool = False,
        evidence_files: Optional[List[str]] = None,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": candidate_id,
            "title": title,
            "prompt": prompt,
            "score": score,
            "category": category,
            "status": status,
            "requires_approval": requires_approval,
            "required": required,
            "evidence_files": evidence_files or [],
            "reason": reason,
            "metadata": metadata or {},
        }

    def _boost(self, candidates: List[Dict[str, Any]], candidate_id: str, amount: int, reason: str) -> None:
        for candidate in candidates:
            if candidate["id"] == candidate_id:
                candidate["score"] += amount
                candidate["reason"] = f"{candidate['reason']} {reason}".strip()
                break

    def _read(self, root: Path, rel: str) -> str:
        path = root / rel
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _codex_skilltree_adapter_complete(self, root: Path) -> bool:
        required = [
            root / "silas_aios" / "adapters" / "codex_skilltree_adapter.md",
            root / ".codex" / "skills" / "sic-silas-aios" / "scripts" / "aios_skilltree_adapter.py",
        ]
        if any(not path.is_file() for path in required):
            return False

        skills_root = root / ".codex" / "skills"
        view_skills = root / "silas_aios" / "runtime" / "skilltree_codex_view" / ".claude" / "skills"
        if not skills_root.is_dir() or not view_skills.is_dir():
            return False

        skill_dirs = sorted(
            path for path in skills_root.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        )
        if not skill_dirs:
            return False

        for skill_dir in skill_dirs:
            link = view_skills / skill_dir.name
            if not link.is_symlink() or link.resolve() != skill_dir.resolve():
                return False
        return True

    def _load_skilltree(self) -> Optional[Dict[str, Any]]:
        sources = []
        if self.skilltree_src is not None:
            sources.append(Path(self.skilltree_src))
        root = self.resolved_root
        if root is not None:
            sources.append(root / "external_repos" / "skilltree" / "src")

        for source in sources:
            if not source.is_dir():
                continue
            sys.path.insert(0, str(source))
            try:
                from skilltree.search import DEFAULT_EXTS as exts, build_index, search, search_folder

                return {
                    "DEFAULT_EXTS": exts,
                    "build_index": build_index,
                    "search": search,
                    "search_folder": search_folder,
                    "source": str(source),
                }
            except ImportError:
                continue

        if self.use_installed_skilltree:
            try:
                from skilltree.search import DEFAULT_EXTS as exts, build_index, search, search_folder

                return {
                    "DEFAULT_EXTS": exts,
                    "build_index": build_index,
                    "search": search,
                    "search_folder": search_folder,
                    "source": "installed",
                }
            except ImportError:
                return None
        return None

    def _skilltree_search(
        self,
        searcher: Dict[str, Any],
        root: Path,
        base: Path,
        query: str,
        *,
        domain: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        if domain == "skills":
            con = searcher["build_index"](base, exts=None)
            hits = searcher["search"](con, query, limit=limit)
        else:
            hits = searcher["search_folder"](base, query, exts=searcher["DEFAULT_EXTS"], limit=limit)
        return [self._normalize_hit(root, domain, hit) for hit in hits]

    def _fallback_search(
        self,
        root: Path,
        base: Path,
        query: str,
        *,
        domain: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        if domain == "skills":
            hits = _lexical_search(base, query, limit=limit, exts=(".md",))
        else:
            hits = _lexical_search(base, query, limit=limit)
        return [self._normalize_hit(root, domain, hit) for hit in hits]

    def _normalize_hit(self, root: Path, domain: str, hit: Dict[str, Any]) -> Dict[str, Any]:
        path_value = hit.get("path", "")
        try:
            rel = str(Path(path_value).resolve().relative_to(root))
        except (ValueError, OSError):
            rel = str(path_value)
        return {
            "domain": domain,
            "name": hit.get("name", ""),
            "coord": hit.get("coord", "") or "",
            "description": hit.get("description", "") or "",
            "path": rel,
            "score": hit.get("score"),
        }
