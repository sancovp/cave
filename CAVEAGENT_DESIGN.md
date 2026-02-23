# CAVEAgent Design Document

## Overview

CAVEAgent is the "god object" - the unified runtime that provides codable global state.

**Core principle:** Everything flows through CAVEAgent. LLM can inspect/modify/reason about it.

---

## The Constructor

```python
class CAVEAgent:
    """The unified CAVE runtime. Starts and never dies."""

    def __init__(self, config: CAVEConfig):
        # === CONFIG ===
        self.config = config

        # === STATE (what we track) ===
        self.paia_states: Dict[str, PAIAState] = {}
        self.agent_registry: Dict[str, AgentRegistration] = {}
        self.remote_agents: Dict[str, RemoteAgentHandle] = {}

        # === ROUTING (how things communicate) ===
        self.message_router = MessageRouter()  # llegos-based
        self.hook_router = HookRouter()
        self.event_router = EventRouter()

        # === OUTPUT (how we communicate out) ===
        self.event_queue: asyncio.Queue = asyncio.Queue()  # SSE events

        # === SERVER ===
        self.app = FastAPI(title="CAVE Harness")
        self._setup_routes()
```

---

## CAVEConfig

```python
class CAVEConfig(BaseModel):
    """Configuration for CAVE runtime."""

    # === Server ===
    host: str = "0.0.0.0"
    port: int = 8421

    # === Paths ===
    data_dir: Path = Path("/tmp/heaven_data")
    hook_dir: Path = Path("/tmp/paia_hooks")

    # === System Prompt Templating ===
    system_prompt_template_path: Optional[Path] = None  # Path to template file
    system_prompt_target_path: Optional[Path] = None    # Where to write rendered prompt
    template_vars: Dict[str, str] = {}                  # {{VAR}} substitutions

    # === Main Agent ===
    main_agent_command: str = "claude"  # What to run in tmux
    main_agent_session: str = "cave"    # tmux session name
    main_agent_working_dir: Path = Path.cwd()

    # === Features ===
    enable_sse: bool = True
    enable_hook_routing: bool = True
    enable_message_routing: bool = True

    # === SDNA (optional) ===
    sdna_enabled: bool = True
    sdna_default_model: str = "claude-sonnet-4-20250514"
```

---

## State Models

```python
class PAIAState(BaseModel):
    """Runtime state of a PAIA."""
    paia_id: str
    status: Literal["idle", "working", "blocked", "needs_input"] = "idle"
    context_pct: int = 0  # 0-100
    inbox_count: int = 0
    current_task: Optional[str] = None
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)
    endpoint: Optional[str] = None  # Where to reach this PAIA
    metadata: Dict[str, Any] = {}


class AgentRegistration(BaseModel):
    """Registration of a CodeAgent with the runtime."""
    agent_id: str
    agent_type: Literal["paia", "worker", "ephemeral"] = "paia"
    endpoint: Optional[str] = None  # IP:port or "local"
    capabilities: List[str] = []
    registered_at: datetime = Field(default_factory=datetime.utcnow)


class RemoteAgentHandle(BaseModel):
    """Handle to a running SDNA remote agent."""
    agent_id: str
    config: Dict[str, Any]  # RemoteAgentConfig as dict
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    spawned_by: str  # Which PAIA spawned this
    spawned_at: datetime = Field(default_factory=datetime.utcnow)
    result: Optional[Dict[str, Any]] = None
```

---

## Mixins

CAVEAgent composes these mixins for functionality:

### PAIAStateMixin

```python
class PAIAStateMixin:
    """Mixin for PAIA state management."""
    paia_states: Dict[str, PAIAState]

    def update_paia_state(self, paia_id: str, **updates) -> PAIAState:
        """Update a PAIA's state."""
        if paia_id not in self.paia_states:
            self.paia_states[paia_id] = PAIAState(paia_id=paia_id)

        state = self.paia_states[paia_id]
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
        state.last_heartbeat = datetime.utcnow()

        self._emit_event("paia_state_changed", {"paia_id": paia_id, "state": state.model_dump()})
        return state

    def get_paia_state(self, paia_id: str) -> Optional[PAIAState]:
        """Get a PAIA's state."""
        return self.paia_states.get(paia_id)

    def list_paias(self) -> Dict[str, PAIAState]:
        """List all PAIAs and their states."""
        return self.paia_states.copy()

    def remove_paia(self, paia_id: str) -> bool:
        """Remove a PAIA from tracking."""
        if paia_id in self.paia_states:
            del self.paia_states[paia_id]
            self._emit_event("paia_removed", {"paia_id": paia_id})
            return True
        return False
```

### AgentRegistryMixin

```python
class AgentRegistryMixin:
    """Mixin for agent registration."""
    agent_registry: Dict[str, AgentRegistration]

    def register_agent(self, agent_id: str, **kwargs) -> AgentRegistration:
        """Register an agent with the runtime."""
        reg = AgentRegistration(agent_id=agent_id, **kwargs)
        self.agent_registry[agent_id] = reg
        self._emit_event("agent_registered", {"agent_id": agent_id})
        return reg

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent."""
        if agent_id in self.agent_registry:
            del self.agent_registry[agent_id]
            self._emit_event("agent_unregistered", {"agent_id": agent_id})
            return True
        return False

    def get_agent(self, agent_id: str) -> Optional[AgentRegistration]:
        """Get agent registration."""
        return self.agent_registry.get(agent_id)

    def list_agents(self) -> Dict[str, AgentRegistration]:
        """List all registered agents."""
        return self.agent_registry.copy()
```

### MessageRouterMixin

```python
class MessageRouterMixin:
    """Mixin for message routing between agents."""
    message_router: MessageRouter

    def route_message(self, from_agent: str, to_agent: str, content: str, **kwargs) -> str:
        """Route a message between agents. Returns message_id."""
        return self.message_router.send(from_agent, to_agent, content, **kwargs)

    def get_inbox(self, agent_id: str) -> List[Dict]:
        """Get an agent's inbox."""
        return self.message_router.get_inbox(agent_id)

    def ack_message(self, agent_id: str, message_id: str) -> bool:
        """Acknowledge a message (remove from inbox)."""
        return self.message_router.ack(agent_id, message_id)

    def broadcast(self, from_agent: str, content: str, **kwargs) -> List[str]:
        """Broadcast to all agents. Returns list of message_ids."""
        return self.message_router.broadcast(from_agent, content, **kwargs)
```

### HookRouterMixin

```python
class HookRouterMixin:
    """Mixin for hook signal routing."""
    hook_router: HookRouter

    def handle_hook(self, hook_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an incoming hook signal."""
        return self.hook_router.handle(hook_type, payload)

    def register_hook_handler(self, hook_type: str, handler: Callable) -> None:
        """Register a handler for a hook type."""
        self.hook_router.register(hook_type, handler)

    def get_hook_status(self) -> Dict[str, Any]:
        """Get status of all hook handlers."""
        return self.hook_router.status()
```

### RemoteAgentMixin

```python
class RemoteAgentMixin:
    """Mixin for SDNA remote agent management."""
    remote_agents: Dict[str, RemoteAgentHandle]

    async def spawn_remote(
        self,
        name: str,
        system_prompt: str,
        goal_template: str,
        spawned_by: str,
        inputs: Optional[Dict] = None,
        **kwargs
    ) -> RemoteAgentHandle:
        """Spawn a remote agent via SDNA."""
        from .remote_agent import RemoteAgent, RemoteAgentConfig

        agent_id = f"{name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        handle = RemoteAgentHandle(
            agent_id=agent_id,
            config={"name": name, "system_prompt": system_prompt, "goal_template": goal_template, **kwargs},
            status="pending",
            spawned_by=spawned_by
        )
        self.remote_agents[agent_id] = handle
        self._emit_event("remote_agent_spawned", {"agent_id": agent_id, "spawned_by": spawned_by})

        # Run async
        config = RemoteAgentConfig(name=name, system_prompt=system_prompt, goal_template=goal_template, **kwargs)
        agent = RemoteAgent(config)

        handle.status = "running"
        result = await agent.run(inputs or {})

        handle.status = "completed" if result.success else "failed"
        handle.result = result.__dict__
        self._emit_event("remote_agent_completed", {"agent_id": agent_id, "success": result.success})

        return handle

    def get_remote_status(self, agent_id: str) -> Optional[RemoteAgentHandle]:
        """Get status of a remote agent."""
        return self.remote_agents.get(agent_id)

    def list_remote_agents(self) -> Dict[str, RemoteAgentHandle]:
        """List all remote agents."""
        return self.remote_agents.copy()
```

### SSEMixin

```python
class SSEMixin:
    """Mixin for Server-Sent Events."""
    event_queue: asyncio.Queue

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

    async def event_generator(self):
        """Generator for SSE endpoint."""
        while True:
            event = await self.event_queue.get()
            yield f"data: {json.dumps(event)}\n\n"
```

---

## The Full CAVEAgent Class

```python
class CAVEAgent(
    PAIAStateMixin,
    AgentRegistryMixin,
    MessageRouterMixin,
    HookRouterMixin,
    RemoteAgentMixin,
    SSEMixin
):
    """The unified CAVE runtime."""

    def __init__(self, config: CAVEConfig):
        self.config = config

        # Initialize state
        self.paia_states: Dict[str, PAIAState] = {}
        self.agent_registry: Dict[str, AgentRegistration] = {}
        self.remote_agents: Dict[str, RemoteAgentHandle] = {}

        # Initialize routers
        self.message_router = MessageRouter(data_dir=config.data_dir)
        self.hook_router = HookRouter(hook_dir=config.hook_dir)
        self.event_router = EventRouter()

        # SSE queue
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # FastAPI app
        self.app = FastAPI(title="CAVE Harness", version="0.1.0")
        self._setup_routes()

        # Template substitution on startup
        if config.system_prompt_template_path and config.system_prompt_target_path:
            self._render_system_prompt()

    def _render_system_prompt(self) -> None:
        """Render system prompt template with substitutions."""
        template = self.config.system_prompt_template_path.read_text()
        rendered = template
        for key, value in self.config.template_vars.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        self.config.system_prompt_target_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.system_prompt_target_path.write_text(rendered)

    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""

        @self.app.get("/health")
        def health():
            return {"status": "ok", "version": "0.1.0"}

        @self.app.get("/inspect")
        def inspect():
            return self.inspect()

        @self.app.post("/hook_signal")
        def hook_signal(data: Dict[str, Any]):
            return self.handle_hook(data.get("hook_type", "unknown"), data.get("payload", {}))

        @self.app.post("/run_agent")
        async def run_agent(request: Dict[str, Any]):
            return await self.spawn_remote(**request)

        @self.app.post("/message")
        def send_message(data: Dict[str, Any]):
            msg_id = self.route_message(
                data["from_agent"],
                data["to_agent"],
                data["content"],
                **data.get("metadata", {})
            )
            return {"message_id": msg_id}

        @self.app.get("/inbox/{agent_id}")
        def get_inbox(agent_id: str):
            return self.get_inbox(agent_id)

        @self.app.get("/events")
        async def events():
            from starlette.responses import StreamingResponse
            return StreamingResponse(
                self.event_generator(),
                media_type="text/event-stream"
            )

    def inspect(self) -> Dict[str, Any]:
        """Return complete system state - AI legibility."""
        return {
            "paias": {k: v.model_dump() for k, v in self.paia_states.items()},
            "agents": {k: v.model_dump() for k, v in self.agent_registry.items()},
            "remote_agents": {k: v.model_dump() for k, v in self.remote_agents.items()},
            "messages": self.message_router.summary(),
            "hooks": self.hook_router.status(),
            "config": {
                "host": self.config.host,
                "port": self.config.port,
                "data_dir": str(self.config.data_dir),
            }
        }

    async def run(self) -> None:
        """Start the CAVE runtime. Never dies."""
        import uvicorn
        config = uvicorn.Config(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
```

---

## Extension Points for Sanctuary Revolution

SR extends CAVEAgent with game-specific functionality:

```python
class SanctuaryRevolutionAgent(CAVEAgent):
    """Sanctuary Revolution game server."""

    def __init__(self, config: SRConfig):
        super().__init__(config)

        # Game-specific state
        self.paiab_builder = PAIABBuilder()
        self.cave_builder = CAVEBuilder()
        self.sanctum_builder = SANCTUMBuilder()
        self.gear_system = GEARSystem()

        # Game-specific routers
        self.psyche_module = PsycheModule()
        self.world_module = WorldModule()

        # Add game routes
        self._setup_game_routes()

    def _setup_game_routes(self) -> None:
        """Add SR-specific routes."""

        @self.app.post("/paiab/{action}")
        def paiab_action(action: str, data: Dict):
            return self.paiab_builder.handle(action, data)

        @self.app.post("/cave/{action}")
        def cave_action(action: str, data: Dict):
            return self.cave_builder.handle(action, data)

        @self.app.post("/sanctum/{action}")
        def sanctum_action(action: str, data: Dict):
            return self.sanctum_builder.handle(action, data)

        @self.app.get("/gear")
        def get_gear():
            return self.gear_system.status()
```

---

## Library Structure (Final)

```
cave/                          # pip install cave-harness
├── __init__.py               # Exports CAVEAgent, CAVEConfig
├── core/
│   ├── __init__.py
│   ├── agent.py              # CodeAgent, ClaudeCodeAgent (KEEP)
│   ├── remote_agent.py       # RemoteAgent - SDNA wrapper (KEEP)
│   ├── cave_agent.py         # CAVEAgent - THE GOD OBJECT (NEW)
│   ├── config.py             # CAVEConfig (NEW)
│   ├── models.py             # PAIAState, AgentRegistration, etc. (NEW)
│   └── mixins/               # Mixin classes (NEW)
│       ├── __init__.py
│       ├── paia_state.py
│       ├── agent_registry.py
│       ├── message_router.py
│       ├── hook_router.py
│       ├── remote_agent.py
│       └── sse.py
├── routing/
│   ├── __init__.py
│   ├── message_router.py     # llegos-based message routing (NEW)
│   ├── hook_router.py        # Hook signal routing (EXTRACT from event_router.py)
│   └── event_router.py       # Generic event routing (KEEP, remove game helpers)
├── server/
│   ├── __init__.py
│   └── http_server.py        # run_server() entry point (SIMPLIFY)
├── docker/                    # Container infrastructure (KEEP)
│   └── ...
└── scripts/
    ├── start_cave.sh         # Entry point script (NEW)
    └── stop_cave.sh          # Shutdown script (NEW)
```

---

## Files to DELETE/MOVE

| File | Action | Reason |
|------|--------|--------|
| `server/orchestrator.py` | DELETE | Marked DEPRECATED |
| `core/harness.py` | SPLIT | Keep base, move psyche/world/system to SR |
| `core/output_watcher.py` | MOVE TO SR | Game-specific terminal watching |
| `core/terminal_ui.py` | MOVE TO SR | Game-specific UI |
| `core/self_command_generator.py` | EVALUATE | May be game-specific |
| `core/hook_control.py` | EVALUATE | May be base or game-specific |
| `adapters/*` | EVALUATE | heaven_integration may stay, langchain may go |
| `mcp/*` | KEEP | harness_client_mcp is base |

---

## start_cave.sh

```bash
#!/bin/bash
# CAVE Entry Point

# Load config
CONFIG_FILE="${1:-cave_config.yaml}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Config file not found: $CONFIG_FILE"
    exit 1
fi

# Start CAVE daemon
python -m cave.server.http_server --config "$CONFIG_FILE" &
CAVE_PID=$!
echo $CAVE_PID > /tmp/cave.pid

echo "CAVE daemon started (PID: $CAVE_PID)"

# Wait for ready
sleep 2

# Attach to environment
SESSION=$(grep 'main_agent_session' "$CONFIG_FILE" | awk '{print $2}' | tr -d '"')
SESSION=${SESSION:-cave}

if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux attach -t "$SESSION"
else
    WORKDIR=$(grep 'main_agent_working_dir' "$CONFIG_FILE" | awk '{print $2}' | tr -d '"')
    WORKDIR=${WORKDIR:-$(pwd)}

    AGENT_CMD=$(grep 'main_agent_command' "$CONFIG_FILE" | awk '{print $2}' | tr -d '"')
    AGENT_CMD=${AGENT_CMD:-claude}

    tmux new-session -s "$SESSION" -c "$WORKDIR" "$AGENT_CMD"
fi
```
