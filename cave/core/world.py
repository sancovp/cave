"""World — The environment CAVEAgent lives in.

World is NOT an organ. It's what organs perceive. It contains event sources
that produce signals. Heart ticks World. Events flow through route_message
into Ears.

Event source types:
  - Deterministic: cron automations, scheduled rituals (AutomationMixin)
  - Probabilistic: RNG injections (RNGEventSource)
  - External: Discord DMs, webhooks, incoming API calls
  - Agent: other agents messaging in (already handled by route_message)
"""
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorldEvent:
    """An event produced by a source in the World."""
    source: str       # Which source produced this (e.g., "rng", "cron", "discord")
    content: str      # The event content / message
    priority: int = 0 # Higher = more urgent
    metadata: Dict[str, Any] = field(default_factory=dict)


class EventSource:
    """Base class for things that produce events in the World.

    Subclass and implement poll() to return events.
    """

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    def poll(self, current_time: float) -> List[WorldEvent]:
        """Poll for new events. Override in subclasses."""
        return []

    def status(self) -> Dict[str, Any]:
        return {"name": self.name, "enabled": self.enabled}


class CallableSource(EventSource):
    """EventSource wrapping a simple callable.

    For quick sources that don't need a full class:
        world.add_source("check_discord", CallableSource("discord", poll_fn))
    """

    def __init__(self, name: str, poll_fn: Callable[[float], List[WorldEvent]], enabled: bool = True):
        super().__init__(name, enabled)
        self._poll_fn = poll_fn

    def poll(self, current_time: float) -> List[WorldEvent]:
        return self._poll_fn(current_time)


@dataclass
class RNGEntry:
    """A probabilistic event definition."""
    name: str
    message: str
    probability: float  # 0.0 to 1.0
    priority: int = 5
    cooldown: float = 0.0  # seconds between fires
    condition: Optional[Callable[[], bool]] = None
    _last_fired: float = field(default=0.0, repr=False)

    def should_fire(self, t: float) -> bool:
        if self.cooldown and (t - self._last_fired) < self.cooldown:
            return False
        if self.condition and not self.condition():
            return False
        return random.random() < self.probability

    def fire(self, t: float) -> WorldEvent:
        self._last_fired = t
        return WorldEvent(source="rng", content=self.message, priority=self.priority,
                          metadata={"rng_event": self.name})


class RNGEventSource(EventSource):
    """Probabilistic event source. Ported from sancrev WorldModule."""

    def __init__(self, name: str = "rng", entries: Optional[List[RNGEntry]] = None,
                 enabled: bool = True):
        super().__init__(name, enabled)
        self.entries: List[RNGEntry] = entries or []

    def add(self, entry: RNGEntry) -> None:
        self.entries.append(entry)

    def poll(self, current_time: float) -> List[WorldEvent]:
        return [e.fire(current_time) for e in self.entries if e.should_fire(current_time)]

    def status(self) -> Dict[str, Any]:
        return {"name": self.name, "enabled": self.enabled,
                "entries": len(self.entries),
                "entry_names": [e.name for e in self.entries]}

    @classmethod
    def default_world_events(cls) -> "RNGEventSource":
        """Factory: default probabilistic world events."""
        src = cls(name="rng_world")
        src.add(RNGEntry("memory_resurface", "[WORLD] A memory from a previous session resurfaces...",
                         probability=0.08, cooldown=1200))
        src.add(RNGEntry("pattern_detected", "[WORLD] Strange resonance detected between projects...",
                         probability=0.05, cooldown=1800))
        src.add(RNGEntry("dream_insight", "[WORLD] Dream fragment: a connection forms in the dark...",
                         probability=0.02, priority=8, cooldown=3600))
        return src


class World:
    """The environment. Contains event sources, ticked by Heart."""

    def __init__(self):
        self._sources: Dict[str, EventSource] = {}
        self._tick_count: int = 0
        self._last_tick: float = 0.0
        self._total_events: int = 0

    def add_source(self, source: EventSource) -> None:
        """Register an event source."""
        self._sources[source.name] = source
        logger.info("World: added source '%s'", source.name)

    def remove_source(self, name: str) -> bool:
        """Remove an event source."""
        if name in self._sources:
            del self._sources[name]
            return True
        return False

    def enable_source(self, name: str) -> bool:
        if name in self._sources:
            self._sources[name].enabled = True
            return True
        return False

    def disable_source(self, name: str) -> bool:
        if name in self._sources:
            self._sources[name].enabled = False
            return True
        return False

    def tick(self) -> List[WorldEvent]:
        """Poll all enabled sources. Returns list of events.

        Called by Heart on schedule. Caller is responsible for
        delivering events via route_message into Ears.
        """
        current_time = time.time()
        self._tick_count += 1
        self._last_tick = current_time

        events = []
        for source in self._sources.values():
            if not source.enabled:
                continue
            try:
                source_events = source.poll(current_time)
                events.extend(source_events)
            except Exception as e:
                logger.error("World: source '%s' errored on tick: %s", source.name, e)

        self._total_events += len(events)
        return events

    def status(self) -> Dict[str, Any]:
        return {
            "sources": {name: s.status() for name, s in self._sources.items()},
            "tick_count": self._tick_count,
            "last_tick": self._last_tick,
            "total_events": self._total_events,
        }
