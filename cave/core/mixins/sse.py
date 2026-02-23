"""SSE Mixin.

Provides Server-Sent Events for CAVEAgent.
"""
import asyncio
import json
from datetime import datetime
from typing import Any, AsyncGenerator, Dict


class SSEMixin:
    """Mixin for Server-Sent Events."""

    event_queue: asyncio.Queue

    def _init_sse(self, maxsize: int = 1000) -> None:
        """Initialize SSE queue."""
        self.event_queue = asyncio.Queue(maxsize=maxsize)

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event to SSE subscribers."""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        try:
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop if queue full

    async def event_generator(self) -> AsyncGenerator[str, None]:
        """Generator for SSE endpoint."""
        while True:
            event = await self.event_queue.get()
            yield f"data: {json.dumps(event)}\n\n"

    def sse_status(self) -> Dict[str, Any]:
        """Get SSE queue status."""
        return {
            "queue_size": self.event_queue.qsize(),
            "queue_maxsize": self.event_queue.maxsize
        }
