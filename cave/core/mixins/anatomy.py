"""AnatomyMixin - Organs for CAVEAgent.

The agent body: Heart (pumps prompts), Blood (carries context), Ears (listen for messages).
"""
import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..cave_agent import CAVEAgent

logger = logging.getLogger(__name__)

# Try to import from SDNA
try:
    from sdna import Heartbeat, HeartbeatScheduler, heartbeat as create_heartbeat
    SDNA_AVAILABLE = True
except ImportError:
    SDNA_AVAILABLE = False
    logger.warning("SDNA not available - anatomy features limited")


@dataclass
class Organ:
    """Base class for agent body parts.
    
    Organs are components that give the agent capabilities.
    Each organ has a lifecycle and can be started/stopped.
    """
    name: str
    enabled: bool = True
    
    def start(self) -> Dict[str, Any]:
        """Start the organ."""
        raise NotImplementedError
    
    def stop(self) -> Dict[str, Any]:
        """Stop the organ."""
        raise NotImplementedError
    
    def status(self) -> Dict[str, Any]:
        """Get organ status."""
        return {"organ": self.name, "enabled": self.enabled}


@dataclass
class Tick:
    """A simple periodic callback. Lightweight sibling of SDNA Heartbeat.

    For internal agent functions (world.tick, organ sync) that don't
    need AriadneChain prompt delivery machinery.
    """
    name: str
    callback: Callable[[], Any]
    every: float  # seconds
    enabled: bool = True
    _last_run: Optional[float] = field(default=None, repr=False)
    _run_count: int = field(default=0, repr=False)

    def is_due(self) -> bool:
        if not self.enabled:
            return False
        if self._last_run is None:
            return True
        return (time.time() - self._last_run) >= self.every

    def execute(self) -> Any:
        self._last_run = time.time()
        self._run_count += 1
        return self.callback()


@dataclass
class Heart(Organ):
    """The heart pumps scheduled prompts to sessions.
    
    A Heart contains Heartbeats. When the heart is beating,
    it runs the HeartbeatScheduler to execute prompts on schedule.
    
    Usage:
        heart = Heart(name="main")
        heart.add_beat(heartbeat(...))
        heart.start()  # Begin beating
    """
    name: str = "heart"
    enabled: bool = True
    beats: List[Heartbeat] = field(default_factory=list)
    ticks: Dict[str, Tick] = field(default_factory=dict)
    _scheduler: Optional[HeartbeatScheduler] = field(default=None, repr=False)
    _beating: bool = field(default=False, repr=False)
    _tick_running: bool = field(default=False, repr=False)
    _tick_thread: Optional[threading.Thread] = field(default=None, repr=False)

    def __post_init__(self):
        if SDNA_AVAILABLE:
            self._scheduler = HeartbeatScheduler()
            for beat in self.beats:
                self._scheduler.add(beat)
    
    def add_beat(self, beat: Heartbeat) -> None:
        """Add a heartbeat to the heart."""
        self.beats.append(beat)
        if self._scheduler:
            self._scheduler.add(beat)
    
    def remove_beat(self, name: str) -> bool:
        """Remove a heartbeat by name."""
        self.beats = [b for b in self.beats if b.name != name]
        if self._scheduler:
            return self._scheduler.remove(name)
        return False

    def add_tick(self, tick: Tick) -> None:
        """Add a periodic callback tick."""
        self.ticks[tick.name] = tick

    def remove_tick(self, name: str) -> bool:
        """Remove a tick by name."""
        return self.ticks.pop(name, None) is not None

    def _run_tick_loop(self, interval: float) -> None:
        """Background thread: check and execute due ticks."""
        while self._tick_running:
            for tick in list(self.ticks.values()):
                if tick.is_due():
                    try:
                        tick.execute()
                    except Exception as e:
                        logger.error("Tick '%s' error: %s", tick.name, e)
            time.sleep(interval)

    def start(self, check_interval: float = 1.0) -> Dict[str, Any]:
        """Start the heart beating (SDNA scheduler + tick loop)."""
        if SDNA_AVAILABLE and self._scheduler:
            self._scheduler.start(check_interval)

        self._tick_running = True
        self._tick_thread = threading.Thread(
            target=self._run_tick_loop, args=(check_interval,), daemon=True
        )
        self._tick_thread.start()

        self._beating = True
        logger.info("Heart '%s' started beating", self.name)
        return {"status": "beating", "heartbeats": len(self.beats), "ticks": len(self.ticks)}

    def stop(self) -> Dict[str, Any]:
        """Stop the heart."""
        if self._scheduler:
            self._scheduler.stop()
        self._tick_running = False
        if self._tick_thread:
            self._tick_thread.join(timeout=5)
            self._tick_thread = None
        self._beating = False
        logger.info("Heart '%s' stopped", self.name)
        return {"status": "stopped"}

    def status(self) -> Dict[str, Any]:
        """Get heart status."""
        return {
            "organ": self.name,
            "type": "heart",
            "enabled": self.enabled,
            "beating": self._beating,
            "heartbeats": [b.name for b in self.beats],
            "ticks": {n: {"every": t.every, "runs": t._run_count} for n, t in self.ticks.items()},
            "scheduler": self._scheduler.status() if self._scheduler else None
        }


@dataclass
class Blood:
    """Blood carries context between organs and sessions.
    
    Blood is the state/context that flows through the agent.
    It can carry payloads from one session to another.
    
    Usage:
        blood = Blood()
        blood.carry("key", {"context": "data"})
        data = blood.get("key")
    """
    _payload: Dict[str, Any] = field(default_factory=dict)
    _flow_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def carry(self, key: str, data: Any) -> None:
        """Carry data in the blood."""
        self._payload[key] = data
        self._flow_history.append({
            "action": "carry",
            "key": key,
            "timestamp": __import__("datetime").datetime.now().isoformat()
        })
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get data from blood."""
        return self._payload.get(key, default)
    
    def drop(self, key: str) -> Any:
        """Drop and return data from blood."""
        data = self._payload.pop(key, None)
        if data:
            self._flow_history.append({
                "action": "drop",
                "key": key,
                "timestamp": __import__("datetime").datetime.now().isoformat()
            })
        return data
    
    def clear(self) -> None:
        """Clear all blood payload."""
        self._payload.clear()
    
    def status(self) -> Dict[str, Any]:
        """Get blood status."""
        return {
            "type": "blood",
            "carrying": list(self._payload.keys()),
            "recent_flow": self._flow_history[-5:] if self._flow_history else []
        }


@dataclass
class Ears(Organ):
    """Ears listen for incoming messages on the main agent inbox.

    Passive listener organ. Polls main_agent.check_inbox() on interval.
    When messages arrive, fires registered callbacks.

    Usage:
        ears = Ears(name="ears", poll_interval=5.0)
        ears.attach(cave_agent)
        ears.on_message(lambda responses: print(responses))
        ears.start()
    """
    name: str = "ears"
    poll_interval: float = 5.0
    _agent_ref: Optional[Any] = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    _task: Optional[Any] = field(default=None, repr=False)
    _messages_processed: int = field(default=0, repr=False)
    _last_check: Optional[str] = field(default=None, repr=False)
    _callbacks: List[Callable] = field(default_factory=list, repr=False)

    def attach(self, cave_agent) -> None:
        """Attach to a CAVEAgent to access its main_agent."""
        self._agent_ref = cave_agent

    def on_message(self, callback: Callable) -> None:
        """Register callback fired when messages are processed.

        Callback receives list of response Messages from check_inbox().
        """
        self._callbacks.append(callback)

    def start(self) -> Dict[str, Any]:
        """Start listening."""
        if self._agent_ref is None:
            return {"error": "No cave_agent attached — call attach() first"}
        self._running = True
        logger.info("Ears '%s' started listening (poll every %.1fs)", self.name, self.poll_interval)
        return {"status": "listening", "poll_interval": self.poll_interval}

    def stop(self) -> Dict[str, Any]:
        """Stop listening."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Ears '%s' stopped (processed %d messages)", self.name, self._messages_processed)
        return {"status": "stopped", "total_processed": self._messages_processed}

    def check_now(self) -> list:
        """Manual check — poll main agent inbox right now."""
        if not self._agent_ref or not hasattr(self._agent_ref, 'main_agent'):
            return []
        agent = self._agent_ref.main_agent
        if agent is None:
            return []

        self._last_check = datetime.utcnow().isoformat()
        responses = agent.check_inbox()

        if responses:
            self._messages_processed += len(responses)
            for response in responses:
                for cb in self._callbacks:
                    try:
                        cb(response)
                    except Exception as e:
                        logger.error("Ears callback error: %s", e)

        return responses

    async def poll_loop(self):
        """Async poll loop. Start with asyncio.create_task(ears.poll_loop())."""
        while self._running:
            self.check_now()
            await asyncio.sleep(self.poll_interval)

    def status(self) -> Dict[str, Any]:
        """Get ears status."""
        inbox_count = 0
        if self._agent_ref and hasattr(self._agent_ref, 'main_agent') and self._agent_ref.main_agent:
            inbox_count = self._agent_ref.main_agent.inbox_count
        return {
            "organ": self.name,
            "type": "ears",
            "enabled": self.enabled,
            "listening": self._running,
            "poll_interval": self.poll_interval,
            "inbox_count": inbox_count,
            "messages_processed": self._messages_processed,
            "last_check": self._last_check,
            "callbacks": len(self._callbacks),
        }


class AnatomyMixin:
    """Mixin that gives CAVEAgent a body with organs.
    
    Provides:
        - heart: Heart that pumps scheduled prompts
        - blood: Blood that carries context
        - organs: Dict of all organs
    
    Usage:
        cave_agent.heart.add_beat(heartbeat(...))
        cave_agent.heart.start()
        cave_agent.blood.carry("notes", notes_data)
    """
    
    def _init_anatomy(self) -> None:
        """Initialize the agent body."""
        self.organs: Dict[str, Organ] = {}
        self.heart = Heart(name="main_heart")
        self.blood = Blood()
        self.ears = Ears(name="ears")
        self.ears.attach(self)

        self.organs["heart"] = self.heart
        self.organs["ears"] = self.ears
    
    def add_organ(self, organ: Organ) -> None:
        """Add an organ to the body."""
        self.organs[organ.name] = organ
        logger.info(f"Added organ: {organ.name}")
    
    def remove_organ(self, name: str) -> bool:
        """Remove an organ."""
        if name in self.organs:
            organ = self.organs.pop(name)
            organ.stop()
            return True
        return False
    
    def start_organ(self, name: str) -> Dict[str, Any]:
        """Start an organ."""
        if name not in self.organs:
            return {"error": f"Organ '{name}' not found"}
        return self.organs[name].start()
    
    def stop_organ(self, name: str) -> Dict[str, Any]:
        """Stop an organ."""
        if name not in self.organs:
            return {"error": f"Organ '{name}' not found"}
        return self.organs[name].stop()
    
    def get_anatomy_status(self) -> Dict[str, Any]:
        """Get status of all organs and blood."""
        return {
            "organs": {name: organ.status() for name, organ in self.organs.items()},
            "blood": self.blood.status()
        }
    
    # === Convenience methods for Heart ===
    
    def add_heartbeat(
        self,
        name: str,
        session: str,
        ariadne: 'AriadneChain',
        every: Optional[int] = None,
        cron: Optional[str] = None,
        prompt: Optional[str] = None,
        on_deliver: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Add a heartbeat to the heart."""
        if not SDNA_AVAILABLE:
            return {"error": "SDNA not available"}

        beat = create_heartbeat(
            name=name,
            session=session,
            ariadne=ariadne,
            every=every,
            cron=cron,
            prompt=prompt,
            on_deliver=on_deliver
        )
        self.heart.add_beat(beat)
        return {"status": "added", "heartbeat": name}
    
    def start_heart(self) -> Dict[str, Any]:
        """Start the heart beating."""
        return self.heart.start()
    
    def stop_heart(self) -> Dict[str, Any]:
        """Stop the heart."""
        return self.heart.stop()

    def _wire_perception_loop(self) -> None:
        """Wire Heart -> World -> route_message -> Ears.

        Creates a Tick that polls world.tick() every 30s and routes
        each WorldEvent to "main" via route_message (-> enqueue -> Ears).
        Must be called AFTER both _init_anatomy() and self.world exist.
        """
        def _world_tick():
            events = self.world.tick()
            for event in events:
                self.route_message(
                    from_agent=f"world:{event.source}",
                    to_agent="main",
                    content=event.content,
                    priority=event.priority,
                )
            return len(events)

        self.heart.add_tick(Tick(
            name="world_tick", callback=_world_tick, every=30.0
        ))
