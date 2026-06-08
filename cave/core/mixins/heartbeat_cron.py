"""Heartbeat CronAutomation code pointer.

Called by the cron scheduler when conductor_heartbeat automation is due.
Writes heartbeat message to Conductor's file inbox, respecting:
- enabled flag from conductor_heartbeat_config.json
- processing flag (queue to pending if busy)
- last user message (skip if user was active recently)
- dedup (clear stale heartbeat files)
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

INBOX_DIR = Path("/tmp/heaven_data/inboxes/conductor")
# CONNECTS_TO: /tmp/heaven_data/conductor_ops/heartbeat/pending.json (write) — conductor heartbeat queue
PENDING_FILE = Path("/tmp/heaven_data/conductor_ops/heartbeat/pending.json")
# CONNECTS_TO: /tmp/heaven_data/conductor_heartbeat_config.json (read/write) — conductor heartbeat config
CONFIG_PATH = Path("/tmp/heaven_data/conductor_heartbeat_config.json")
PROCESSING_FLAG = Path("/tmp/heaven_data/conductor_processing.flag")
# CONNECTS_TO: /tmp/heaven_data/conductor_ops/heartbeat/last_user_message.txt (read/write)
LAST_USER_MSG = Path("/tmp/heaven_data/conductor_ops/heartbeat/last_user_message.txt")


def conductor_heartbeat_fire(**kwargs) -> dict:
    """Fire conductor heartbeat — write prompt to file inbox.

    This is the code_pointer for the conductor_heartbeat CronAutomation.
    Called by fire_due_automations() via the cron scheduler tick.
    """
    # Check enabled from config
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
            if not cfg.get("enabled", False):
                return {"status": "skipped", "reason": "disabled"}
        except Exception:
            pass

    # Read interval for user-active check
    every = 300.0
    if CONFIG_PATH.exists():
        try:
            every = float(json.loads(CONFIG_PATH.read_text()).get("interval_seconds", 300))
        except Exception:
            pass

    # Skip if user was active within the heartbeat interval
    if LAST_USER_MSG.exists():
        try:
            last_ts = datetime.fromisoformat(LAST_USER_MSG.read_text().strip())
            elapsed = (datetime.utcnow() - last_ts).total_seconds()
            if elapsed < every:
                logger.debug("Heartbeat skipped — user active %.0fs ago", elapsed)
                return {"status": "skipped", "reason": "user_active"}
        except Exception:
            pass

    now = datetime.utcnow().isoformat()
    prompt_text = "Heartbeat: check rituals, check inbox, report status."
    if CONFIG_PATH.exists():
        try:
            prompt_text = json.loads(CONFIG_PATH.read_text()).get("prompt", prompt_text)
        except Exception:
            pass

    heartbeat_msg = {
        "content": f"<system>\u2764\ufe0f heartbeat {now}\n{prompt_text}</system>",
        "metadata": {"source": "heart", "type": "heartbeat"},
    }

    is_busy = PROCESSING_FLAG.exists()

    if is_busy:
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_FILE.write_text(json.dumps(heartbeat_msg))
        logger.debug("Conductor busy — queued heartbeat to pending file")
        return {"status": "pending", "reason": "busy"}
    else:
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        # Dedup: clear stale heartbeat files
        for stale in INBOX_DIR.glob("heartbeat_*.json"):
            try:
                stale.unlink()
            except Exception:
                pass
        fname = f"heartbeat_{now.replace(':', '-')}.json"
        (INBOX_DIR / fname).write_text(json.dumps(heartbeat_msg))
        logger.info("Heartbeat delivered to Conductor inbox")
        return {"status": "delivered"}
