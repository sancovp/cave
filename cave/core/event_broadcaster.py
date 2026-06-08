"""EventBroadcaster - bridges HeavenEvent → Channel delivery.

Single callback that parses langchain messages into HeavenEvents
and broadcasts to all registered Channels. Any agent can use this
to stream turn-by-turn output through its channels.

Usage:
    from cave.core.event_broadcaster import EventBroadcaster

    broadcaster = EventBroadcaster(agent.central_channel.main())
    result = await sdnac.execute(context=ctx, on_message=broadcaster)

TRUNCATION POLICY: NEVER truncate message content. EVER.
Discord has a 2000 char limit — we CHUNK, we do NOT truncate.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .channel import Channel

logger = logging.getLogger(__name__)

DISCORD_CHUNK_SIZE = 1900


def _chunk_text(text: str, chunk_size: int = DISCORD_CHUNK_SIZE) -> List[str]:
    """Split text into chunks. Prefers newline splits. NEVER truncates."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, chunk_size)
        if split_at <= 0:
            split_at = chunk_size
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    return chunks


class EventBroadcaster:
    """Heaven callback that formats HeavenEvents and delivers to a Channel.

    Parses raw langchain messages into HeavenEvents (TOOL_USE, TOOL_RESULT,
    AGENT_MESSAGE) and delivers formatted text through the given channel.

    This is the standard way ANY CAVE agent streams turn-by-turn output
    to its channel during execution.
    """

    def __init__(self, channel: Channel, label: str = "Agent"):
        self.channel = channel
        self.label = label
        self._tool_count = 0

    def __call__(self, raw_langchain_message):
        try:
            from heaven_base.memory.heaven_event import HeavenEvent
            events = HeavenEvent.from_langchain_message(raw_langchain_message)
            for event in events:
                ed = event.to_dict()
                self._deliver_event(ed)
        except Exception:
            # Fallback: parse langchain message directly
            try:
                self._fallback_parse(raw_langchain_message)
            except Exception as e2:
                logger.debug("EventBroadcaster fallback failed: %s", e2)

    def _deliver_event(self, ed: Dict[str, Any]):
        """Format a HeavenEvent dict and deliver to channel."""
        etype = ed.get("event_type")
        data = ed.get("data", {})

        if etype == "TOOL_USE":
            self._tool_count += 1
            name = data.get("name", "?")
            args = self._format_args(name, data.get("input", {}))
            msg = f"\U0001f527 `[{self._tool_count}]` **{name}**"
            if args:
                msg += f"\n```\n{args}\n```"
            self._deliver_chunked(msg)

        elif etype == "TOOL_RESULT":
            output = str(data.get("output", ""))
            if output:
                msg = f"\U0001f4cb `[{self._tool_count}]` result:\n```\n{output}\n```"
                self._deliver_chunked(msg)

        elif etype == "AGENT_MESSAGE":
            content = data.get("content", "")
            if content.strip():
                msg = f"\U0001f4ac **{self.label}:**\n{content}"
                self._deliver_chunked(msg)

        elif etype == "USER_MESSAGE":
            content = data.get("content", "")
            if content.strip():
                msg = f"\U0001f4e5 **Input:**\n{content}"
                self._deliver_chunked(msg)

    def _fallback_parse(self, msg):
        """Parse tool calls directly from langchain AIMessage/ToolMessage."""
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                self._tool_count += 1
                name = tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                args_str = self._format_args(name, args)
                out = f"\U0001f527 `[{self._tool_count}]` **{name}**"
                if args_str:
                    out += f"\n```\n{args_str}\n```"
                self._deliver_chunked(out)
        elif hasattr(msg, 'type') and msg.type == 'tool':
            content = str(getattr(msg, 'content', ''))
            if content:
                self._deliver_chunked(f"\U0001f4cb `[{self._tool_count}]` result:\n```\n{content}\n```")
        elif hasattr(msg, 'type') and msg.type == 'ai' and not getattr(msg, 'tool_calls', None):
            content = getattr(msg, 'content', '')
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = '\n'.join(text_parts)
            content = str(content)
            if content and content.strip():
                self._deliver_chunked(f"\U0001f4ac **{self.label}:**\n{content}")

    def _deliver_chunked(self, text: str):
        """Deliver to channel, chunking if needed. NEVER truncates."""
        chunks = _chunk_text(text)
        for chunk in chunks:
            try:
                self.channel.deliver({"message": chunk})
            except Exception as e:
                logger.error("EventBroadcaster delivery failed: %s", e)

    def _format_args(self, tool_name: str, tool_input: dict) -> str:
        """Format tool args for display. NO TRUNCATION."""
        if not tool_input:
            return ""
        if "command" in tool_input:
            return tool_input["command"]
        if "file_path" in tool_input:
            return tool_input["file_path"]
        try:
            return json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(tool_input)
