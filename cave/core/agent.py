"""
CodeAgent - Base class for code agents with Actor model inbox.

This is the fundamental building block. CodeAgent IS a llegos Actor,
meaning it has message passing as a first-class citizen.

CURRENT Hierarchy:
    CodeAgent(Actor)              # Base - any code agent, has inbox + tmux mixed
        └── ClaudeCodeAgent       # Claude-specific impl (tmux-based)
            └── ClaudeCodeSubAgent  # Isolated workers (claude -p based)

    PAIAAgent                     # Wraps CodeAgent with omnisanc/guru loop

# =============================================================================
# CAVE_REFACTOR: TARGET HIERARCHY (from CAVE_REFACTOR_ANALYSIS.md)
# =============================================================================
#
# Stage 1: Extract Inbox to standalone class — DONE (see inbox.py)
# Stage 2: Channels become bidirectional (add receive())
# Stage 3: Agent type hierarchy built on Inbox + Channels
#
# STAGE 1 COMPLETE: Inbox class lives in cave/core/inbox.py
# Next: CodeAgent.enqueue/dequeue/peek/_save_inbox/_load_inbox delegate to self.inbox
# Then: Agent base class gets self.inbox = Inbox(config)
#
#
# class Agent(Actor, ABC):
#     \"\"\"Base agent. Has Inbox. Stage 3.
#
#     Every agent in CAVE has an inbox. Push/pull behavior is
#     EMERGENT from how the agent's channels feed the inbox,
#     not from the inbox itself.
#     \"\"\"
#     inbox: Inbox
#     config: AgentConfig  # name, working_directory
#
#     def check_inbox(self) -> List[Message]: ...
#     def process_one(self) -> Optional[Message]: ...
#     def start(self): ...
#     def stop(self): ...
#
#
# class Channel:
#     \"\"\"A CONVERSATION the agent has. Stage 2.
#
#     A Channel IS a conversation with its own transcript/history.
#     NOT a transport pipe — a conversation track.
#     The transport (Discord API, tmux send-keys, file I/O) is just
#     how bytes move in and out of that conversation history.
#
#     Channel wraps the native history object (Heaven history,
#     Claude transcript, tmux capture, etc.)
#     \"\"\"
#     def deliver(self, payload) -> dict: ...   # send OUT through this conversation
#     def receive(self) -> Optional[dict]: ...  # receive IN from this conversation
#     def channel_type(self) -> str: ...
#
#
# class CentralChannel:
#     \"\"\"An agent's collection of conversation types. Stage 3 / Phase 5.
#
#     Every agent has a CentralChannel. It IS the set of conversations
#     that agent participates in. Each conversation is a Channel with
#     its own transcript/history.
#
#     Splitting main vs heartbeat = SEPARATE CONVERSATIONS with
#     SEPARATE TRANSCRIPTS. Not separate transports — separate histories.
#
#     Examples:
#       Conductor:      CentralChannel(main=discord_user_chat, heartbeat=heartbeat_convo)
#       Autobiographer: CentralChannel(chat=memory_chat, journal=journal_convo, night=night_convo)
#       GNOSYS:         CentralChannel(main=tmux_session)  # can't split, tmux is tmux
#       OpenClaw:       CentralChannel(main=discord_pipe)
#     \"\"\"
#     conversations: Dict[str, Channel]  # named conversation tracks
#
#
# CAVEAgent.CentralChannel:
#     \"\"\"The COMPLETE MAP of all agents and all their conversation types.
#
#     CAVEAgent.CentralChannel = {
#       conductor: CentralChannel(main, heartbeat),
#       autobiographer: CentralChannel(chat, journal, night),
#       gnosys: CentralChannel(main),
#       openclaw: CentralChannel(main),
#     }
#
#     Nadis = external channels (Discord channels, cron timers, webhooks)
#     that flow INTO agent CentralChannels:
#       Discord #conductor-whisper  →  conductor.main
#       Discord heartbeat timer     →  conductor.heartbeat
#       Discord #journal            →  autobiographer.journal
#       Cron 6AM/10PM               →  autobiographer.journal
#       tmux session                →  gnosys.main
#       Discord #openclaw           →  openclaw.main
#       Webhook /webhook/{name}     →  wherever automation routes
#
#     CAVEAgent.CentralChannel IS the routing table for the entire system.
#     \"\"\"
#
#
# class Agent(Actor, ABC):
#     \"\"\"Base agent. Has Inbox + CentralChannel. Stage 3.
#
#     EVERY agent has channels (conversations). The difference is
#     whether the channel is EXPOSED (user can see/interact) or
#     INTERNAL (only other agents/system can reach it).
#
#     Inbox MEDIATES across channels — messages from any of the
#     agent's channels get enqueued, agent processes in priority
#     order regardless of which channel they came from. Response
#     routes back to the originating channel (the right conversation).
#     \"\"\"
#     inbox: Inbox
#     central_channel: CentralChannel
#     config: AgentConfig
#
#     def check_inbox(self) -> List[Message]: ...
#     def process_one(self) -> Optional[Message]: ...
#     def start(self): ...
#     def stop(self): ...
#
#
# class ChatAgent(Agent):
#     \"\"\"Agent with conversational history channels. Stage 3.
#
#     Channel wraps a conversational history (Heaven/SDNA).
#     Channel is EXPOSED — user talks to it.
#
#     Push/pull EMERGENT from channel count:
#       1 conversation  → auto-serve (feels direct, push)
#       N conversations → auto-queue (agent polls, pull)
#
#     Extracts Conductor's current pattern:
#       BaseHeavenAgent-per-message, history, compaction, context overflow
#     \"\"\"
#     async def handle_message(self, msg): ...
#
#
# class CodeAgent(ChatAgent):
#     \"\"\"ChatAgent + tmux session management. Stage 3.
#
#     Channel wraps tmux/terminal session.
#     Channel exposure is GATED — kanban controls user access.
#     Can only send/receive through tmux, can't programmatically split.
#     \"\"\"
#     tmux_session: str
#     agent_command: str
#
#
# class ClawAgent(Agent):
#     \"\"\"External agent. Own config/lifecycle. Stage 3.
#
#     Channel wraps external agent's interface.
#     Channel is a PIPE — we don't manage the other side.
#     Still has inbox + CentralChannel like every agent.
#     \"\"\"
#
# =============================================================================
"""
import asyncio
import logging
import subprocess
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
import json
import os

from pydantic import Field, PrivateAttr

# Import llegos Actor model (LGPL-3.0)
# pip install -e /tmp/sanctuary-system/llegos
from llegos import Actor, Message, Object
from enum import Enum

from .inbox import Inbox, InboxConfig


class IngressType(str, Enum):
    """Ingress points for messages into the agent inbox.

    MVP: Only FRONTEND is active. Others stubbed for future.
    """
    FRONTEND = "frontend"      # Active - from http_server.py /send endpoint
    # Stubbed for future:
    EMAIL = "email"
    DISCORD = "discord"
    SLACK = "slack"
    SMS = "sms"
    WEBHOOK = "webhook"
    SYSTEM = "system"          # Internal system events

logger = logging.getLogger(__name__)


# =============================================================================
# MESSAGE TYPES
# =============================================================================

class InboxMessage(Message):
    """Base message for inbox delivery."""
    ingress: IngressType = IngressType.FRONTEND  # Where message came from
    priority: int = 0  # Higher = more urgent
    content: str = ""


class UserPromptMessage(InboxMessage):
    """Message from a user prompt (any ingress point)."""
    ingress: IngressType = IngressType.FRONTEND
    source_id: Optional[str] = None  # Who sent it (discord user id, email, etc.)


class SystemEventMessage(InboxMessage):
    """System-level events (hooks, timers, etc.)."""
    ingress: IngressType = IngressType.SYSTEM
    event_type: str = ""  # hook_fired, timer_tick, etc.
    event_data: Dict[str, Any] = Field(default_factory=dict)


class BlockedMessage(Message):
    """Agent is blocked and needs external input."""
    reason: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)
    blocking_question: Optional[str] = None


class CompletedMessage(Message):
    """Agent completed a task."""
    result: Any = None
    summary: str = ""


# =============================================================================
# CAVE_REFACTOR Stage 3: Agent Config + Type Hierarchy
# =============================================================================


@dataclass
class AgentConfig:
    """Base configuration for any agent."""
    name: str = "agent"
    working_directory: str = field(default_factory=os.getcwd)

    # Inbox settings
    inbox_poll_interval: float = 5.0
    max_inbox_size: int = 100
    state_file: Optional[str] = None


@dataclass
class CodeAgentConfig(AgentConfig):
    """Configuration for a code agent (ChatAgent + tmux).

    Extends AgentConfig with tmux-specific fields.
    """
    agent_command: str = ""  # e.g., "claude"
    tmux_session: str = "code-agent"

    # Response detection
    response_marker: str = ""  # e.g., "◇" for Claude Code
    poll_interval: float = 0.5
    max_wait_seconds: float = 300.0


class Agent(Actor):
    """Base agent. Has Inbox + CentralChannel + Runtime + Automations.

    An agent's behavior is defined by:
    - runtime: DI'd backend (BaseHeavenAgent, DUOChain, callable)
      Maps runtime.run/handle_message/__call__ to what agent.run() delegates to.
    - automations: List of InputAutomation that define the agent's "organs"
      EventAutomations feed the inbox, CronAutomations trigger polls,
      the run behavior itself is configurable through these.
    - inbox settings: push (run immediately on enqueue) vs pull (run on poll/heartbeat)

    Agent → automations compose into agents
    CAVEAgent → agents compose into higher-order organs
    Same pattern at both levels.

    CAVEAgent wires channel.receive() → inbox.enqueue() at runtime.
    """

    config: AgentConfig = Field(default_factory=AgentConfig)

    _inbox_instance: Any = PrivateAttr(default=None)
    _central_channel: Any = PrivateAttr(default=None)
    _runtime: Any = PrivateAttr(default=None)
    _automations: list = PrivateAttr(default_factory=list)
    _processing: bool = PrivateAttr(default=False)

    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        super().__init__(**kwargs)
        if config:
            self.config = config
        self._inbox_instance = Inbox(InboxConfig(
            max_size=self.config.max_inbox_size,
            state_file=self.config.state_file,
            poll_interval=self.config.inbox_poll_interval,
        ))
        self._central_channel = None  # Set by CAVEAgent wiring
        self._runtime = None
        self._automations = []
        self._processing = False

    # ==================== RUNTIME DI ====================

    def set_runtime(self, runtime: Any) -> None:
        """Inject the runtime backend. Any object with run(message), handle_message(message), or __call__."""
        self._runtime = runtime

    @property
    def runtime(self) -> Any:
        return self._runtime

    # ==================== AUTOMATIONS (ORGANS) ====================

    def add_automation(self, automation) -> None:
        """Add an automation (organ) to this agent."""
        self._automations.append(automation)

    def remove_automation(self, name: str) -> bool:
        """Remove an automation by name."""
        before = len(self._automations)
        self._automations = [a for a in self._automations if a.name != name]
        return len(self._automations) < before

    @property
    def automations(self) -> list:
        return self._automations

    # ==================== EVENT → AUTOMATION BRIDGE ====================

    def emit(self, event_name: str, data: Any = None) -> None:
        """Emit event AND check EventAutomations for matches.

        Extends llegos Actor.emit to bridge CAVE events to EventAutomations.
        Any EventAutomation on this agent that matches the event_name will fire.
        """
        super().emit(event_name, data)
        for auto in self._automations:
            if hasattr(auto, 'matches_event') and auto.matches_event(event_name):
                try:
                    auto.fire({"event": event_name, "data": data})
                    logger.info("EventAutomation '%s' fired on '%s'", auto.name, event_name)
                except Exception as e:
                    logger.error("EventAutomation '%s' failed: %s", auto.name, e)

    # ==================== RUN ====================

    async def run(self, message: Any = None) -> Any:
        """Execute the agent's behavior on a message.

        Delegates to the DI'd runtime. The runtime mapping:
        - has .run(msg) → call .run(msg)
        - has .handle_message(msg) → call .handle_message(msg)
        - is callable → call it directly
        - None → no-op, return None

        Handles both sync and async runtimes — awaits if result is a coroutine.

        This is what gets called when the inbox says to process.
        Push mode: called immediately on enqueue.
        Pull mode: called on poll tick / heartbeat.
        """
        if self._runtime is None:
            return None

        content = message.content if hasattr(message, 'content') else str(message) if message else ""

        if hasattr(self._runtime, 'run'):
            result = self._runtime.run(content)
        elif hasattr(self._runtime, 'handle_message'):
            result = self._runtime.handle_message(content)
        elif callable(self._runtime):
            result = self._runtime(content)
        else:
            return None

        # Await if runtime returned a coroutine (async runtime)
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            result = await result

        # Route result to deliverable channels
        if result is not None and self.central_channel:
            for conv_name, ch in self.central_channel.conversations.items():
                if hasattr(ch, 'is_deliverable') and ch.is_deliverable:
                    try:
                        ch.deliver({"deliverable": result, "agent": self.config.name})
                    except Exception as e:
                        logger.error("Deliverable routing to %s failed: %s", conv_name, e)

        return result

    # ==================== INBOX DELEGATION ====================

    @property
    def inbox(self) -> Inbox:
        return self._inbox_instance

    @property
    def central_channel(self):
        return self._central_channel

    @central_channel.setter
    def central_channel(self, value):
        self._central_channel = value

    def enqueue(self, message: InboxMessage) -> bool:
        """Add message to inbox. Called by ingress points."""
        result = self.inbox.enqueue(message)
        if result:
            self.emit("inbox:enqueued", message)
        else:
            self.emit("inbox:overflow", message)
        return result

    def dequeue(self) -> Optional[InboxMessage]:
        """Remove and return next message from inbox."""
        message = self.inbox.dequeue()
        if message:
            self.emit("inbox:dequeued", message)
        return message

    def peek(self) -> Optional[InboxMessage]:
        """Look at next message without removing it."""
        return self.inbox.peek()

    @property
    def inbox_count(self) -> int:
        return self.inbox.count

    @property
    def has_messages(self) -> bool:
        return self.inbox.has_messages

    # ==================== INBOX PROCESSING ====================

    async def check_inbox(self) -> List[Any]:
        """Check inbox and process all pending messages via run()."""
        if self._processing:
            return []

        self._processing = True
        responses = []

        try:
            while self.has_messages:
                message = self.dequeue()
                if message:
                    result = await self.run(message)
                    if result is not None:
                        responses.append(result)
        finally:
            self._processing = False

        return responses

    async def process_one(self) -> Any:
        """Process single message from inbox via run(). Returns result."""
        message = self.dequeue()
        if not message:
            return None
        return await self.run(message)

    # ==================== MESSAGE HANDLERS ====================

    def receive_user_prompt_message(self, message: UserPromptMessage) -> Iterator[Message]:
        self.emit("user_prompt:received", message)
        yield CompletedMessage(
            sender=self,
            receiver=message.sender,
            parent=message,
            summary=f"Received prompt from {message.ingress}"
        )

    def receive_system_event_message(self, message: SystemEventMessage) -> Iterator[Message]:
        self.emit("system_event:received", message)
        yield from []

    def receive_inbox_message(self, message: InboxMessage) -> Iterator[Message]:
        self.emit("inbox:received", message)
        yield from []

    # ==================== LIFECYCLE ====================

    def start(self):
        self.emit("agent:starting", {"agent_id": self.id})

    async def stop(self):
        self.emit("agent:stopping", {"agent_id": self.id})
        await self.check_inbox()
        self.inbox._save()

    async def run_poll_loop(self):
        logger.info("Agent '%s' poll_loop STARTING (interval=%.1fs)", self.config.name, self.config.inbox_poll_interval)
        while True:
            try:
                await asyncio.sleep(self.config.inbox_poll_interval)
                await self.check_inbox()
            except Exception as e:
                logger.error("Agent '%s' poll_loop error (continuing): %s", self.config.name, e, exc_info=True)


class ChatAgent(Agent):
    """Agent with conversational history channels.

    Channel wraps a conversational history (Heaven/SDNA).
    Channel is EXPOSED — user talks to it.

    Push/pull EMERGENT from channel count:
      1 conversation  → auto-serve (feels direct, push)
      N conversations → auto-queue (agent polls, pull)

    Runtime DI: ChatAgent wraps ANY runtime via dependency injection.
    The runtime is what actually processes messages — BaseHeavenAgent,
    DUOChain, or any object with a run(message, channel) method.
    ChatAgent provides CAVE infrastructure (inbox, channels, commands).
    The runtime provides the actual agent logic.

    User commands (!heartbeat, !stop, !prune, !new) are intercepted
    at the channel level BEFORE reaching the agent's processing.

    Queue behavior:
      - Process immediately when idle
      - Queue when busy
      - Drain queue in order when done
      - !stop clears the queue
    """

    config: AgentConfig = Field(default_factory=AgentConfig)
    _busy: bool = PrivateAttr(default=False)

    # runtime, set_runtime, automations inherited from Agent base

    # ==================== COMMAND INTERCEPTOR ====================

    def intercept_command(self, msg: InboxMessage) -> Optional[Dict[str, Any]]:
        """Intercept ! commands before they reach processing.

        Returns command result dict if intercepted, None if not a command.
        Commands are prefixed with ! and handled at the channel level.
        """
        content = msg.content.strip()
        if not content.startswith("!"):
            return None

        parts = content.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "!stop":
            return self._cmd_stop()
        elif cmd == "!new":
            return self._cmd_new()
        elif cmd == "!prune":
            return self._cmd_prune(args)
        elif cmd == "!heartbeat":
            return self._cmd_heartbeat(args)
        else:
            return {"error": f"Unknown command: {cmd}", "available": ["!stop", "!new", "!prune N", "!heartbeat"]}

    def _cmd_stop(self) -> Dict[str, Any]:
        """Abort current run, clear queue."""
        self._busy = False
        self.inbox.clear()
        self.emit("command:stop", {})
        return {"command": "stop", "status": "queue cleared, run aborted"}

    def _cmd_new(self) -> Dict[str, Any]:
        """Reset conversation — clear history, fresh session."""
        self._busy = False
        self.inbox.clear()
        self.emit("command:new", {})
        return {"command": "new", "status": "conversation reset"}

    def _cmd_prune(self, args: str) -> Dict[str, Any]:
        """Remove last N turn pairs from history via runtime."""
        try:
            n = int(args.strip()) if args.strip() else 1
        except ValueError:
            return {"error": "!prune requires a number: !prune 3"}

        ref = getattr(self, '_conductor_ref', None)
        if ref and hasattr(ref, 'prune_turns'):
            result = ref.prune_turns(n)
            self.emit("command:prune", {"n": n, "result": result})
            return {"command": "prune", **result}

        self.emit("command:prune", {"n": n})
        return {"command": "prune", "n": n, "status": "no runtime to prune"}

    def _cmd_heartbeat(self, args: str) -> Dict[str, Any]:
        """Edit HEARTBEAT.md — change standing orders via runtime."""
        ref = getattr(self, '_conductor_ref', None)
        if ref and hasattr(ref, 'edit_heartbeat'):
            result = ref.edit_heartbeat(args)
            self.emit("command:heartbeat", {"content": args, "result": result})
            return {"command": "heartbeat", **result}

        self.emit("command:heartbeat", {"content": args})
        return {"command": "heartbeat", "status": "no runtime for heartbeat edit", "content": args}

    # ==================== MESSAGE HANDLING ====================

    async def receive_user_prompt_message(self, message: UserPromptMessage):
        """Process user prompt through Agent.run().

        run() delegates to the DI'd runtime. ChatAgent adds:
        - Heartbeat response detection (HEARTBEAT_OK / HEARTBEAT_SUMMARY)
        - Response delivery back through main channel
        """
        result = await self.run(message)

        if result is not None:
            response_text = str(result)

            # Check for heartbeat response — handle turn deletion
            hb_result = self.check_heartbeat_response(response_text)
            if hb_result == "ok":
                self.emit("runtime:heartbeat_ok", {})
                yield CompletedMessage(
                    sender=self, receiver=message.sender, parent=message,
                    summary="HEARTBEAT_OK",
                )
                return

            # Deliver response back through main channel
            if self.central_channel and self.central_channel.main():
                self.central_channel.main().deliver({"message": response_text})

            self.emit("runtime:completed", {"content": message.content[:100], "response": response_text[:100]})
            yield CompletedMessage(
                sender=self, receiver=message.sender, parent=message,
                result=result, summary=response_text[:200],
            )
        else:
            self.emit("user_prompt:received", message)
            yield CompletedMessage(
                sender=self, receiver=message.sender, parent=message,
                summary=f"Received prompt from {message.ingress} (no runtime)",
            )

    async def handle_message(self, msg: InboxMessage) -> Optional[Message]:
        """Handle a message in conversational context.

        1. Intercept ! commands
        2. If busy, queue the message
        3. If idle, process immediately
        """
        # Intercept commands
        cmd_result = self.intercept_command(msg)
        if cmd_result is not None:
            yield_msg = CompletedMessage(
                sender=self,
                summary=str(cmd_result),
            )
            return yield_msg

        # Queue or process
        self.enqueue(msg)
        if not self._busy:
            return await self._drain_queue()
        return None

    async def _drain_queue(self) -> Optional[Message]:
        """Process all queued messages in order."""
        self._busy = True
        last_response = None
        try:
            while self.has_messages:
                last_response = await self.process_one()
        finally:
            self._busy = False
        return last_response

    # ==================== HEARTBEAT TURN DELETION ====================

    def check_heartbeat_response(self, response_text: str) -> Optional[str]:
        """Check if response is a heartbeat response and handle turn deletion.

        HEARTBEAT_OK: Agent has nothing to do. Delete the heartbeat turn
        from conversation history — zero context accumulation.

        HEARTBEAT_SUMMARY: Agent did work. Extract the summary, save to
        heartbeat_log.md, then delete work + summary turns.

        Returns:
            - None if not a heartbeat response
            - "ok" if HEARTBEAT_OK (turn should be deleted)
            - summary text if HEARTBEAT_SUMMARY found
        """
        import re
        text = response_text.strip()

        # Case 1: HEARTBEAT_OK — nothing to do, delete turn
        if "HEARTBEAT_OK" in text:
            self._log_heartbeat("HEARTBEAT_OK")
            self.emit("heartbeat:ok", {})
            return "ok"

        # Case 2: HEARTBEAT_SUMMARY — work was done, extract and save
        pattern = re.compile(r'```HEARTBEAT_SUMMARY\s*\n(.*?)\n```', re.DOTALL)
        match = pattern.search(text)
        if match:
            summary = match.group(1).strip()
            self._log_heartbeat("HEARTBEAT_SUMMARY", summary)
            self.emit("heartbeat:summary", {"summary": summary})
            return summary

        return None

    def _log_heartbeat(self, action: str, summary: str = "") -> None:
        """Append heartbeat event to heartbeat_log.md."""
        import json as _json
        # CONNECTS_TO: /tmp/heaven_data/heartbeat_log.md (write)
        log_path = Path("/tmp/heaven_data/heartbeat_log.md")
        log_path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().isoformat()
        entry = f"\n## {timestamp} — {action}\n"
        if summary:
            entry += f"\n{summary}\n"

        with open(log_path, "a") as f:
            f.write(entry)


class ClawAgent(Agent):
    """External agent. Own config/lifecycle.

    Channel wraps external agent's interface.
    Channel is a PIPE — we don't manage the other side.
    Pass-through: deliver sends, receive captures what came back.
    """

    config: AgentConfig = Field(default_factory=AgentConfig)

    async def handle_message(self, msg: InboxMessage) -> Optional[Message]:
        """Pass through to external agent via channel."""
        if self.central_channel and self.central_channel.main():
            self.central_channel.main().deliver({"message": msg.content})
        return None


class ServiceAgent(Agent):
    """Autonomous SDNAC agent. No conversation. Runs work, delivers output.

    There's an SDNAC programmed under here. It runs autonomously on
    schedule/trigger, processes work, delivers results to a channel.
    No user talks to it — it just runs and produces output.

    Use cases:
    - Autobiographer NIGHT mode (autonomous deepening, queue writing)
    - Observatory researcher (processes research queue)
    - Any autonomous SDNA pipeline

    Runtime DI: set_runtime() with an SDNAC or any async callable.
    The runtime is called with execute(context) or __call__(context).
    """

    config: AgentConfig = Field(default_factory=AgentConfig)
    _sdnac: Any = PrivateAttr(default=None)

    def set_sdnac(self, sdnac: Any) -> None:
        """Inject the SDNAC that this service runs."""
        self._sdnac = sdnac
        self.set_runtime(sdnac)

    @property
    def sdnac(self) -> Any:
        return self._sdnac

    async def execute(self, context: Optional[Dict[str, Any]] = None, on_message=None) -> Any:
        """Run the SDNAC with given context. Returns result.

        This is the main entry point — called by cron automations,
        heartbeat triggers, or manual fire.

        Args:
            context: Dict of context values for the SDNAC.
            on_message: Optional callback for each agent turn (e.g. Discord mirroring).
        """
        ctx = context or {}

        if self._sdnac is None:
            logger.warning("ServiceAgent '%s' has no SDNAC configured", self.config.name)
            return None

        self._processing = True
        self.emit("service:starting", {"agent": self.config.name, "context_keys": list(ctx.keys())})

        try:
            if hasattr(self._sdnac, 'execute'):
                result = await self._sdnac.execute(context=ctx, on_message=on_message)
            elif callable(self._sdnac):
                result = await self._sdnac(ctx) if asyncio.iscoroutinefunction(self._sdnac) else self._sdnac(ctx)
            else:
                result = None

            self.emit("service:completed", {"agent": self.config.name})

            # Deliver result to channel if configured
            if result and self.central_channel and self.central_channel.main():
                output = str(result)
                self.central_channel.main().deliver({"message": output})

            return result

        except Exception as e:
            logger.error("ServiceAgent '%s' execute failed: %s", self.config.name, e, exc_info=True)
            self.emit("service:error", {"agent": self.config.name, "error": str(e)})
            return None
        finally:
            self._processing = False


class RemoteAgent(Agent):
    """Network wrapper for agents in remote containers.

    RemoteAgent represents an agent that lives across a network boundary
    (Docker container, remote server). Communication happens via HTTP.
    The remote side has its own CAVEHTTPServer with /execute, /health, etc.

    RemoteAgent wraps whatever agent type lives on the other end —
    could be a CodeAgent (PAIA container), ServiceAgent, ChatAgent, etc.
    From CAVE's perspective, it's just an agent you send work to via HTTP.

    Use cases:
    - PAIA containers (CodeAgent + HTTP server + /exec endpoint)
    - Grug in repo-lord container
    - Future domain-specific containerized agents
    """

    config: AgentConfig = Field(default_factory=AgentConfig)
    _address: str = PrivateAttr(default="")
    _timeout: float = PrivateAttr(default=300.0)

    def __init__(self, config: Optional[AgentConfig] = None, address: str = "", timeout: float = 300.0, **kwargs):
        super().__init__(config=config, **kwargs)
        self._address = address
        self._timeout = timeout

    @property
    def address(self) -> str:
        return self._address

    @address.setter
    def address(self, value: str):
        self._address = value

    async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
        """Send task to remote agent via HTTP and return result."""
        if not self._address:
            return {"error": f"RemoteAgent '{self.config.name}' has no address configured"}

        try:
            import httpx
            timeout = kwargs.get("timeout", self._timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self._address}/execute",
                    json={"code": task, "timeout": int(timeout), **kwargs},
                )
                resp.raise_for_status()
                result = resp.json()

            self.emit("remote:completed", {"agent": self.config.name, "status": result.get("status")})
            return result

        except Exception as e:
            logger.error("RemoteAgent '%s' execute failed: %s", self.config.name, e)
            self.emit("remote:error", {"agent": self.config.name, "error": str(e)})
            return {"error": str(e)}

    async def health_check(self) -> bool:
        """Check if the remote agent is healthy."""
        if not self._address:
            return False
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._address}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def handle_message(self, msg: InboxMessage) -> Optional[Message]:
        """Forward inbox message to remote agent."""
        result = await self.execute(msg.content)
        if result and not result.get("error"):
            # Deliver result to channel if configured
            if self.central_channel and self.central_channel.main():
                output = result.get("response", result.get("output", str(result)))
                self.central_channel.main().deliver({"message": str(output)})
        return None


class CodeAgent(ChatAgent):
    """ChatAgent + tmux session management.

    Channel wraps tmux/terminal session.
    Channel exposure is GATED — kanban controls user access.
    """

    def _run_tmux(self, *args) -> subprocess.CompletedProcess:
        """Run a tmux command."""
        cmd = ["tmux"] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def session_exists(self) -> bool:
        """Check if our tmux session exists."""
        result = self._run_tmux("has-session", "-t", self.config.tmux_session)
        return result.returncode == 0

    def create_session(self) -> bool:
        """Create the tmux session for the agent."""
        if self.session_exists():
            return True
        result = self._run_tmux(
            "new-session", "-d", "-s", self.config.tmux_session,
            "-c", self.config.working_directory
        )
        return result.returncode == 0

    def kill_session(self) -> bool:
        """Kill the tmux session."""
        result = self._run_tmux("kill-session", "-t", self.config.tmux_session)
        return result.returncode == 0

    def spawn_agent(self) -> bool:
        """Spawn the agent inside tmux. Requires config.agent_command."""
        if not self.config.agent_command:
            raise RuntimeError("agent_command not configured")
        if not self.session_exists():
            if not self.create_session():
                return False
        result = self._run_tmux(
            "send-keys", "-t", self.config.tmux_session,
            self.config.agent_command, "Enter"
        )
        return result.returncode == 0

    def send_keys(self, *sequence) -> bool:
        """Send key sequence. Items can be str (keys) or float (sleep)."""
        for item in sequence:
            if isinstance(item, (int, float)):
                time.sleep(item)
            else:
                result = self._run_tmux("send-keys", "-t", self.config.tmux_session, item)
                if result.returncode != 0:
                    return False
        return True

    def capture_pane(self, history_limit: int = 5000) -> str:
        """Capture current pane content."""
        result = self._run_tmux(
            "capture-pane", "-t", self.config.tmux_session,
            "-p", "-S", f"-{history_limit}"
        )
        return result.stdout if result.returncode == 0 else ""

    def send_and_wait(self, prompt: str, timeout: Optional[float] = None) -> str:
        """Send prompt and wait for response (detected by response_marker)."""
        timeout = timeout or self.config.max_wait_seconds
        before = self.capture_pane()
        before_lines = len(before.splitlines())

        self.send_keys(prompt, "Enter")

        start_time = time.time()
        last_content = before
        stable_count = 0

        while time.time() - start_time < timeout:
            time.sleep(self.config.poll_interval)
            current = self.capture_pane()
            if current == last_content:
                stable_count += 1
                if stable_count >= 3 and self.config.response_marker and self.config.response_marker in current:
                    break
            else:
                stable_count = 0
                last_content = current

        after_lines = self.capture_pane().splitlines()
        response_lines = after_lines[before_lines:]
        cleaned = []
        for line in response_lines:
            if self.config.response_marker and line.strip().startswith(self.config.response_marker):
                break
            cleaned.append(line)
        return "\n".join(cleaned)

    # CAVE_REFACTOR Stage 3: inbox processing, message handlers, persistence,
    # and lifecycle all inherited from Agent base class. CodeAgent only adds tmux.


# =============================================================================
# INGRESS POINT HELPERS
# =============================================================================

def create_user_message(
    content: str,
    ingress: IngressType = IngressType.FRONTEND,
    source_id: Optional[str] = None,
    priority: int = 0
) -> UserPromptMessage:
    """Helper to create user prompt messages from any ingress."""
    return UserPromptMessage(
        content=content,
        ingress=ingress,
        source_id=source_id,
        priority=priority
    )


def create_system_event(
    event_type: str,
    event_data: Optional[Dict[str, Any]] = None,
    priority: int = 0
) -> SystemEventMessage:
    """Helper to create system event messages."""
    return SystemEventMessage(
        event_type=event_type,
        event_data=event_data or {},
        priority=priority
    )


# =============================================================================
# CLAUDE CODE AGENT
# =============================================================================

@dataclass
class ClaudeCodeAgentConfig(CodeAgentConfig):
    """Config for Claude Code agent - just sets Claude-specific defaults."""
    tmux_session: str = "claude"
    response_marker: str = "◇"  # Claude Code input prompt marker


class ClaudeCodeAgent(CodeAgent):
    """CodeAgent configured for Claude Code.
    
    This just sets Claude-specific defaults (response marker).
    The actual command comes from user settings.
    """
    config: ClaudeCodeAgentConfig = Field(default_factory=ClaudeCodeAgentConfig)

    def __init__(self, config: Optional[ClaudeCodeAgentConfig] = None, **kwargs):
        super().__init__(config=config or ClaudeCodeAgentConfig(), **kwargs)
