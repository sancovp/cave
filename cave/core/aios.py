"""Read-only bridge from CAVE into a SILAS AIOS filesystem scaffold."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


DEFAULT_REQUIRED_PATHS = [
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
