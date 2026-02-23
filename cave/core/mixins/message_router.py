"""MessageRouter Mixin.

Provides message routing between agents for CAVEAgent.

Delivery strategy:
  1. If target agent is live in-memory (main_agent or future live agents),
     deliver via CodeAgent.enqueue() — typed InboxMessage, priority queue.
  2. Fallback: file-based JSON drop to data_dir/inboxes/{agent_id}/.
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import CAVEConfig

logger = logging.getLogger(__name__)


class MessageRouterMixin:
    """Mixin for message routing between agents."""

    config: "CAVEConfig"

    def _get_inbox_dir(self, agent_id: str) -> Path:
        """Get inbox directory for an agent."""
        inbox_dir = self.config.data_dir / "inboxes" / agent_id
        inbox_dir.mkdir(parents=True, exist_ok=True)
        return inbox_dir

    def _resolve_live_agent(self, agent_id: str):
        """Find a live in-memory CodeAgent by id. Returns agent or None.

        Checks main_agent first (the primary Claude Code session).
        "main" is an alias for whatever main_agent is.
        """
        if hasattr(self, 'main_agent') and self.main_agent is not None:
            main_id = getattr(self, 'paia_id', None) or getattr(self.main_agent, 'id', None)
            if agent_id in (main_id, "main"):
                return self.main_agent
        return None

    def route_message(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        **kwargs
    ) -> str:
        """Route a message between agents. Returns message_id.

        Tries in-memory delivery via enqueue() first, falls back to file.
        """
        message_id = str(uuid.uuid4())[:8]
        timestamp = datetime.utcnow().isoformat()

        # Try in-memory delivery to live agent
        target = self._resolve_live_agent(to_agent)
        if target is not None:
            try:
                from ..agent import InboxMessage, IngressType
                msg = InboxMessage(
                    content=content,
                    ingress=IngressType.SYSTEM,
                    priority=kwargs.get("priority", 0),
                )
                if target.enqueue(msg):
                    logger.info("Delivered message %s to %s via enqueue", message_id, to_agent)
                    return message_id
                logger.warning("enqueue() returned False for %s (inbox full?), falling back to file", to_agent)
            except Exception as e:
                logger.warning("In-memory delivery failed for %s: %s, falling back to file", to_agent, e)

        # Fallback: file-based delivery
        message = {
            "id": message_id,
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "timestamp": timestamp,
            **kwargs
        }

        inbox_dir = self._get_inbox_dir(to_agent)
        msg_file = inbox_dir / f"{timestamp}_{message_id}.json"
        msg_file.write_text(json.dumps(message, indent=2))
        logger.info("Delivered message %s to %s via file", message_id, to_agent)

        return message_id

    def get_inbox(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get an agent's inbox."""
        inbox_dir = self._get_inbox_dir(agent_id)
        messages = []

        for msg_file in sorted(inbox_dir.glob("*.json")):
            try:
                messages.append(json.loads(msg_file.read_text()))
            except json.JSONDecodeError:
                pass

        return messages

    def ack_message(self, agent_id: str, message_id: str) -> bool:
        """Acknowledge a message (remove from inbox)."""
        inbox_dir = self._get_inbox_dir(agent_id)

        for msg_file in inbox_dir.glob(f"*_{message_id}.json"):
            msg_file.unlink()
            return True

        return False

    def broadcast(self, from_agent: str, content: str, **kwargs) -> List[str]:
        """Broadcast to all agents. Returns list of message_ids."""
        message_ids = []

        # Broadcast to all registered agents
        if hasattr(self, 'agent_registry'):
            for agent_id in self.agent_registry:
                if agent_id != from_agent:
                    msg_id = self.route_message(from_agent, agent_id, content, **kwargs)
                    message_ids.append(msg_id)

        return message_ids

    def message_router_summary(self) -> Dict[str, Any]:
        """Get summary of message routing state."""
        summary = {"inboxes": {}}

        inboxes_dir = self.config.data_dir / "inboxes"
        if inboxes_dir.exists():
            for agent_dir in inboxes_dir.iterdir():
                if agent_dir.is_dir():
                    count = len(list(agent_dir.glob("*.json")))
                    summary["inboxes"][agent_dir.name] = count

        return summary
