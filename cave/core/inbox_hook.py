"""Inbox notification hook — checks file inbox for pending items.

Registered as a PostToolUse CAVE hook. On every tool call, checks
/tmp/heaven_data/inboxes/main/ for unread JSON files. If found,
injects a notification into Claude Code context via additionalContext.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from cave import ClaudeCodeHook, HookType, HookResult, HookDecision

logger = logging.getLogger(__name__)


def _inbox_dir() -> Path:
    return Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "inboxes" / "main"


class InboxNotificationHook(ClaudeCodeHook):
    """Notify agent when inbox has pending items."""

    hook_type = HookType.POST_TOOL_USE

    def __init__(self):
        super().__init__(name="inbox_notification")

    def handle(self, payload: Dict[str, Any], state: Dict[str, Any]) -> HookResult:
        inbox = _inbox_dir()
        if not inbox.exists():
            return HookResult(HookDecision.CONTINUE)

        items = sorted(inbox.glob("*.json"))
        if not items:
            return HookResult(HookDecision.CONTINUE)

        sources: Dict[str, int] = {}
        for f in items:
            try:
                data = json.loads(f.read_text())
                src = data.get("from", "unknown").replace("world:", "")
                sources[src] = sources.get(src, 0) + 1
            except Exception:
                pass

        if not sources:
            return HookResult(HookDecision.CONTINUE)

        summary = ", ".join(f"{v} {k}" for k, v in sources.items())
        noti = f"📬 INBOX: {len(items)} items waiting ({summary}). Use /inbox to check."

        return HookResult(
            decision=HookDecision.CONTINUE,
            additional_context=noti,
        )
