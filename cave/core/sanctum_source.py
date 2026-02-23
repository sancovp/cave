"""SANCTUM ritual EventSource for World.

Fires reminder WorldEvents when scheduled rituals are due.
Rituals are sequential — each starts after the previous one's duration.
Anchor time comes from sanctuary journal_config.json morning_time.

Data:
  - /tmp/heaven_data/sanctums/_config.json  → which sanctum is active
  - /tmp/heaven_data/sanctums/{name}.json   → ritual definitions
  - /tmp/heaven_data/sanctuary/journal_config.json → morning_time anchor
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .world import EventSource, WorldEvent

logger = logging.getLogger(__name__)

SANCTUMS_DIR = Path("/tmp/heaven_data/sanctums")
JOURNAL_CONFIG = Path("/tmp/heaven_data/sanctuary/journal_config.json")


REMINDED_STATE_FILE = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "sanctum_reminded.json"


class SanctumRitualSource(EventSource):
    """Deterministic event source: fires when SANCTUM rituals are due.

    Reads active sanctum, computes sequential schedule from morning_time
    anchor, fires reminder events at each ritual's start time.
    Resets daily. Tracks which rituals have been reminded today.
    Persists reminded state to disk so daemon restarts don't re-fire.
    """

    def __init__(
        self,
        name: str = "sanctum_rituals",
        sanctums_dir: Optional[Path] = None,
        journal_config_path: Optional[Path] = None,
        enabled: bool = True,
    ):
        super().__init__(name, enabled)
        self._sanctums_dir = sanctums_dir or SANCTUMS_DIR
        self._journal_config_path = journal_config_path or JOURNAL_CONFIG
        self._rituals: List[Dict[str, Any]] = []
        self._schedule: List[Tuple[str, str, datetime]] = []  # (name, desc, start_time)
        self._reminded_today: set = set()
        self._last_schedule_date: Optional[str] = None
        self._morning_time: str = "09:00"
        self._sanctum_name: str = ""
        self._restore_reminded_state()
        self._load()

    def _load(self) -> None:
        """Load active sanctum and compute schedule."""
        # Find active sanctum
        config_path = self._sanctums_dir / "_config.json"
        if not config_path.exists():
            logger.warning("No sanctum config at %s — source disabled", config_path)
            self.enabled = False
            return

        try:
            config = json.loads(config_path.read_text())
            self._sanctum_name = config.get("current", "")
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read sanctum config: %s", e)
            self.enabled = False
            return

        if not self._sanctum_name:
            self.enabled = False
            return

        # Load sanctum data
        sanctum_path = self._sanctums_dir / f"{self._sanctum_name}.json"
        if not sanctum_path.exists():
            logger.error("Sanctum file not found: %s", sanctum_path)
            self.enabled = False
            return

        try:
            sanctum = json.loads(sanctum_path.read_text())
            self._rituals = [r for r in sanctum.get("rituals", []) if r.get("active", True)]
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read sanctum: %s", e)
            self.enabled = False
            return

        # Load morning anchor time
        if self._journal_config_path.exists():
            try:
                jc = json.loads(self._journal_config_path.read_text())
                self._morning_time = jc.get("morning_time", "09:00")
            except (json.JSONDecodeError, OSError):
                pass

    def _restore_reminded_state(self) -> None:
        """Load reminded state from disk to survive daemon restarts."""
        if not REMINDED_STATE_FILE.exists():
            return
        try:
            data = json.loads(REMINDED_STATE_FILE.read_text())
            saved_date = data.get("date")
            today_str = datetime.now().strftime("%Y-%m-%d")
            if saved_date == today_str:
                self._reminded_today = set(data.get("reminded", []))
                self._last_schedule_date = saved_date
                logger.info("Restored reminded state: %s", self._reminded_today)
            else:
                logger.info("Reminded state from %s — stale, starting fresh", saved_date)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to restore reminded state: %s", e)

    def _persist_reminded_state(self) -> None:
        """Save reminded state to disk."""
        REMINDED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "date": self._last_schedule_date or datetime.now().strftime("%Y-%m-%d"),
            "reminded": list(self._reminded_today),
        }
        REMINDED_STATE_FILE.write_text(json.dumps(data))

    def _compute_schedule(self, today: datetime) -> None:
        """Compute today's ritual schedule from morning anchor."""
        date_str = today.strftime("%Y-%m-%d")
        if self._last_schedule_date == date_str:
            return  # Already computed for today

        h, m = map(int, self._morning_time.split(":"))
        current = today.replace(hour=h, minute=m, second=0, microsecond=0)

        self._schedule = []
        for ritual in self._rituals:
            self._schedule.append((
                ritual["name"],
                ritual.get("description", ""),
                current,
            ))
            duration = ritual.get("duration_minutes", 30)
            current = current + timedelta(minutes=duration)

        self._last_schedule_date = date_str
        self._reminded_today = set()  # Reset reminders for new day

    def poll(self, current_time: float) -> List[WorldEvent]:
        """Check if any rituals are due now."""
        if not self._rituals:
            return []

        now = datetime.fromtimestamp(current_time)
        self._compute_schedule(now)

        events = []
        for ritual_name, desc, start_time in self._schedule:
            if ritual_name in self._reminded_today:
                continue
            if now >= start_time:
                events.append(WorldEvent(
                    source="sanctum",
                    content=f"[SANCTUM] Ritual due: {ritual_name} — {desc}",
                    priority=6,
                    metadata={
                        "ritual_name": ritual_name,
                        "scheduled_time": start_time.isoformat(),
                        "sanctum": self._sanctum_name,
                    },
                ))
                self._reminded_today.add(ritual_name)

        if events:
            self._persist_reminded_state()

        return events

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "sanctum": self._sanctum_name,
            "morning_time": self._morning_time,
            "rituals": len(self._rituals),
            "reminded_today": list(self._reminded_today),
            "schedule": [
                {"name": n, "start": t.strftime("%H:%M")}
                for n, _, t in self._schedule
            ] if self._schedule else [],
        }

    @classmethod
    def from_config(cls) -> "SanctumRitualSource":
        """Factory: create from default config paths."""
        return cls()
