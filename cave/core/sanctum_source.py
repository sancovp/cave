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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .world import EventSource, WorldEvent

logger = logging.getLogger(__name__)

# CONNECTS_TO: /tmp/heaven_data/sanctums/ (read) — sanctum configs, triggers ritual scheduler
SANCTUMS_DIR = Path("/tmp/heaven_data/sanctums")
# CONNECTS_TO: /tmp/heaven_data/sanctuary/journal_config.json (read) — triggers Journal config / SD calculator
JOURNAL_CONFIG = Path("/tmp/heaven_data/sanctuary/journal_config.json")
REMINDED_STATE_FILE = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "sanctum_reminded.json"


class SanctumRitualSource(EventSource):
    """Fires when SANCTUM rituals are due.

    Every poll:
    1. Read the schedule fresh (rituals + morning anchor)
    2. Compute each ritual's start time
    3. If now >= start_time and not already notified → fire
    4. If past time and missed → fire anyway
    """

    def __init__(self, name: str = "sanctum_rituals", enabled: bool = True):
        super().__init__(name, enabled)
        self._sanctums_dir = SANCTUMS_DIR
        self._reminded_today: set = set()
        self._anchor_date: Optional[str] = None
        self._restore_reminded_state()

    def _get_morning_time(self) -> str:
        """Read morning anchor time from journal config."""
        if JOURNAL_CONFIG.exists():
            try:
                jc = json.loads(JOURNAL_CONFIG.read_text())
                return jc.get("morning_time", "09:00")
            except (json.JSONDecodeError, OSError):
                pass
        return "09:00"

    def _get_anchor(self, now: datetime) -> datetime:
        """Compute the most recent morning anchor."""
        morning = self._get_morning_time()
        h, m = map(int, morning.split(":"))
        anchor = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now < anchor:
            anchor = anchor - timedelta(days=1)
        return anchor

    def _load_todays_rituals(self, now: datetime) -> Tuple[str, List[Dict[str, Any]]]:
        """Load active sanctum and filter rituals for today. Called every poll."""
        config_path = self._sanctums_dir / "_config.json"
        if not config_path.exists():
            return "", []
        try:
            config = json.loads(config_path.read_text())
            sanctum_name = config.get("current", "")
            if not sanctum_name:
                return "", []
        except (json.JSONDecodeError, OSError):
            return "", []

        sanctum_path = self._sanctums_dir / f"{sanctum_name}.json"
        if not sanctum_path.exists():
            return sanctum_name, []

        try:
            sanctum = json.loads(sanctum_path.read_text())
        except (json.JSONDecodeError, OSError):
            return sanctum_name, []

        # Use the anchor date's day of week for filtering
        anchor = self._get_anchor(now)
        day_of_week = anchor.strftime("%A").lower()
        anchor_str = anchor.strftime("%Y-%m-%d")

        rituals = []
        for r in sanctum.get("rituals", []):
            if not r.get("active", True):
                continue
            freq = r.get("frequency", "daily").lower()
            if freq == "daily":
                rituals.append(r)
            elif freq == "weekly" and day_of_week in r.get("name", "").lower():
                rituals.append(r)
            elif freq == "monthly" and anchor.day == 1:
                rituals.append(r)

        # Exclude already-completed rituals
        for r in rituals:
            for c in r.get("completions", []):
                if str(c.get("date", "")).startswith(anchor_str):
                    self._reminded_today.add(r["name"])
                    break

        return sanctum_name, rituals

    def _compute_schedule(self, anchor: datetime, rituals: List[Dict[str, Any]]) -> List[Tuple[str, str, datetime]]:
        """Compute sequential schedule from morning anchor."""
        schedule = []
        current = anchor
        for r in rituals:
            schedule.append((
                r["name"],
                r.get("description", ""),
                current,
            ))
            current = current + timedelta(minutes=r.get("duration_minutes", 30))
        return schedule

    def _restore_reminded_state(self) -> None:
        """Load reminded state from disk."""
        if not REMINDED_STATE_FILE.exists():
            return
        try:
            data = json.loads(REMINDED_STATE_FILE.read_text())
            saved_date = data.get("date")
            if saved_date:
                self._reminded_today = set(data.get("reminded", []))
                self._anchor_date = saved_date
                logger.info("Restored reminded state for %s: %s", saved_date, self._reminded_today)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to restore reminded state: %s", e)

    def _persist_reminded_state(self, anchor_date: str) -> None:
        """Save reminded state to disk."""
        REMINDED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"date": anchor_date, "reminded": list(self._reminded_today)}
        REMINDED_STATE_FILE.write_text(json.dumps(data))

    _DAILY_INSTRUCTIONS = (
        "📋 **Ritual Channel — Daily Commands:**\n"
        "`done <ritual>` — mark ritual complete\n"
        "`skip <ritual>` — skip for today\n"
        "`status` — see today's schedule"
    )

    _JOURNAL_ORDER = ["morning-journal", "night-journal", "friendship-saturday"]

    def poll(self, current_time: float) -> List[WorldEvent]:
        """Check if any rituals are due now.

        Dead simple:
        1. Read schedule fresh
        2. Check the time
        3. If due and not reminded → fire
        4. If past time and missed → fire anyway
        """
        now = datetime.fromtimestamp(current_time)
        anchor = self._get_anchor(now)
        anchor_date = anchor.strftime("%Y-%m-%d")

        # New day → clear reminded set
        if self._anchor_date != anchor_date:
            logger.info("Day transition: %s → %s", self._anchor_date, anchor_date)
            self._reminded_today = set()
            self._anchor_date = anchor_date

        # Load rituals fresh every poll
        sanctum_name, rituals = self._load_todays_rituals(now)
        if not rituals:
            return []

        # Compute schedule from anchor
        schedule = self._compute_schedule(anchor, rituals)

        # Track if first notifications of the day
        was_empty = len(self._reminded_today) == 0

        # Find what's due
        newly_due = []
        for ritual_name, desc, start_time in schedule:
            if ritual_name in self._reminded_today:
                continue
            if now >= start_time:
                newly_due.append((ritual_name, desc, start_time))

        # Auto-skip missed journals if a later one is due
        due_journals = [r for r, _, _ in newly_due if r in self._JOURNAL_ORDER]
        if due_journals:
            latest_idx = max(self._JOURNAL_ORDER.index(j) for j in due_journals)
            for j in self._JOURNAL_ORDER[:latest_idx]:
                if j not in self._reminded_today:
                    self._reminded_today.add(j)
                    try:
                        from .sanctum_cli import handle_skip
                        handle_skip(j)
                        logger.info("Auto-skipped missed journal: %s", j)
                    except Exception as e:
                        logger.warning("Failed to auto-skip %s: %s", j, e)

        # Fire notifications
        events = []
        for ritual_name, desc, start_time in newly_due:
            if ritual_name in self._reminded_today:
                continue
            events.append(WorldEvent(
                source="sanctum",
                content=f"[SANCTUM] Ritual due: {ritual_name} — {desc}",
                priority=6,
                metadata={
                    "ritual_name": ritual_name,
                    "scheduled_time": start_time.isoformat(),
                    "sanctum": sanctum_name,
                },
            ))
            self._reminded_today.add(ritual_name)

        # Daily instructions on first batch
        if events and was_empty:
            events.insert(0, WorldEvent(
                source="sanctum",
                content=self._DAILY_INSTRUCTIONS,
                priority=5,
                metadata={"ritual_name": "_instructions", "sanctum": sanctum_name},
            ))

        if events:
            self._persist_reminded_state(anchor_date)

        return events

    def status(self) -> Dict[str, Any]:
        now = datetime.now()
        anchor = self._get_anchor(now)
        sanctum_name, rituals = self._load_todays_rituals(now)
        schedule = self._compute_schedule(anchor, rituals)
        return {
            "name": self.name,
            "enabled": self.enabled,
            "sanctum": sanctum_name,
            "morning_time": self._get_morning_time(),
            "anchor_date": self._anchor_date,
            "rituals": len(rituals),
            "reminded_today": list(self._reminded_today),
            "schedule": [
                {"name": n, "start": t.strftime("%H:%M")}
                for n, _, t in schedule
            ],
        }

    @classmethod
    def from_config(cls) -> "SanctumRitualSource":
        return cls()
