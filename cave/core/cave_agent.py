"""CAVEAgent - The God Object (State Only).

Unified CAVE runtime state. HTTP routes are in server/http_server.py.

# =============================================================================
# CAVE_REFACTOR: CAVEAgent CHANGES (Stage 5 + Stage 6)
# =============================================================================
#
# CURRENT: CAVEAgent is a mixin onion that owns a single ClaudeCodeAgent
#          and manages state directly. http_server.py creates it with
#          inverted ownership (global cave = CAVEAgent(...) at startup).
#          Config only knows about ONE agent (main_agent_config: singular).
#
# TARGET (Stage 5): CAVEAgent becomes a generic agent registry.
#   config.agents: List[AgentConfig]  — not just main_agent_config
#   CAVEAgent.__init__ reads config, creates right agent type for each:
#     - ChatAgent for Conductor, Autobiographer
#     - CodeAgent for Inner GNOSYS
#     - ClawAgent for OpenClaw
#   Generic registry: register(agent), get(name), list(), route(message)
#
# TARGET (Stage 6): CAVEHTTPServer becomes a facade.
#   CAVEHTTPServer(port, cave_agent) — takes agent IN, not created internally
#   Every route calls ONE method on cave_agent. No logic in routes.
#   No global cave variable.
#   start_sancrev.py becomes ~5 lines:
#     wd = WakingDreamer()
#     cave = CAVEHTTPServer(8080, wd)
#     uvicorn.run(cave.app)
#
# TARGET: WakingDreamer(CAVEAgent) — the SANCREV impl.
#   Singleton god object. Loads config from file. Hot-reloads changes.
#   IS svabhavikakaya (the unity of all kayas).
#   Agents edit config → WakingDreamer hot-reloads → behavior changes.
#
# CAVEAgent.CentralChannel = the COMPLETE MAP of all agents + all their
#   conversation types. It IS the routing table for the entire system.
#
#   self.central_channel = {
#     "conductor":      CentralChannel(main=discord_user_chat, heartbeat=heartbeat_convo),
#     "autobiographer": CentralChannel(chat=memory_chat, journal=journal_convo, night=night_convo),
#     "gnosys":         CentralChannel(main=tmux_session),
#     "openclaw":       CentralChannel(main=discord_pipe),
#   }
#
#   Nadis = external inputs that flow INTO agent CentralChannels:
#     Discord #conductor-whisper  →  conductor.main
#     Discord heartbeat timer     →  conductor.heartbeat
#     Discord #journal            →  autobiographer.journal
#     Cron 6AM/10PM               →  autobiographer.journal
#     tmux session                →  gnosys.main
#     Discord #openclaw           →  openclaw.main
#     Webhook /webhook/{name}     →  wherever automation routes
#
# MIXIN ONION: Stays as-is (marked "don't touch" in CAVE_REFACTOR_ANALYSIS).
#   What MOVES OUT: runtime logic that is NOT invariant (how many agents,
#   what any config is). CAVEAgent takes configs. Any IMPL gives configs.
#
# =============================================================================
"""
import subprocess
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

from .config import CAVEConfig
from .models import PAIAState, AgentRegistration, RemoteAgentHandle, CaveAgentEntry
from .agent import Agent, ChatAgent, CodeAgent, ClawAgent, ServiceAgent, RemoteAgent, AgentConfig, CodeAgentConfig, ClaudeCodeAgent, ClaudeCodeAgentConfig
from .channel import CentralChannel
from .state_reader import ClaudeStateReader
from .dna import AutoModeDNA
from .mixins import (
    PAIAStateMixin,
    AgentRegistryMixin,
    MessageRouterMixin,
    HookRouterMixin,
    LoopManagerMixin,
    RemoteAgentMixin,
    SSEMixin,
    OmnisancMixin,
    AnatomyMixin,
    AutomationMixin,
    TUIMixin,
)
from .config_snapshots import MainAgentConfigManager
from .world import World, RNGEventSource
from .sanctum_automations import sync_ritual_automations


class CAVEAgent(
    PAIAStateMixin,
    AgentRegistryMixin,
    MessageRouterMixin,
    HookRouterMixin,
    LoopManagerMixin,
    RemoteAgentMixin,
    SSEMixin,
    OmnisancMixin,
    AnatomyMixin,
    AutomationMixin,
    TUIMixin,
):
    """Unified CAVE runtime state. Routes are in http_server.py."""

    def __init__(self, config: CAVEConfig | None = None):
        self.config = config or CAVEConfig()

        # === STATE ===
        self.paia_states: Dict[str, PAIAState] = {}
        self.agent_registry: Dict[str, AgentRegistration] = {}
        self.remote_agents: Dict[str, RemoteAgentHandle] = {}

        # === SSE (must be before cave_agents — auto-SSE needs event_queue) ===
        self._init_sse()

        # === CAVE AGENT REGISTRY (Stage 5) ===
        # Generic registry: N agents of any type, created from config.
        # CentralChannel map = routing table for the entire system.
        self.cave_agents: Dict[str, Agent] = {}
        self.central_channels: Dict[str, CentralChannel] = {}
        self._init_cave_agents()

        # === LIVE MIRROR (legacy — main_agent kept for backwards compat) ===
        self.main_agent: Optional[ClaudeCodeAgent] = None
        self.state_reader = ClaudeStateReader(
            project_dir=self.config.main_agent_config.working_dir
        )
        self._attach_to_session()

        # === ROUTING ===
        self._init_hook_router()
        self._init_loop_manager()

        # === OMNISANC ===
        self._init_omnisanc()

        # === ANATOMY (Heart, Blood, Ears, Organs) ===
        self._init_anatomy()

        # === AGENT HEARTBEATS ===
        # Heartbeats are wired by the IMPL (WakingDreamer), not by config.
        # The heartbeat system uses HEARTBEAT.md files — not inline prompts.

        # === WORLD (environment — event sources tick into Ears) ===
        self.world = World()
        self._register_event_sources()

        # === PERCEPTION (Body perceives world through Ears) ===
        self._wire_perception_loop()

        # === HEARTBEAT ===
        # Conductor heartbeat is now a CronAutomation at
        # /tmp/heaven_data/automations/conductor_heartbeat.json
        # Fired by cron_scheduler tick. No more Tick or _wire methods needed.
        # CodeAgents use OMNISANC, not heartbeat.

        # === HEALTH CHECKS (body.checkup — organ state, ticked by Heart) ===
        self._wire_checkup()

        # === START HEART (runs tick loop thread for heartbeat + checkup) ===
        self.start_heart()

        # === AUTOMATIONS ===
        self._init_automations()

        # === CRON SCHEDULER — fire due automations every 60s ===
        from .mixins.anatomy import Tick
        self.heart.add_tick(Tick(
            name="cron_scheduler",
            callback=self.fire_due_automations,
            every=60.0,
        ))

        # === SANCTUM CATCH-UP — fires 30s after startup, then every 5 min ===
        from .sanctum_automations import catch_up_missed_rituals
        import time as _time
        def _sanctum_catchup_tick():
            catch_up_missed_rituals()
        self.heart.add_tick(Tick(
            name="sanctum_catchup",
            callback=_sanctum_catchup_tick,
            every=300.0,
        ))
        self.heart.ticks["sanctum_catchup"]._last_run = _time.time() - 270.0

        # === MINI CLIs — system-level Discord channels with commands ===
        self.mini_clis = {}
        try:
            from .sanctum_cli import create_sanctum_cli
            sanctum_cli = create_sanctum_cli()
            if sanctum_cli:
                self.mini_clis["sanctum"] = sanctum_cli
        except Exception as e:
            logger.warning("Failed to create sanctum MiniCLI: %s", e)

        # Poll MiniCLIs on a tick (same rate as perception)
        if self.mini_clis:
            def _poll_mini_clis():
                for name, cli in self.mini_clis.items():
                    try:
                        results = cli.poll()
                        for r in results:
                            logger.info("MiniCLI %s: %s", name, r)
                    except Exception as e:
                        logger.error("MiniCLI %s poll failed: %s", name, e)

            self.heart.add_tick(Tick(
                name="mini_cli_poll",
                callback=_poll_mini_clis,
                every=30.0,
            ))

        # === AUTOMATION HOT-RELOAD — check for new/changed/deleted JSONs every 5 min ===
        def _hot_reload_tick():
            if hasattr(self, 'automation_registry'):
                self.automation_registry.hot_reload()
        self.heart.add_tick(Tick(
            name="automation_hot_reload",
            callback=_hot_reload_tick,
            every=300.0,
        ))

        # === DNA (Auto Mode) ===
        self.dna: Optional[AutoModeDNA] = None

        # === System Prompt Templating ===
        if self.config.system_prompt_template_path and self.config.system_prompt_target_path:
            self._render_system_prompt()

        # === Data directories ===
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.hook_dir.mkdir(parents=True, exist_ok=True)

        # === Main Agent Config Archives ===
        self.config_manager = MainAgentConfigManager(
            data_dir=self.config.data_dir,
            claude_home=self.config.claude_home
        )

    def _register_event_sources(self) -> None:
        """Register default event sources with World.

        Discord polling is now handled by UserDiscordChannel.receive()
        through the Channel system — NOT through a World EventSource.
        Ears.perceive_world() polls CentralChannel.receive_all() for
        channel-based events (Discord, tmux, file inbox).

        World is reserved for non-channel sources only:
        - RNG/probabilistic events (disabled for now)
        - Sanctum ritual reminders (scheduled, no channel home)
        """
        # Probabilistic: RNG world events — DISABLED (no RNG hooked up yet)
        # self.world.add_source(RNGEventSource.default_world_events())

        # Discord: NOW HANDLED BY CHANNEL SYSTEM — not World
        # UserDiscordChannel.receive() polls Discord REST API
        # Ears.perceive_world() polls CentralChannel.receive_all()

        # SANCTUM rituals: sync to CronAutomations (replaces SanctumRitualSource)
        sync_ritual_automations()

    @property
    def is_paia(self) -> bool:
        return self.config.parent_url is not None

    @property
    def paia_id(self) -> str:
        return self.config.paia_id or f"paia-{self.config.port}"

    def _render_system_prompt(self) -> None:
        if not self.config.system_prompt_template_path or not self.config.system_prompt_target_path:
            return
        template = self.config.system_prompt_template_path.read_text()
        rendered = template
        for key, value in self.config.template_vars.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        self.config.system_prompt_target_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.system_prompt_target_path.write_text(rendered)

    def _attach_to_session(self) -> bool:
        session = self.config.main_agent_config.tmux_session
        result = subprocess.run(["tmux", "has-session", "-t", session], capture_output=True)
        if result.returncode == 0:
            agent_config = ClaudeCodeAgentConfig(
                agent_command=self.config.main_agent_config.command,
                tmux_session=session,
                working_directory=str(self.config.main_agent_config.working_dir),
            )
            self.main_agent = ClaudeCodeAgent(config=agent_config)
            self._emit_event("attached", {"session": session})
            return True
        else:
            self.main_agent = None
            self._emit_event("no_session", {"session": session})
            return False

    # === CAVE AGENT REGISTRY (Stage 5) ===

    def _init_cave_agents(self):
        """Create agents from config.agents list.

        Each CaveAgentEntry → right Agent subtype + CentralChannel.
        If config.agents is empty, no agents are created here
        (falls back to legacy main_agent path).

        After creation:
        - Event forwarding: Agent.emit() → CAVEAgent SSE + broadcast channels
        - Heartbeat: Heart tick added if entry.heartbeat.enabled
        """
        for entry in self.config.agents:
            agent = self._create_agent_from_entry(entry)
            if agent:
                self.cave_agents[entry.name] = agent
                self.central_channels[entry.name] = agent.central_channel or CentralChannel()

                # Wire event forwarding: agent events → SSE + broadcast channels
                self._wire_event_forwarding(entry.name, agent)

                logger.info(f"CAVE agent registered: {entry.name} ({entry.agent_type})")


    def _wire_event_forwarding(self, agent_name: str, agent: Agent):
        """Wire Agent.emit() to flow through CAVEAgent's unified event stream.

        Every agent event:
        1. Fires the original llegos Actor emit (local listeners)
        2. Forwards to CAVEAgent._emit_event() → SSE queue (frontend)
        3. Forwards to agent's broadcast channels (Discord mirrors etc)
        """
        original_emit = agent.emit
        cave_ref = self

        def forwarding_emit(event_name, data=None):
            # Original llegos emit
            original_emit(event_name, data)

            # Forward to unified SSE stream (tagged with agent name)
            cave_ref._emit_event(f"{agent_name}:{event_name}", {
                "agent": agent_name,
                "event": event_name,
                "data": data,
            })

            # Forward to broadcast channels (not SSE — that's already handled above)
            if agent.central_channel:
                for conv_name, ch in agent.central_channel.conversations.items():
                    if conv_name == "sse":
                        continue  # SSE already gets it via _emit_event
                    if hasattr(ch, 'is_broadcast') and ch.is_broadcast:
                        try:
                            ch.deliver({"message": f"[{agent_name}:{event_name}] {data}"})
                        except Exception as e:
                            logger.debug("Broadcast to %s.%s failed: %s", agent_name, conv_name, e)

        agent.emit = forwarding_emit


    def _create_agent_from_entry(self, entry: CaveAgentEntry) -> Optional[Agent]:
        """Factory: CaveAgentEntry → correct Agent subtype.

        After creating the agent:
        1. Builds CentralChannel from config
        2. Applies channel_mode preset (complete_mirror/notify/mixed)
        3. Auto-adds SSE channel (every agent gets SSE for frontend)
        """
        if entry.agent_type == "code":
            agent = CodeAgent(config=CodeAgentConfig(
                name=entry.name,
                agent_command=entry.command,
                tmux_session=entry.tmux_session,
                working_directory=entry.working_dir,
            ))
        elif entry.agent_type == "chat":
            agent = ChatAgent(config=AgentConfig(
                name=entry.name,
                working_directory=entry.working_dir,
            ))
        elif entry.agent_type == "claw":
            agent = ClawAgent(config=AgentConfig(
                name=entry.name,
                working_directory=entry.working_dir,
            ))
        elif entry.agent_type == "service":
            agent = ServiceAgent(config=AgentConfig(
                name=entry.name,
                working_directory=entry.working_dir,
            ))
        elif entry.agent_type == "remote":
            agent = RemoteAgent(config=AgentConfig(
                name=entry.name,
                working_directory=entry.working_dir,
            ))
        else:
            logger.error(f"Unknown agent type: {entry.agent_type} for {entry.name}")
            return None

        # Wire CentralChannel from entry.channels config
        conversations = {}
        for conv_name, conv_config in entry.channels.items():
            channel = self._create_channel_from_config(conv_config)
            if channel:
                conversations[conv_name] = channel

        # Apply channel_mode preset
        if entry.channel_mode == "complete_mirror":
            for ch in conversations.values():
                ch.set_modes(["mirror", "broadcast"])
        elif entry.channel_mode == "notify":
            for ch in conversations.values():
                ch.set_modes(["broadcast"])
        # "mixed" = per-channel modes already set by _create_channel_from_config

        # Auto-SSE: every agent gets an SSE channel (broadcast-only, for frontend)
        from .channel import SSEChannel
        if hasattr(self, 'event_queue'):
            sse_ch = SSEChannel(queue=self.event_queue)
            sse_ch.set_modes(["broadcast"])
            conversations["sse"] = sse_ch

        agent.central_channel = CentralChannel(conversations=conversations)

        return agent

    def _create_channel_from_config(self, config: Dict[str, Any]):
        """Factory: channel config dict → Channel instance.

        Config format: {"type": "discord", "channel_id": "123", "modes": ["mirror", "broadcast"]}
                       {"type": "tmux", "session": "lord"}
                       {"type": "inbox", "inbox_dir": "/tmp/..."}
                       {"type": "internal"}  — no external transport
                       {"type": "sse"}  — SSE channel (auto-added, but can be explicit)

        Per-channel modes (used when agent channel_mode="mixed"):
            "modes": ["mirror", "broadcast", "deliverable"]
        """
        from .channel import (
            UserDiscordChannel, AgentInboxChannel, AgentTmuxChannel, SSEChannel
        )

        ch_type = config.get("type", "internal")
        channel = None

        if ch_type == "discord":
            channel = UserDiscordChannel(
                channel_id=config.get("channel_id", ""),
                guild_id=config.get("guild_id", ""),
                token=config.get("token", ""),
            )
        elif ch_type == "tmux":
            channel = AgentTmuxChannel(
                session=config.get("session", "claude"),
            )
        elif ch_type == "inbox":
            from pathlib import Path
            channel = AgentInboxChannel(
                inbox_dir=Path(config.get("inbox_dir", "/tmp/heaven_data/inbox")),
            )
        elif ch_type == "internal":
            from pathlib import Path
            agent_name = config.get("agent_name", "unknown")
            channel = AgentInboxChannel(
                inbox_dir=Path(f"/tmp/heaven_data/inboxes/{agent_name}"),
            )
        elif ch_type == "sse":
            if hasattr(self, 'event_queue'):
                channel = SSEChannel(queue=self.event_queue)
            else:
                logger.warning("SSE channel requested but no event_queue available")
                return None
        else:
            logger.warning(f"Unknown channel type: {ch_type}")
            return None

        # Apply per-channel modes if specified (for mixed mode)
        if channel and "modes" in config:
            channel.set_modes(config["modes"])

        return channel

    async def start_agent_poll_loops(self):
        """Start run_poll_loop for every registered agent.

        Called from server startup AFTER all runtimes are wired.
        Each agent's run_poll_loop() calls check_inbox() on interval.
        """
        import asyncio
        for name, agent in self.cave_agents.items():
            asyncio.create_task(agent.run_poll_loop())
            logger.info("Started poll loop for agent: %s", name)

    def get_cave_agent(self, name: str) -> Optional[Agent]:
        """Get a registered CAVE agent by name."""
        return self.cave_agents.get(name)

    def list_cave_agents(self) -> Dict[str, str]:
        """List all registered CAVE agents: {name: type}."""
        return {name: agent.__class__.__name__ for name, agent in self.cave_agents.items()}

    def route_to_agent(self, agent_name: str, message) -> bool:
        """Route a message to a specific agent's inbox."""
        agent = self.cave_agents.get(agent_name)
        if not agent:
            logger.warning(f"No CAVE agent named '{agent_name}'")
            return False
        return agent.enqueue(message)

    # === PHASE 5: INTEGRATION WIRING ===

    def get_agent_status(self) -> Dict[str, Any]:
        """Get status of all CAVE agents for agent awareness.

        Written to agent_status.txt by heartbeat.
        Conductor reads this every turn to know what each agent is doing.
        """
        status = {}
        for name, agent in self.cave_agents.items():
            status[name] = {
                "type": agent.__class__.__name__,
                "inbox_count": agent.inbox_count,
                "has_messages": agent.has_messages,
                "channels": agent.central_channel.list_conversations() if agent.central_channel else [],
            }
        return status

    def write_agent_status_file(self):
        """Write agent_status.txt — called by heartbeat.

        Conductor reads this dynamic file every turn for agent awareness.
        """
        import json
        status = self.get_agent_status()
        status_file = self.config.data_dir / "conductor_dynamic" / "agent_status.txt"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        lines = ["=== Agent Status ===", ""]
        for name, info in status.items():
            lines.append(f"{name} ({info['type']}): inbox={info['inbox_count']}, channels={info['channels']}")
        lines.append("")
        lines.append(f"Updated: {datetime.utcnow().isoformat()}")
        status_file.write_text("\n".join(lines))

    def fire_due_automations(self):
        """Fire all CronAutomations that are due. Called by Heart tick.

        Completion handler:
        1. Poll running processes — check if async subprocesses finished
        2. Capture result from auto.fire()
        3. Check expected_deliverables
        4. SUCCESS + deliverables present → trigger dependent automations
        5. ERROR/BLOCKED → write block report
        6. One-shot → auto-unregister after firing
        7. Parallel → fire parallel automations simultaneously
        """
        import os
        from pathlib import Path
        from datetime import datetime

        registry = getattr(self, 'automation_registry', None)
        if not registry:
            return

        if not hasattr(self, '_automation_results'):
            self._automation_results = {}
        if not hasattr(self, '_running_processes'):
            self._running_processes = {}  # name → {pid, automation_name, started_at}

        # --- Phase 1: Poll running processes ---
        completed_pids = []
        for name, proc_info in list(self._running_processes.items()):
            pid = proc_info["pid"]
            original_start = proc_info.get("start_time_ticks", 0)
            try:
                os.kill(pid, 0)  # check alive
                # PID exists — but is it OUR process or a reused PID?
                if original_start:
                    current_start = self._get_pid_start_time(pid)
                    if current_start and current_start != original_start:
                        # PID reused — our process is gone
                        logger.warning("PID %d reused (start %d != %d), treating %s as dead",
                                      pid, current_start, original_start, name)
                    else:
                        continue  # same process, still running
                else:
                    continue  # no start_time recorded, assume still running
            except ProcessLookupError:
                pass  # finished
            except PermissionError:
                continue  # still running, different user

            # Process finished — reap zombie
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass  # already reaped

            # Check deliverables
            auto = registry.get(name)
            deliverables_ok = True
            missing = []
            if auto and auto.schema.expected_deliverables:
                missing = [p for p in auto.schema.expected_deliverables if not Path(p).exists()]
                deliverables_ok = not missing

            status = "success" if deliverables_ok else "deliverables_missing"
            self._automation_results[name] = {
                "status": status,
                "result": {"pid": pid, "missing_deliverables": missing},
                "timestamp": datetime.now().isoformat(),
            }

            if not deliverables_ok:
                self._write_automation_failure(name, {
                    "status": "deliverables_missing",
                    "pid": pid,
                    "missing": missing,
                })
            else:
                logger.info("Process %d for %s completed, deliverables OK", pid, name)

            # One-shot cleanup for async processes
            if auto and auto.schema.one_shot:
                registry.unregister(name)
                schema_path = registry._dir / f"{name}.json"
                if schema_path.exists():
                    schema_path.unlink()
                logger.info("One-shot async automation %s removed after process completion", name)

            completed_pids.append(name)

        for name in completed_pids:
            del self._running_processes[name]

        # --- Phase 2: Fire due automations ---
        to_unregister = []

        for auto in registry.get_due():
            # Check depends_on — skip if any dependency hasn't succeeded
            deps = auto.schema.depends_on
            if deps:
                deps_met = all(
                    self._automation_results.get(d, {}).get("status") == "success"
                    for d in deps
                )
                if not deps_met:
                    logger.info("Automation %s skipped: dependencies not met (%s)", auto.name, deps)
                    continue

            # Fire
            try:
                result = auto.fire()
                status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
                logger.info("Fired automation: %s → %s", auto.name, status)
            except Exception as e:
                result = {"status": "error", "error": str(e)}
                status = "error"
                logger.error("Automation %s failed: %s", auto.name, e)

            # If result contains a PID, track it — process is async, skip deliverable check
            result_pid = result.get("pid") if isinstance(result, dict) else None
            if result_pid:
                import uuid
                self._running_processes[auto.name] = {
                    "pid": result_pid,
                    "started_at": datetime.now().isoformat(),
                    "start_time_ticks": self._get_pid_start_time(result_pid),
                    "run_id": str(uuid.uuid4())[:8],
                }
                logger.info("Tracking async process %d (run=%s) for %s",
                           result_pid, self._running_processes[auto.name]["run_id"], auto.name)
                # Don't check deliverables yet — process still running
                self._automation_results[auto.name] = {
                    "status": "running",
                    "result": result,
                    "timestamp": datetime.now().isoformat(),
                }
                continue  # skip to next automation

            # Sync result — check expected_deliverables immediately
            deliverables_ok = True
            if auto.schema.expected_deliverables:
                missing = [p for p in auto.schema.expected_deliverables if not Path(p).exists()]
                if missing:
                    deliverables_ok = False
                    result["missing_deliverables"] = missing
                    status = "deliverables_missing"
                    logger.warning("Automation %s: missing deliverables %s", auto.name, missing)

            # Determine final status
            final_status = "success" if status in ("success", "unknown") and deliverables_ok else "failed"

            # Store result for dependency tracking
            self._automation_results[auto.name] = {
                "status": final_status,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }

            # On success — resolve any previous blockages for this automation
            if final_status == "success":
                from cave.core.blockage_store import BlockageStore
                BlockageStore().mark_resolved(auto.name)

            # On failure — check for SDNA block report in agent history, store blockage
            if status in ("error", "blocked", "deliverables_missing"):
                self._write_automation_failure(auto.name, result)
                from cave.core.blockage_store import BlockageStore
                store = BlockageStore()
                # Try to read block report from agent history
                agent_name = result.get("agent_name", auto.name)
                br = store.read_block_report_from_history(agent_name)
                block_data = br["block_report"] if br else result
                store.add(auto.name, block_data)

            # One-shot cleanup
            if auto.schema.one_shot:
                to_unregister.append(auto.name)

            # Parallel — fire listed automations now
            for par_name in auto.schema.parallel:
                par_auto = registry.get(par_name)
                if par_auto:
                    try:
                        par_result = par_auto.fire()
                        logger.info("Parallel fired: %s → %s", par_name, par_result.get("status", "?"))
                        self._automation_results[par_name] = {
                            "status": "success",
                            "result": par_result,
                            "timestamp": __import__("datetime").datetime.now().isoformat(),
                        }
                    except Exception as e:
                        logger.error("Parallel automation %s failed: %s", par_name, e)
                        self._write_automation_failure(par_name, {"status": "error", "error": str(e)})

        # Clean up one-shots
        for name in to_unregister:
            registry.unregister(name)
            schema_path = registry._dir / f"{name}.json"
            if schema_path.exists():
                schema_path.unlink()
            logger.info("One-shot automation %s removed after firing", name)

    @staticmethod
    def _get_pid_start_time(pid: int) -> int:
        """Get process start time in clock ticks from /proc. Returns 0 if unavailable."""
        try:
            from pathlib import Path as _P
            stat = _P(f"/proc/{pid}/stat").read_text()
            # Field 22 (0-indexed: 21) is starttime in clock ticks
            return int(stat.split(")")[1].split()[19])
        except (FileNotFoundError, IndexError, ValueError, PermissionError):
            return 0

    def _write_automation_failure(self, name: str, result: dict):
        """Write a block report for a failed automation."""
        import json
        from pathlib import Path
        from datetime import datetime
        failures_dir = Path(self.config.data_dir) / "automation_failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report = {
            "automation": name,
            "timestamp": datetime.now().isoformat(),
            "result": result,
        }
        (failures_dir / f"{name}_{ts}.json").write_text(json.dumps(report, indent=2, default=str))
        logger.warning("Block report written for automation %s", name)

    def assemble_morning_briefing(self) -> str:
        """Assemble morning briefing from dynamic files.

        Conductor calls this after journal completes.
        Reads: sanctum_status.txt, social_queue.txt, agent_status.txt, tasks.
        """
        briefing_parts = []
        dynamic_dir = self.config.data_dir / "conductor_dynamic"

        for filename in ["sanctum_status.txt", "social_queue.txt", "agent_status.txt"]:
            filepath = dynamic_dir / filename
            if filepath.exists():
                briefing_parts.append(f"--- {filename} ---")
                briefing_parts.append(filepath.read_text().strip())
                briefing_parts.append("")

        return "\n".join(briefing_parts) if briefing_parts else "No status files available."

    def _ensure_attached(self) -> bool:
        if self.main_agent and self.main_agent.session_exists():
            return True
        return self._attach_to_session()

    def inspect(self) -> Dict[str, Any]:
        return {
            "paias": {k: v.model_dump() for k, v in self.paia_states.items()},
            "agents": {k: v.model_dump() for k, v in self.agent_registry.items()},
            "remote_agents": {k: v.model_dump() for k, v in self.remote_agents.items()},
            "messages": self.message_router_summary(),
            "hooks": self.get_hook_status(),
            "sse": self.sse_status(),
            "config": {
                "host": self.config.host,
                "port": self.config.port,
                "data_dir": str(self.config.data_dir),
                "hook_dir": str(self.config.hook_dir),
                "sdna_enabled": self.config.sdna_enabled,
            }
        }

    def _build_heartbeat_state(self) -> Dict[str, Any]:
        context_pct = 0
        if self.main_agent and self.main_agent.session_exists():
            output = self.main_agent.capture_pane(history_limit=50)
            context_pct = ClaudeStateReader.parse_context_pct(output) or 0
        return {
            "paia_id": self.paia_id,
            "status": "working" if self.main_agent else "idle",
            "context_pct": context_pct,
            "inbox_count": 0,
            "current_task": None,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "endpoint": f"http://{self.config.host}:{self.config.port}",
            "metadata": {"session": self.config.main_agent_config.tmux_session, "attached": self.main_agent is not None}
        }

    async def send_heartbeat(self) -> bool:
        """Send single heartbeat to parent. Called by http_server startup loop."""
        if not self.config.parent_url:
            return False
        try:
            state = self._build_heartbeat_state()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{self.config.parent_url}/paias/{self.paia_id}", json=state)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            return False

    # === Main Agent Config Management ===

    def archive_config(self, name: str) -> Dict[str, Any]:
        """Archive current main agent config files."""
        result = self.config_manager.archive(name)
        if "error" not in result:
            self._emit_event("config_archived", {"name": name})
        return result

    def inject_config(self, name: str) -> Dict[str, Any]:
        """Inject (restore) a named config archive. Auto-backs up current first."""
        result = self.config_manager.inject(name)
        if "error" not in result:
            self._emit_event("config_injected", {"name": name, "backup": result.get("backup")})
        return result

    def list_config_archives(self) -> Dict[str, Any]:
        """List all config archives."""
        return self.config_manager.list_archives()

    def get_active_config(self) -> Dict[str, Any]:
        """Get info about currently active config."""
        return self.config_manager.get_active_info()

    def delete_config_archive(self, name: str) -> Dict[str, Any]:
        """Delete a config archive."""
        return self.config_manager.delete_archive(name)

    def export_config_archive(self, name: str, dest_path: str) -> Dict[str, Any]:
        """Export an archive to external path."""
        return self.config_manager.export_archive(name, dest_path)

    def import_config_archive(self, source_path: str, name: str) -> Dict[str, Any]:
        """Import an archive from external path."""
        return self.config_manager.import_archive(source_path, name)

    # === DNA (Auto Mode) ===

    def start_auto_mode(self, dna: AutoModeDNA) -> Dict[str, Any]:
        """Start auto mode with given DNA."""
        self.dna = dna
        return self.dna.start(self)

    def stop_auto_mode(self) -> Dict[str, Any]:
        """Stop auto mode."""
        if not self.dna:
            return {"error": "No DNA active"}
        result = self.dna.stop(self)
        self.dna = None
        return result

    def check_dna_transition(self) -> Dict[str, Any]:
        """Check if DNA should transition to next loop. Call on each hook pass."""
        if not self.dna or not self.dna.active:
            return {"status": "no_dna"}
        return self.dna.check_and_transition(self)

    def get_dna_status(self) -> Dict[str, Any]:
        """Get current DNA status."""
        if not self.dna:
            return {"status": "no_dna"}
        return self.dna.get_status()

    # === OMNISANC Workflow (hardcoded, hack to customize) ===

    def run_omnisanc(self) -> Dict[str, Any]:
        """Run OMNISANC zone detection and activate appropriate hooks.

        This is the hardcoded OMNISANC workflow. Fork and hack if you want
        different behavior. No abstraction - just Python.

        Returns:
            Status dict with zone and active hooks
        """
        # Always-on stop hooks (fire every zone, even when omnisanc disabled)
        always_on_stop = [
            "dragonbones",
            "inbox_injection",
            "obs_recording",
            "gnosys_discord_notify",
        ]

        if not self.is_omnisanc_enabled():
            self.config.main_agent_config.active_hooks = {
                "stop": always_on_stop,
                "pretooluse": [],
                "posttooluse": ["inbox_notification"],
            }
            return {"status": "disabled", "active_hooks": always_on_stop}

        state = self.get_omnisanc_state()
        mode = self.get_paia_mode()  # DAY or NIGHT
        auto = self.get_auto_mode()  # AUTO or MANUAL
        is_auto = auto == "AUTO"
        is_night = mode == "NIGHT"

        # Start with empty active hooks
        active = []

        # Zone logic - mutually exclusive
        zone = "HOME"
        if not state.get("course_plotted"):
            zone = "HOME"
            # HOME hooks only fire in AUTO mode
            if is_auto:
                if is_night:
                    # NIGHT + AUTO = maintenance mode
                    active.append("metabrainhook")
                    active.append("omnisanc_home_night")
                else:
                    # DAY + AUTO = work mode (canopy tasks)
                    active.append("omnisanc_home_day")
            # MANUAL = user driving, no HOME hooks
        elif state.get("needs_review"):
            zone = "LANDING"
            active.append("omnisanc_landing")
        elif state.get("flight_selected") or state.get("session_active"):
            zone = "SESSION"
            active.append("omnisanc_session")
        elif state.get("fly_called"):
            zone = "LAUNCH"
            active.append("omnisanc_launch")
        else:
            zone = "STARPORT"
            active.append("omnisanc_starport")

        # Set active hooks for all hook types
        # inbox_notification always fires on posttooluse (perception layer)
        self.config.main_agent_config.active_hooks = {
            "stop": active + always_on_stop,
            "pretooluse": ["omnisanc_router_pretooluse"],
            "posttooluse": ["omnisanc_router_posttooluse", "inbox_notification"],
        }

        logger.info(f"OMNISANC: zone={zone}, mode={mode}, auto={auto}, hooks={active}")

        return {
            "status": "active",
            "zone": zone,
            "mode": mode,
            "auto": auto,
            "active_hooks": active,
            "state": state,
        }

    def get_paia_mode(self) -> str:
        """Get current PAIA mode: DAY or NIGHT.

        TODO: Implement proper mode detection (user presence, time, etc.)
        For now, reads from file or defaults to DAY.
        """
        from pathlib import Path
        # CONNECTS_TO: /tmp/heaven_data/paia_mode.txt (read) — also accessed by set_paia_mode(), OMNISANC
        mode_file = Path("/tmp/heaven_data/paia_mode.txt")
        try:
            if mode_file.exists():
                return mode_file.read_text().strip().upper()
        except Exception:
            pass
        return "DAY"

    def get_auto_mode(self) -> str:
        """Get current auto mode: AUTO or MANUAL.

        AUTO = agent works autonomously (pulls tasks, does maintenance)
        MANUAL = user is driving, agent responds to user
        """
        from pathlib import Path
        # CONNECTS_TO: /tmp/heaven_data/paia_auto.txt (read) — also accessed by set_auto_mode(), OMNISANC
        auto_file = Path("/tmp/heaven_data/paia_auto.txt")
        try:
            if auto_file.exists():
                return auto_file.read_text().strip().upper()
        except Exception:
            pass
        return "MANUAL"  # Default to MANUAL (user driving)

    def set_auto_mode(self, mode: str) -> Dict[str, Any]:
        """Set auto mode: AUTO or MANUAL."""
        from pathlib import Path
        # CONNECTS_TO: /tmp/heaven_data/paia_auto.txt (write) — also accessed by get_auto_mode(), OMNISANC
        auto_file = Path("/tmp/heaven_data/paia_auto.txt")
        mode = mode.upper()
        if mode not in ("AUTO", "MANUAL"):
            return {"success": False, "error": f"Invalid mode: {mode}"}
        auto_file.parent.mkdir(parents=True, exist_ok=True)
        auto_file.write_text(mode)
        return {"success": True, "mode": mode}

    def set_paia_mode(self, mode: str) -> Dict[str, Any]:
        """Set PAIA mode: DAY or NIGHT."""
        from pathlib import Path
        # CONNECTS_TO: /tmp/heaven_data/paia_mode.txt (write) — also accessed by get_paia_mode(), OMNISANC
        mode_file = Path("/tmp/heaven_data/paia_mode.txt")
        mode = mode.upper()
        if mode not in ("DAY", "NIGHT"):
            return {"success": False, "error": f"Invalid mode: {mode}"}
        mode_file.parent.mkdir(parents=True, exist_ok=True)
        mode_file.write_text(mode)
        return {"success": True, "mode": mode}
