"""CAVE State Models.

Pydantic models for tracking PAIAs, agents, and remote agents.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class MainAgentConfig(BaseModel):
    """Configuration for the main Claude Code agent managed by CAVE.

    This is the structured config that gets archived/injected.
    """

    agent_id: str = "main"

    # Which hooks from registry are active, by hook type
    # e.g., {"stop": ["brainhook", "autopoiesis_stop"], "pretooluse": ["context_reminder"]}
    active_hooks: Dict[str, List[str]] = Field(default_factory=dict)

    # Command and session info
    command: str = "claude"
    tmux_session: str = "claude"
    working_dir: str = "."

    # Any other agent-specific settings
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HeartbeatConfig(BaseModel):
    """Heartbeat configuration for an agent."""
    enabled: bool = False
    interval_seconds: float = 300.0
    prompt: str = "Heartbeat: check status, report."
    separate_conversation: bool = False  # True = heartbeat gets its own transcript


class CaveAgentEntry(BaseModel):
    """Configuration for one agent in the CAVE registry.

    CAVE_REFACTOR Stage 5: Replaces MainAgentConfig (singular) with
    a list of these entries in CAVEConfig.agents.

    Each entry defines: what type of CAVE agent, what runtime it wraps,
    and what conversations (channels) it has.
    """
    name: str  # e.g., "conductor", "gnosys", "autobiographer", "openclaw"
    agent_type: Literal["chat", "code", "claw", "service", "remote"] = "chat"

    # Channel mode preset — determines default modes on all channels
    # complete_mirror: every channel gets mirror+broadcast (ChatAgent default)
    # notify: channels get broadcast only — lifecycle events (ServiceAgent default)
    # mixed: each channel defines its own modes via "modes" key in channel config
    channel_mode: Literal["complete_mirror", "notify", "mixed"] = "complete_mirror"

    # Runtime config — what the agent actually wraps
    # For code agents: command + tmux
    command: str = ""
    tmux_session: str = ""
    working_dir: str = "."

    # Channel config — the conversations this agent has
    # Keys are conversation names, values are channel type + config
    # e.g., {"main": {"type": "discord", "channel_id": "123", "modes": ["mirror", "broadcast"]},
    #        "heartbeat": {"type": "discord", "channel_id": "123"}}
    channels: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    # Heartbeat config — Heart adds a tick for this agent if enabled
    heartbeat: Optional[HeartbeatConfig] = None

    # Hooks active on this agent
    active_hooks: Dict[str, List[str]] = Field(default_factory=dict)

    # Agent-specific metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PAIAState(BaseModel):
    """Runtime state of a PAIA (Personal AI Agent)."""

    paia_id: str
    status: Literal["idle", "working", "blocked", "needs_input"] = "idle"
    context_pct: int = Field(default=0, ge=0, le=100)
    inbox_count: int = Field(default=0, ge=0)
    current_task: Optional[str] = None
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)
    endpoint: Optional[str] = None  # Where to reach this PAIA (IP:port or "local")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # DNA System Fields
    mode: Literal["DAY", "NIGHT"] = "DAY"
    current_loop: Optional[str] = None  # Name of current AgentInferenceLoop
    omnisanc_zone: Optional[str] = None  # HOME, STARPORT, SESSION, LANDING, MISSION


class AgentRegistration(BaseModel):
    """Registration of a CodeAgent with the CAVE runtime."""

    agent_id: str
    agent_type: Literal["paia", "worker", "ephemeral"] = "paia"
    endpoint: Optional[str] = None  # IP:port or "local"
    capabilities: List[str] = Field(default_factory=list)
    registered_at: datetime = Field(default_factory=datetime.utcnow)


class RemoteAgentHandle(BaseModel):
    """Handle to a running SDNA remote agent."""

    agent_id: str
    config: Dict[str, Any] = Field(default_factory=dict)  # RemoteAgentConfig as dict
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    spawned_by: str  # Which PAIA spawned this
    spawned_at: datetime = Field(default_factory=datetime.utcnow)
    result: Optional[Dict[str, Any]] = None
