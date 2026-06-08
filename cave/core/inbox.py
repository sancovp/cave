"""Inbox - Standalone priority queue with persistence.

CAVE_REFACTOR Stage 1: Extracted from CodeAgent.

A dumb priority queue. Knows nothing about agents, channels, routing,
or processing. Any agent type can have one. Channels feed into it,
agents drain it. The inbox itself has no opinion about either.

Extracted methods (moved from CodeAgent):
    enqueue()     — was CodeAgent.enqueue()
    dequeue()     — was CodeAgent.dequeue()
    peek()        — was CodeAgent.peek()
    inbox_count   — was CodeAgent.inbox_count
    has_messages  — was CodeAgent.has_messages
    _save()       — was CodeAgent._save_inbox()
    _load()       — was CodeAgent._load_inbox()

Extracted config (moved from CodeAgentConfig):
    max_size          — was CodeAgentConfig.max_inbox_size
    state_file        — was CodeAgentConfig.state_file
    poll_interval     — was CodeAgentConfig.inbox_poll_interval
"""

import json
import logging
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# No import from agent.py — avoids circular import.
# Inbox is type-agnostic. It queues any object with .priority and .created_at.
# The agent layer enforces that only Any subtypes get enqueued.

logger = logging.getLogger(__name__)


@dataclass
class InboxConfig:
    """Configuration for an Inbox instance.

    Extracted from CodeAgentConfig — these are inbox concerns, not agent concerns.
    """
    max_size: int = 100
    state_file: Optional[str] = None
    poll_interval: float = 5.0  # seconds — used by the agent's poll loop, not by inbox itself


class Inbox:
    """Standalone priority queue with persistence.

    This is the queue primitive. It does not know about:
    - Agents (who processes messages)
    - Channels (where messages come from)
    - Routing (where responses go)
    - Processing (what happens to messages)

    It knows about:
    - Enqueueing messages with priority
    - Dequeueing highest-priority, oldest-first
    - Persisting to disk and loading back
    - Its own size limits
    """

    def __init__(self, config: Optional[InboxConfig] = None):
        self.config = config or InboxConfig()
        self._queue: deque = deque(maxlen=self.config.max_size)

        if self.config.state_file:
            self._load()

    def enqueue(self, message: Any) -> bool:
        """Add message to queue. Returns False if full."""
        if len(self._queue) >= self.config.max_size:
            return False

        self._queue.append(message)

        if self.config.state_file:
            self._save()

        return True

    def dequeue(self) -> Optional[Any]:
        """Remove and return highest-priority, oldest-first message."""
        if not self._queue:
            return None

        sorted_queue = sorted(
            self._queue,
            key=lambda m: (-m.priority, m.created_at)
        )

        message = sorted_queue[0]
        self._queue.remove(message)

        return message

    def peek(self) -> Optional[Any]:
        """Look at next message without removing it."""
        if not self._queue:
            return None
        sorted_queue = sorted(
            self._queue,
            key=lambda m: (-m.priority, m.created_at)
        )
        return sorted_queue[0]

    def clear(self):
        """Empty the queue."""
        self._queue.clear()

    @property
    def count(self) -> int:
        """Number of messages waiting."""
        return len(self._queue)

    @property
    def has_messages(self) -> bool:
        """Check if queue has messages."""
        return len(self._queue) > 0

    # ==================== PERSISTENCE ====================

    def _save(self):
        """Persist queue to disk."""
        if not self.config.state_file:
            return

        path = Path(self.config.state_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "saved_at": datetime.utcnow().isoformat(),
            "messages": [m.model_dump() for m in self._queue]
        }
        path.write_text(json.dumps(data, indent=2, default=str))

    def _load(self):
        """Load queue from disk."""
        if not self.config.state_file:
            return

        path = Path(self.config.state_file)
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text())
            for msg_data in data.get("messages", []):
                msg = Any(**msg_data)
                self._queue.append(msg)
            logger.info(f"Loaded {len(self._queue)} messages from inbox")
        except Exception as e:
            logger.error(f"Failed to load inbox: {e}\n{traceback.format_exc()}")

    def __repr__(self):
        return f"Inbox(count={self.count}, max={self.config.max_size})"
