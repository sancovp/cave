"""Dynamic status functions for Conductor prompt injection.

Called by Heaven's prompt_suffix_blocks via dynamic_call= at prompt time.
Each function returns a string that gets appended to Conductor's system prompt.
Always fresh — no file caching needed.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

HEAVEN_DATA = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))


def get_agent_status(**kwargs) -> str:
    """What each CAVE agent is currently doing."""
    try:
        from cave.core.cave_agent import CAVEAgent
        # Try to get the running WakingDreamer instance
        try:
            from sanctuary_revolution.harness.server.waking_dreamer import WakingDreamer
            wd = WakingDreamer()
            status = wd.get_agent_status()
        except Exception:
            status = {}

        if not status:
            return ""

        lines = ["# Agent Status"]
        for name, info in status.items():
            lines.append(f"- **{name}** ({info.get('type', '?')}): inbox={info.get('inbox_count', 0)}, channels={info.get('channels', [])}")
        lines.append(f"\n_Updated: {datetime.utcnow().strftime('%H:%M:%S')}_")
        return "\n".join(lines)
    except Exception as e:
        logger.error("get_agent_status failed: %s", e)
        return ""


def get_sanctum_status(**kwargs) -> str:
    """Today's ritual completion status, GEAR scores, streaks."""
    try:
        # Find active sanctum
        config_path = HEAVEN_DATA / "sanctums" / "_config.json"
        if not config_path.exists():
            return ""

        config = json.loads(config_path.read_text())
        sanctum_name = config.get("current", "")
        if not sanctum_name:
            return ""

        sanctum_path = HEAVEN_DATA / "sanctums" / f"{sanctum_name}.json"
        if not sanctum_path.exists():
            return ""

        sanctum = json.loads(sanctum_path.read_text())
        rituals = sanctum.get("rituals", [])
        if not rituals:
            return ""

        # Count completions
        today = datetime.now().strftime("%Y-%m-%d")
        total = len([r for r in rituals if r.get("active", True)])
        done = 0
        done_names = []
        pending_names = []

        for r in rituals:
            if not r.get("active", True):
                continue
            completions = r.get("completions", [])
            if any(c.get("date", "").startswith(today) for c in completions):
                done += 1
                done_names.append(r["name"])
            else:
                pending_names.append(r["name"])

        # GEAR scores
        gear = sanctum.get("gear", {})
        domains = sanctum.get("domains", {})

        lines = [f"# Sanctum Status — {sanctum_name}"]
        lines.append(f"**Rituals today:** {done}/{total}")
        if done_names:
            lines.append(f"  Done: {', '.join(done_names)}")
        if pending_names:
            lines.append(f"  Pending: {', '.join(pending_names)}")

        if domains:
            lines.append("\n**Domain Scores:**")
            for domain, score in domains.items():
                lines.append(f"  {domain}: {score}/10")

        if gear:
            composite = gear.get("composite", 0)
            state = "Sanctuary" if composite >= 0.75 else "Wasteland"
            lines.append(f"\n**GEAR Composite:** {composite:.2f} ({state})")

        return "\n".join(lines)
    except Exception as e:
        logger.error("get_sanctum_status failed: %s", e)
        return ""


def get_social_queue(**kwargs) -> str:
    """Pending social content drafts for review."""
    try:
        queue_dir = HEAVEN_DATA / "social_queue"
        if not queue_dir.exists():
            return ""

        drafts = list(queue_dir.glob("*.json"))
        if not drafts:
            return ""

        lines = [f"# Social Queue — {len(drafts)} draft(s)"]
        for draft_path in sorted(drafts)[:5]:  # Show max 5
            try:
                draft = json.loads(draft_path.read_text())
                title = draft.get("title", draft_path.stem)
                status = draft.get("status", "pending")
                lines.append(f"- [{status}] {title}")
            except Exception:
                lines.append(f"- [error] {draft_path.stem}")

        return "\n".join(lines)
    except Exception as e:
        logger.error("get_social_queue failed: %s", e)
        return ""


def get_task_summary(**kwargs) -> str:
    """Current task state from TreeKanban."""
    try:
        tasks_file = HEAVEN_DATA / "conductor_dynamic" / "tasks.txt"
        if tasks_file.exists():
            return tasks_file.read_text()
        return ""
    except Exception:
        return ""
