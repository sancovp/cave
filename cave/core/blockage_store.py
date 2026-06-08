"""Blockage Store — tracks automation block reports with read/unread and resolution.

Append-only JSONL log. Each entry:
{
    "id": "blockage_20260508_230000",
    "automation": "daily_ralph_carton",
    "timestamp": "2026-05-08T23:00:00",
    "block_report": {completed_tasks, current_task, explanation, blocked_reason},
    "read": false,
    "resolved": false,
    "resolved_at": null,
    "resolved_by_run": null
}

Usage:
    from cave.core.blockage_store import BlockageStore
    store = BlockageStore()
    store.add("automation_name", block_report_dict)
    unread = store.get_unread()
    store.mark_read("blockage_id")
    store.mark_resolved("automation_name", run_id="ralph_20260509_030000")
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HEAVEN_DATA = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
STORE_PATH = HEAVEN_DATA / "automation_blockages.jsonl"


def _load_all() -> List[Dict[str, Any]]:
    """Load all blockage entries."""
    if not STORE_PATH.exists():
        return []
    entries = []
    for line in STORE_PATH.read_text().strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _save_all(entries: List[Dict[str, Any]]):
    """Rewrite all entries (for updates like mark_read)."""
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text("\n".join(json.dumps(e, default=str) for e in entries) + "\n")


def _append(entry: Dict[str, Any]):
    """Append a single entry."""
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


class BlockageStore:
    """Track automation block reports with read/unread and resolution lifecycle."""

    def add(self, automation: str, block_report: Dict[str, Any], run_id: str = "") -> str:
        """Add a new blockage entry. Returns blockage ID."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        blockage_id = f"blockage_{ts}"
        entry = {
            "id": blockage_id,
            "automation": automation,
            "timestamp": datetime.now().isoformat(),
            "block_report": block_report,
            "run_id": run_id,
            "read": False,
            "resolved": False,
            "resolved_at": None,
            "resolved_by_run": None,
        }
        _append(entry)
        logger.info("Blockage added: %s for %s", blockage_id, automation)
        return blockage_id

    def get_unread(self) -> List[Dict[str, Any]]:
        """Get all unread blockages."""
        return [e for e in _load_all() if not e.get("read")]

    def get_unresolved(self, automation: str = None) -> List[Dict[str, Any]]:
        """Get unresolved blockages, optionally filtered by automation name."""
        entries = _load_all()
        unresolved = [e for e in entries if not e.get("resolved")]
        if automation:
            unresolved = [e for e in unresolved if e.get("automation") == automation]
        return unresolved

    def get_all(self, automation: str = None) -> List[Dict[str, Any]]:
        """Get all blockages, optionally filtered."""
        entries = _load_all()
        if automation:
            entries = [e for e in entries if e.get("automation") == automation]
        return entries

    def mark_read(self, blockage_id: str = None, mark_all: bool = False) -> int:
        """Mark blockage(s) as read. Returns count marked."""
        entries = _load_all()
        count = 0
        for e in entries:
            if mark_all or e.get("id") == blockage_id:
                if not e.get("read"):
                    e["read"] = True
                    count += 1
        if count:
            _save_all(entries)
        return count

    def mark_resolved(self, automation: str, run_id: str = "") -> int:
        """Mark all unresolved blockages for an automation as resolved. Returns count."""
        entries = _load_all()
        count = 0
        now = datetime.now().isoformat()
        for e in entries:
            if e.get("automation") == automation and not e.get("resolved"):
                e["resolved"] = True
                e["resolved_at"] = now
                e["resolved_by_run"] = run_id
                count += 1
        if count:
            _save_all(entries)
            logger.info("Resolved %d blockage(s) for %s", count, automation)
        return count

    def summary(self) -> Dict[str, Any]:
        """Summary stats."""
        entries = _load_all()
        return {
            "total": len(entries),
            "unread": sum(1 for e in entries if not e.get("read")),
            "unresolved": sum(1 for e in entries if not e.get("resolved")),
            "resolved": sum(1 for e in entries if e.get("resolved")),
        }

    @staticmethod
    def read_block_report_from_history(agent_name: str, history_dir: str = None) -> Optional[Dict[str, Any]]:
        """Read the most recent block report from an agent's history files.

        Scans history JSON files for _current_extracted_content.block_report.
        Returns the block report dict or None.
        """
        if not history_dir:
            history_dir = str(HEAVEN_DATA / "agents" / agent_name / "memories" / "histories")
        hist_path = Path(history_dir)
        if not hist_path.exists():
            return None

        # Get most recent history file
        history_files = sorted(hist_path.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for hf in history_files[:5]:  # check last 5
            try:
                data = json.loads(hf.read_text())
                # Check agent_status for block report
                status = data.get("agent_status", {})
                if isinstance(status, dict):
                    block = status.get("block_report")
                    if block:
                        return {"source": str(hf), "block_report": block}
                # Check extracted_content
                extracted = data.get("extracted_content", {})
                if isinstance(extracted, dict):
                    block = extracted.get("block_report")
                    if block:
                        return {"source": str(hf), "block_report": block}
            except (json.JSONDecodeError, OSError):
                continue
        return None
