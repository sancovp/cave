"""AnatomyMixin - Organs for CAVEAgent.

The agent body: Heart (pumps prompts), Blood (carries context), Ears (listen for messages).
"""
import asyncio
import logging
import os
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
    """Ears listen for incoming messages AND perceive the world.

    The perceptive organ of the Body. Two functions:
    1. Inbox polling — check_now() polls main_agent.check_inbox()
    2. World perception — perceive_world() polls world.tick() for events

    World perception is a Body function executed through Ears (not Heart).
    Heart pumps scheduled prompts. Ears perceives. Mind knows.

    Usage:
        ears = Ears(name="ears", poll_interval=5.0)
        ears.attach(cave_agent)
        ears.on_message(lambda responses: print(responses))
        ears.start()
    """
    name: str = "ears"
    poll_interval: float = 5.0
    proprioception_rate: float = 30.0
    _agent_ref: Optional[Any] = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    _task: Optional[Any] = field(default=None, repr=False)
    _messages_processed: int = field(default=0, repr=False)
    _world_events_processed: int = field(default=0, repr=False)
    _last_check: Optional[str] = field(default=None, repr=False)
    _last_perception: Optional[float] = field(default=None, repr=False)
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

    async def check_now(self) -> list:
        """Manual check — poll main agent inbox right now."""
        if not self._agent_ref or not hasattr(self._agent_ref, 'main_agent'):
            return []
        agent = self._agent_ref.main_agent
        if agent is None:
            return []

        self._last_check = datetime.utcnow().isoformat()
        responses = await agent.check_inbox()

        if responses:
            self._messages_processed += len(responses)
            for response in responses:
                for cb in self._callbacks:
                    try:
                        cb(response)
                    except Exception as e:
                        logger.error("Ears callback error: %s", e)

        return responses

    def perceive_world(self) -> list:
        """Perceive through channels AND world sources.

        Two input paths, unified:
        1. Channel perception: poll each agent's CentralChannel.receive_all()
           → feed results into agent inbox (Discord, tmux, file inbox channels)
        2. World perception: poll world.tick() for RNG/probabilistic events only

        ARCHITECTURE RULE (Isaac, Mar 01 2026):
        CaveAgent is the ONLY thing that ever runs. ALL event routing happens
        HERE inside CaveAgent's Ears. Nothing polls Discord outside this object.

        Channel-based routing (Discord, tmux, file):
        - Messages arrive via channel.receive() on each agent's CentralChannel
        - Ears feeds them into the agent's inbox
        - Discord routing: Isaac's messages → conductor, commands → CAVE endpoint

        World-based routing (RNG only):
        - Probabilistic events → injection file
        """
        if not self._agent_ref:
            return []

        now = time.time()
        if self._last_perception and (now - self._last_perception) < self.proprioception_rate:
            return []
        self._last_perception = now

        routed = []

        # === 1. CHANNEL PERCEPTION — poll all agent CentralChannels ===
        if hasattr(self._agent_ref, 'cave_agents') and hasattr(self._agent_ref, 'central_channels'):
            for agent_name, central in self._agent_ref.central_channels.items():
                messages = central.receive_all()
                for conv_name, msg_data in messages.items():
                    channel = central.get(conv_name)
                    ch_type = channel.channel_type() if channel else "unknown"

                    if "discord" in ch_type:
                        self._route_channel_discord_message(agent_name, conv_name, msg_data)
                    else:
                        # Non-discord channels: feed directly to agent inbox
                        agent = self._agent_ref.cave_agents.get(agent_name)
                        if agent:
                            from ..agent import UserPromptMessage, IngressType
                            content = msg_data.get("content", str(msg_data))
                            inbox_msg = UserPromptMessage(
                                content=content,
                                ingress=IngressType.SYSTEM,
                                priority=msg_data.get("priority", 0),
                            )
                            agent.enqueue(inbox_msg)

                    self._world_events_processed += 1
                    routed.append(msg_data)

        # === 2. WORLD PERCEPTION — RNG/probabilistic only ===
        if hasattr(self._agent_ref, 'world'):
            events = self._agent_ref.world.tick()
            for event in events:
                if event.source == "rng":
                    from ..organ_daemon import write_to_injection
                    write_to_injection(event)
                elif event.source == "sanctum":
                    from ..discord_config import load_discord_config
                    sanctum_ch = load_discord_config().get("sanctum_channel_id", "")
                    self._ping_discord(event.content, channel_id=sanctum_ch)
                    # Route journal/friendship rituals to autobiographer
                    self._route_sanctum_trigger(event)
                else:
                    self._agent_ref.route_message(
                        from_agent=f"world:{event.source}",
                        to_agent="main",
                        content=event.content,
                        priority=event.priority,
                    )
                routed.append(event)
                self._world_events_processed += 1

        return routed

    def _route_channel_discord_message(self, agent_name: str, conv_name: str, msg_data: Dict[str, Any]) -> None:
        """Route a message received from a Discord channel.

        Replaces _route_discord_event but works with Channel data instead of WorldEvent.
        """
        from ..organ_daemon import _detect_command, _handle_command
        from ..discord_config import load_discord_config

        if not hasattr(self, '_isaac_user_id'):
            discord_config = load_discord_config()
            self._isaac_user_id = discord_config.get("isaac_user_id")

        content = msg_data.get("content", "")
        metadata = msg_data.get("metadata", {})
        sender_id = metadata.get("discord_user_id", "")

        # Check for commands first
        cmd = _detect_command(content)
        if cmd:
            command, argument = cmd
            logger.info("Ears: command detected via channel: %s %s", command, argument)
            _handle_command(command, argument, source="discord")
            return

        # Route to the agent this channel belongs to
        agent = self._agent_ref.cave_agents.get(agent_name)
        if agent:
            from ..agent import UserPromptMessage, IngressType
            inbox_msg = UserPromptMessage(
                content=content,
                ingress=IngressType.DISCORD,
                priority=7,
                source_id=sender_id,
            )
            agent.enqueue(inbox_msg)
            logger.info("Ears: %s.%s <- discord: %s", agent_name, conv_name, content[:80])

            # Trigger inbox processing as async task — NEVER block Ears
            async def _process_agent_inbox(a=agent, name=agent_name):
                try:
                    responses = await a.check_inbox()
                    if responses:
                        logger.info("Ears: %s processed %d messages", name, len(responses))
                except Exception as e:
                    logger.error("Ears: %s inbox processing failed: %s", name, e)

            asyncio.create_task(_process_agent_inbox())

    def _route_discord_event(self, event) -> None:
        """Route a Discord WorldEvent. Runs INSIDE CaveAgent — never outside.

        NEVER create a separate World or DiscordChannelSource outside CaveAgent.
        All Discord routing flows through this method via Ears.perceive_world().

        Routing rules:
        1. Commands ("done X") → CAVE /sanctum/ritual/complete endpoint
        2. Isaac's messages (non-command) → conductor inbox
        3. Other users' messages → main inbox
        """
        from ..organ_daemon import _detect_command, _handle_command
        from ..discord_config import load_discord_config

        # Load isaac_user_id (cached after first load)
        if not hasattr(self, '_isaac_user_id'):
            discord_config = load_discord_config()
            self._isaac_user_id = discord_config.get("isaac_user_id")

        # Check for commands first
        is_command = False
        cmd = _detect_command(event.content)
        if cmd:
            command, argument = cmd
            logger.info("Ears: command detected: %s %s", command, argument)
            _handle_command(command, argument, source="discord")
            is_command = True
            event.metadata["command"] = True
            event.metadata["command_type"] = command
            event.metadata["command_arg"] = argument

        # Route by sender
        sender_id = event.metadata.get("discord_user_id", "")
        if self._isaac_user_id and sender_id == self._isaac_user_id and not is_command:
            # Isaac's messages → conductor inbox
            self._agent_ref.route_message(
                from_agent=f"world:{event.source}",
                to_agent="conductor",
                content=event.content,
                priority=event.priority,
                ingress="discord",
                metadata=event.metadata,
            )
            logger.info("Ears: Conductor <- Isaac: %s", event.content[:80])
        else:
            # Other messages → main inbox
            self._agent_ref.route_message(
                from_agent=f"world:{event.source}",
                to_agent="main",
                content=event.content,
                priority=event.priority,
            )
            logger.info("Ears: Inbox <- discord: %s%s", event.content[:80],
                        " [CMD]" if is_command else "")

    def _ping_discord(self, content: str, channel_id: str = "") -> None:
        """Send a message to Isaac via Discord. Best-effort, never blocks.

        Args:
            content: Message text
            channel_id: Optional override channel. If empty, uses default (private_chat_channel_id).
        """
        try:
            from ..channel import UserDiscordChannel
            if channel_id:
                discord = UserDiscordChannel(channel_id=channel_id)
            else:
                discord = UserDiscordChannel()
            if discord.token and discord.channel_id:
                discord.deliver({"message": content})
                logger.info("Ears: Discord ping (%s): %s", discord.channel_id[:6], content[:60])
        except Exception as e:
            logger.error("Ears: Discord ping failed: %s", e)

    # Sanctum ritual name → agent trigger mapping
    _RITUAL_TRIGGERS = {
        "morning-journal": {"agent": "autobiographer_journal", "mode": "journal_morning", "period": "morning"},
        "night-journal": {"agent": "autobiographer_journal", "mode": "journal_evening", "period": "evening"},
        "friendship-saturday": {"agent": "autobiographer_night", "job_type": "friendship"},
    }

    def _route_sanctum_trigger(self, event) -> None:
        """Route sanctum ritual events to the appropriate agent.

        When a journal/friendship ritual fires, enqueue a trigger message
        to the autobiographer or night agent so they start processing.
        """
        if not self._agent_ref or not hasattr(self._agent_ref, 'cave_agents'):
            return

        ritual_name = event.metadata.get("ritual_name", "")
        trigger = self._RITUAL_TRIGGERS.get(ritual_name)
        if not trigger:
            return

        agent_name = trigger.get("agent", "autobiographer")
        agent = self._agent_ref.cave_agents.get(agent_name)
        if not agent:
            logger.warning("Ears: sanctum trigger for %s but agent '%s' not found", ritual_name, agent_name)
            return

        # Build trigger message based on agent type
        if "job_type" in trigger:
            # ServiceAgent (night) — enqueue job dispatch
            from ..agent import UserPromptMessage, IngressType
            job_msg = UserPromptMessage(
                content=f"Run {trigger['job_type']} contextualization",
                ingress=IngressType.SYSTEM,
                priority=8,
            )
            agent.enqueue(job_msg)
            logger.info("Ears: sanctum trigger %s → %s job_type=%s", ritual_name, agent_name, trigger["job_type"])
        else:
            # ChatAgent (journal) — inject autocontext as prompt
            from ..agent import UserPromptMessage, IngressType
            from datetime import datetime as _dt
            mode = trigger.get('mode', 'journal')
            period = trigger.get('period', 'morning')
            today = _dt.now().strftime("%Y_%m_%d")
            period_cap = period.capitalize()

            # Try to load night agent's compiled autocontext
            autocontext = ""
            autocontext_path = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / f"journal_autocontext_{period}.txt"
            if autocontext_path.exists():
                try:
                    autocontext = autocontext_path.read_text().strip()
                except Exception:
                    pass

            if autocontext:
                content = (
                    f"Here is the context compiled from since the last journal:\n\n"
                    f"{autocontext}\n\n"
                    f"Contextually request my {period} journal now and work it out with me."
                )
            else:
                content = (
                    f"It's time for my {period} journal. "
                    f"Check CartON for Journal_Autocontext_{period_cap}_{today} if it exists. "
                    f"Then ask me for my {period} journal — walk through the 6 dimensions, "
                    f"ask how I'm feeling, and use journal_entry() to persist."
                )

            inbox_msg = UserPromptMessage(
                content=content,
                ingress=IngressType.SYSTEM,
                priority=8,
            )
            agent.enqueue(inbox_msg)
            logger.info("Ears: sanctum trigger %s → %s mode=%s period=%s", ritual_name, agent_name, mode, period)

    async def poll_loop(self):
        """Async poll loop — inbox + world perception.

        Start with asyncio.create_task(ears.poll_loop()).
        Inbox checked every poll_interval (5s).
        World perceived every proprioception_rate (30s), rate-limited internally.
        """
        logger.info("Ears poll_loop STARTING (poll=%.1fs, perception=%.1fs)", self.poll_interval, self.proprioception_rate)
        while self._running:
            try:
                await self.check_now()
                self.perceive_world()
            except Exception as e:
                logger.error("Ears poll_loop error (continuing): %s", e, exc_info=True)
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
            "proprioception_rate": self.proprioception_rate,
            "inbox_count": inbox_count,
            "messages_processed": self._messages_processed,
            "world_events_processed": self._world_events_processed,
            "last_check": self._last_check,
            "last_perception": self._last_perception,
            "callbacks": len(self._callbacks),
        }




class AnatomyMixin:
    """Mixin that gives CAVEAgent a body with organs.

    Provides:
        - heart: Heart that pumps scheduled prompts
        - blood: Blood that carries context
        - mind: Mind that dispatches awareness queries
        - organs: Dict of all organs

    Usage:
        cave_agent.heart.add_beat(heartbeat(...))
        cave_agent.heart.start()
        cave_agent.blood.carry("notes", notes_data)
        cave_agent.mind.dispatch("system")
    """
    
    def _init_anatomy(self) -> None:
        """Initialize the agent body."""
        self.organs: Dict[str, Organ] = {}
        self.heart = Heart(name="main_heart")
        self.blood = Blood()
        self.ears = Ears(name="ears")
        self.ears.attach(self)
        self._health_checks: Dict[str, Callable] = {}
        self._checkup_count: int = 0
        self._last_checkup: Optional[Dict[str, Any]] = None

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

    # === Health checks (body.checkup) ===

    def register_check(self, name: str, fn: Callable) -> None:
        """Register a health check on the Body.

        Each check is a callable returning a dict of domain-specific state.
        Called by checkup(). Mind (Conductor) calls checkup when it wants
        to know how the Body is doing.
        """
        self._health_checks[name] = fn
        logger.info("Body registered health check: %s", name)

    def unregister_check(self, name: str) -> bool:
        """Remove a health check."""
        return self._health_checks.pop(name, None) is not None

    def checkup(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Body checkup — calls all health checks, returns organ state.

        Args:
            domain: If given, run only that check. If None, run all.

        Returns:
            Dict of {check_name: state_dict}. Failed checks return {"error": str}.
        """
        result = {}
        targets = (
            {domain: self._health_checks[domain]}
            if domain and domain in self._health_checks
            else self._health_checks
        )

        for name, fn in targets.items():
            try:
                result[name] = fn()
            except Exception as e:
                logger.error("Health check '%s' error: %s", name, e)
                result[name] = {"error": str(e)}

        self._checkup_count += 1
        self._last_checkup = result
        return result
    
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

    def _wire_heartbeat(self) -> None:
        """Wire Heart interoception — agent checks its own internal state.

        Interoception rate = how often the agent prompts itself to check
        inbox, task status, organ health. Configured via heartbeat_config.json.
        Proprioception (world perception) is on Ears, not here.

        Uses Tick system and send_keys (proven via AgentInferenceLoop).
        Reads heartbeat_config.json for prompt, enabled, interval (interoception_rate).
        Checks user-active lock before sending.
        """
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        LOCK_PATH = _Path("/tmp/heaven_data/heartbeat_user_active.lock")
        LOCK_STALE = 300  # 5 minutes
        # CONNECTS_TO: /tmp/heaven_data/heartbeat_config.json (read/write) — heartbeat daemon config
        CONFIG_PATH = _Path("/tmp/heaven_data/heartbeat_config.json")
        # CONNECTS_TO: /tmp/heaven_data/heartbeat_log.jsonl (write) — heartbeat event log
        LOG_PATH = _Path("/tmp/heaven_data/heartbeat_log.jsonl")

        def _log(action, details=None):
            entry = {"ts": datetime.utcnow().isoformat(), "action": action, **(details or {})}
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, "a") as f:
                f.write(_json.dumps(entry) + "\n")

        def _heartbeat_tick():
            # Read config (hot-reloadable)
            if CONFIG_PATH.exists():
                try:
                    config = _json.loads(CONFIG_PATH.read_text())
                except Exception:
                    config = {}
            else:
                config = {}

            if not config.get("enabled", False):
                return

            # Check user-active lock
            if LOCK_PATH.exists():
                try:
                    lock = _json.loads(LOCK_PATH.read_text())
                    if (_time.time() - lock.get("ts", 0)) < LOCK_STALE:
                        _log("skipped_user_active")
                        return
                except Exception:
                    pass

            # Send prompt via tmux (same path as AgentInferenceLoop)
            prompt = config.get("prompt", "Heartbeat: check rituals, check inbox, report status.")
            if self.main_agent:
                self.main_agent.send_keys(prompt, 0.5, "Enter")
                _log("prompt_sent", {"prompt": prompt[:100]})
                logger.info("Heartbeat sent prompt to agent")
            else:
                _log("skipped_no_agent")

        # Read interval from config or default 900s
        every = 900.0
        if CONFIG_PATH.exists():
            try:
                every = float(_json.loads(CONFIG_PATH.read_text()).get("interval_seconds", 900))
            except Exception:
                pass

        self.heart.add_tick(Tick(
            name="heartbeat_prompt",
            callback=_heartbeat_tick,
            every=every,
        ))

    def _wire_conductor_heartbeat(self) -> None:
        """Wire Conductor heartbeat — periodic prompt to Conductor agent.

        Writes heartbeat message to Conductor's file inbox. If Conductor is
        currently processing, writes to a single pending file instead (latest
        overwrites). The inbox loop checks for pending heartbeat after each
        message processing completes.

        Interval configurable via conductor_heartbeat_config.json, default 300s (5 min).
        """
        import json as _json
        from pathlib import Path as _Path
        from datetime import datetime as _dt

        INBOX_DIR = _Path("/tmp/heaven_data/inboxes/conductor")
        # CONNECTS_TO: /tmp/heaven_data/conductor_ops/heartbeat/pending.json (write) — conductor heartbeat queue
        PENDING_FILE = _Path("/tmp/heaven_data/conductor_ops/heartbeat/pending.json")
        # CONNECTS_TO: /tmp/heaven_data/conductor_heartbeat_config.json (read/write) — conductor heartbeat config
        CONFIG_PATH = _Path("/tmp/heaven_data/conductor_heartbeat_config.json")
        PROCESSING_FLAG = _Path("/tmp/heaven_data/conductor_processing.flag")
        # CONNECTS_TO: /tmp/heaven_data/conductor_ops/heartbeat/last_user_message.txt (read/write)
        LAST_USER_MSG = _Path("/tmp/heaven_data/conductor_ops/heartbeat/last_user_message.txt")

        def _conductor_heartbeat_tick():
            # Check enabled flag from config
            if CONFIG_PATH.exists():
                try:
                    _cfg = _json.loads(CONFIG_PATH.read_text())
                    if not _cfg.get("enabled", False):
                        return
                except Exception:
                    pass

            # Skip if user was active within the heartbeat interval
            if LAST_USER_MSG.exists():
                try:
                    last_ts = _dt.fromisoformat(LAST_USER_MSG.read_text().strip())
                    elapsed = (_dt.utcnow() - last_ts).total_seconds()
                    if elapsed < every:
                        logger.debug("Heartbeat skipped — user active %.0fs ago", elapsed)
                        return
                except Exception:
                    pass

            now = _dt.utcnow().isoformat()
            # Use prompt from config or default
            prompt_text = "Heartbeat: check rituals, check inbox, report status."
            if CONFIG_PATH.exists():
                try:
                    prompt_text = _json.loads(CONFIG_PATH.read_text()).get("prompt", prompt_text)
                except Exception:
                    pass
            heartbeat_msg = {
                "content": f"<system>\u2764\uFE0F heartbeat {now}\n{prompt_text}</system>",
                "metadata": {"source": "heart", "type": "heartbeat"},
            }

            # Check if Conductor is currently processing
            # We check the flag file since we're in a different thread
            is_busy = PROCESSING_FLAG.exists()

            if is_busy:
                # Overwrite single pending file — latest heartbeat wins
                PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
                PENDING_FILE.write_text(_json.dumps(heartbeat_msg))
                logger.debug("Conductor busy — queued heartbeat to pending file")
            else:
                # Deliver directly to file inbox
                # DEDUP: Clear any existing heartbeat files first — only latest matters
                INBOX_DIR.mkdir(parents=True, exist_ok=True)
                for stale in INBOX_DIR.glob("heartbeat_*.json"):
                    try:
                        stale.unlink()
                        logger.debug("Cleared stale heartbeat: %s", stale.name)
                    except Exception:
                        pass
                fname = f"heartbeat_{now.replace(':', '-')}.json"
                (_Path(INBOX_DIR) / fname).write_text(_json.dumps(heartbeat_msg))
                logger.info("Heartbeat delivered to Conductor inbox")

        # Read interval from config or default 300s (5 min)
        every = 300.0
        if CONFIG_PATH.exists():
            try:
                every = float(_json.loads(CONFIG_PATH.read_text()).get("interval_seconds", 300))
            except Exception:
                pass

        self.heart.add_tick(Tick(
            name="conductor_heartbeat",
            callback=_conductor_heartbeat_tick,
            every=every,
        ))

    def _wire_perception_loop(self) -> None:
        """Wire Body perception through Ears via Heart tick.

        Ears.perceive_world() polls CentralChannels + World sources.
        Ears.check_now() polls inbox.
        Both run on a Heart tick (not async — Heart tick thread drives them).

        Must be called AFTER both _init_anatomy() and self.world exist.
        """
        self.ears.proprioception_rate = 30.0
        self.ears.start()  # Sets _running=True

        # Heart tick drives perception — perceive_world is sync, handles
        # CentralChannel polling + World sources. check_now is async/legacy
        # and cannot run from Heart's background thread (no event loop).
        def _perception_tick():
            self.ears.perceive_world()

        self.heart.add_tick(Tick(
            name="perception",
            callback=_perception_tick,
            every=30.0,
        ))

    def _wire_checkup(self) -> None:
        """Wire body health checks. Heart ticks checkup every 60s.

        Health checks are simple callables that read files for state.
        Results carried in Blood as 'checkup'. Called by Mind (Conductor)
        on demand via body.checkup(), or automatically via Heart tick.

        Checks:
        - system: organ daemon PID, heartbeat config
        - context: brainhook state, compaction cooldown
        - task: inbox count
        - code: arch lock state
        """
        import json as _json
        from pathlib import Path as _Path

        HEAVEN = _Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))

        def _system_check() -> Dict[str, Any]:
            result = {"organs": {}, "cpu_warning": False}
            pid_file = HEAVEN / "organ_daemon.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    result["organs"]["daemon"] = {"pid": pid, "alive": True}
                except (ValueError, ProcessLookupError, PermissionError):
                    result["organs"]["daemon"] = {"alive": False}
            hb_config = HEAVEN / "heartbeat_config.json"
            if hb_config.exists():
                try:
                    result["heartbeat"] = _json.loads(hb_config.read_text())
                except Exception:
                    result["heartbeat"] = {"error": "unreadable"}
            return result

        def _context_check() -> Dict[str, Any]:
            result = {}
            result["brainhook_active"] = (HEAVEN / "brainhook_active").exists()
            result["in_cooldown"] = (HEAVEN / "compaction_cooldown").exists()
            return result

        def _task_check() -> Dict[str, Any]:
            result = {"pending": 0, "in_progress": 0}
            inbox = HEAVEN / "inboxes" / "main"
            if inbox.exists():
                result["inbox_count"] = len(list(inbox.glob("*.json")))
            else:
                result["inbox_count"] = 0
            return result

        def _code_check() -> Dict[str, Any]:
            result = {}
            arch_lock = HEAVEN / "arch_lock.json"
            if arch_lock.exists():
                try:
                    result["arch_lock"] = _json.loads(arch_lock.read_text())
                except Exception:
                    result["arch_lock"] = {"error": "unreadable"}
            else:
                result["arch_lock"] = None
            return result

        self.register_check("system", _system_check)
        self.register_check("context", _context_check)
        self.register_check("task", _task_check)
        self.register_check("code", _code_check)

        # Heart ticks checkup every 60s, results flow into Blood
        def _checkup_tick():
            state = self.checkup()
            self.blood.carry("checkup", state)
            return state

        self.heart.add_tick(Tick(
            name="checkup_tick", callback=_checkup_tick, every=60.0
        ))
