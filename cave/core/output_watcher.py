"""
Output Watcher - Parse Claude Code terminal output for events.

Watches tmux capture-pane output and emits events when patterns match.
This is how we get block reports, giint responses, etc. out to Railgun.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events we detect in terminal output."""
    BLOCK_REPORT = "block_report"
    GIINT_RESPONSE = "giint_response"
    COGLOG = "coglog"
    SKILLLOG = "skilllog"
    DELIVERABLELOG = "deliverablelog"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    CONTEXT_WARNING = "context_warning"
    AUTOPOIESIS = "autopoiesis"
    INJECTION = "injection"  # Events injected by harness
    CUSTOM = "custom"


@dataclass
class DetectedEvent:
    """An event detected in terminal output."""
    event_type: EventType
    content: str
    raw_match: str
    line_number: Optional[int] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class PatternMatcher:
    """A pattern to match in terminal output."""
    event_type: EventType
    pattern: re.Pattern
    extract_content: Optional[Callable[[re.Match], str]] = None
    extract_metadata: Optional[Callable[[re.Match], dict]] = None


class OutputWatcher:
    """Watch terminal output and detect events.

    Usage:
        watcher = OutputWatcher()
        new_events = watcher.process_output(terminal_content)
        for event in new_events:
            emit_to_railgun(event)
    """

    # Default patterns for Claude Code output
    DEFAULT_PATTERNS = [
        # Block reports - autopoiesis blocked state
        PatternMatcher(
            event_type=EventType.BLOCK_REPORT,
            pattern=re.compile(r'\[BLOCKED\](.+?)(?=\n\n|\Z)', re.DOTALL),
            extract_content=lambda m: m.group(1).strip()
        ),

        # GIINT responses - be_myself awareness
        PatternMatcher(
            event_type=EventType.GIINT_RESPONSE,
            pattern=re.compile(r'core__be_myself.*?certainty["\']:\s*(\d+)', re.DOTALL),
            extract_content=lambda m: m.group(0),
            extract_metadata=lambda m: {"certainty": int(m.group(1))}
        ),

        # CogLog - semantic addressing
        PatternMatcher(
            event_type=EventType.COGLOG,
            pattern=re.compile(r'🧠\s*(.+?)\s*🧠'),
            extract_content=lambda m: m.group(1)
        ),

        # SkillLog - skill predictions
        PatternMatcher(
            event_type=EventType.SKILLLOG,
            pattern=re.compile(r'🎯\s*(\w+)::(\w+)::(\w+)::(.+?)\s*🎯'),
            extract_content=lambda m: m.group(4),
            extract_metadata=lambda m: {
                "status": m.group(1),
                "domain": m.group(2),
                "subdomain": m.group(3),
                "skill_name": m.group(4)
            }
        ),

        # DeliverableLog - content pipeline
        PatternMatcher(
            event_type=EventType.DELIVERABLELOG,
            pattern=re.compile(r'📦\s*(\w+)::(\w+)::(.+?)\s*📦'),
            extract_content=lambda m: m.group(3),
            extract_metadata=lambda m: {
                "type": m.group(1),
                "domain": m.group(2),
                "title": m.group(3)
            }
        ),

        # Context warnings
        PatternMatcher(
            event_type=EventType.CONTEXT_WARNING,
            pattern=re.compile(r'ContextWindow:\s*(\d+)%'),
            extract_content=lambda m: f"Context at {m.group(1)}%",
            extract_metadata=lambda m: {"percentage": int(m.group(1))}
        ),

        # Autopoiesis mode changes
        PatternMatcher(
            event_type=EventType.AUTOPOIESIS,
            pattern=re.compile(r'be_autopoietic.*?mode["\']:\s*["\'](\w+)["\']'),
            extract_content=lambda m: m.group(1),
            extract_metadata=lambda m: {"mode": m.group(1)}
        ),

        # Tool calls (simplified pattern)
        PatternMatcher(
            event_type=EventType.TOOL_CALL,
            pattern=re.compile(r'<invoke name="([^"]+)"'),
            extract_content=lambda m: m.group(1),
            extract_metadata=lambda m: {"tool_name": m.group(1)}
        ),

        # Errors
        PatternMatcher(
            event_type=EventType.ERROR,
            pattern=re.compile(r'(?:Error|Exception|FAILED):\s*(.+?)(?=\n|$)', re.IGNORECASE),
            extract_content=lambda m: m.group(1)
        ),
    ]

    def __init__(self, patterns: Optional[list[PatternMatcher]] = None):
        """Initialize with patterns to match.

        Args:
            patterns: Custom patterns, or None for defaults
        """
        self.patterns = patterns or self.DEFAULT_PATTERNS
        self._last_content = ""
        self._seen_events: set[str] = set()  # Dedup by content hash

    def _get_new_content(self, full_content: str) -> str:
        """Extract only new content since last check."""
        if not self._last_content:
            return full_content

        # Find where old content ends in new content
        # Simple approach: if old is prefix of new, return suffix
        if full_content.startswith(self._last_content):
            return full_content[len(self._last_content):]

        # Content may have scrolled - find overlap
        # Look for last N chars of old in new
        overlap_size = min(500, len(self._last_content))
        old_tail = self._last_content[-overlap_size:]

        idx = full_content.find(old_tail)
        if idx >= 0:
            return full_content[idx + len(old_tail):]

        # No overlap found - treat all as new (terminal may have cleared)
        return full_content

    def process_output(self, terminal_content: str) -> list[DetectedEvent]:
        """Process terminal output and return new detected events.

        Args:
            terminal_content: Full terminal content from capture_pane()

        Returns:
            List of newly detected events (deduplicated)
        """
        new_content = self._get_new_content(terminal_content)
        self._last_content = terminal_content

        if not new_content.strip():
            return []

        events = []

        for pattern in self.patterns:
            for match in pattern.pattern.finditer(new_content):
                # Extract content
                if pattern.extract_content:
                    content = pattern.extract_content(match)
                else:
                    content = match.group(0)

                # Dedup check
                event_hash = f"{pattern.event_type.value}:{content[:100]}"
                if event_hash in self._seen_events:
                    continue
                self._seen_events.add(event_hash)

                # Limit seen events cache size
                if len(self._seen_events) > 1000:
                    # Remove oldest half
                    self._seen_events = set(list(self._seen_events)[500:])

                # Extract metadata
                metadata = {}
                if pattern.extract_metadata:
                    try:
                        metadata = pattern.extract_metadata(match)
                    except Exception as e:
                        logger.warning(f"Metadata extraction failed: {e}")

                events.append(DetectedEvent(
                    event_type=pattern.event_type,
                    content=content,
                    raw_match=match.group(0),
                    metadata=metadata
                ))

        if events:
            logger.info(f"Detected {len(events)} events: {[e.event_type.value for e in events]}")

        return events

    def add_pattern(self, pattern: PatternMatcher):
        """Add a custom pattern to watch for."""
        self.patterns.append(pattern)

    def reset(self):
        """Reset state (clear last content and seen events)."""
        self._last_content = ""
        self._seen_events.clear()
