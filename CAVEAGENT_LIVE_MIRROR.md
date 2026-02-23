# CAVEAgent Live Mirror Architecture

## The Vision

CAVEAgent is NOT a passive state holder that receives reports.
CAVEAgent ATTACHES to a live Claude Code session and MIRRORS its complete state.

**You use Claude Code through the HTTP server.**

---

## Current State (What We Built)

```
CAVEAgent (passive)
├── self.paia_states = {}  ← empty until reported to
├── self.remote_agents = {}
├── HTTP endpoints
└── Waits for hooks to POST state updates
```

**Problem:** Requires hooks to report. Not a true mirror.

---

## Target State (What It Should Be)

```
CAVEAgent (active live mirror)
│
├── ATTACH to tmux session
│   ├── auto-detect existing session OR use config
│   ├── capture_pane() → see current output
│   └── send_keys() → control input
│
├── READ Claude Code state from filesystem
│   ├── ~/.claude/settings.json → global settings
│   ├── ~/.claude/projects/{hash}/ → project state
│   ├── .claude/ in cwd → local project config
│   ├── MCP configs → which MCPs loaded
│   ├── Parse output → context window %
│   └── Hook configs → which hooks active
│
├── LIFT to unified state
│   └── self.state = {
│       "session": "cave",
│       "cwd": "/path/to/project",
│       "context_pct": 45,
│       "mcps_loaded": ["gnosys_kit", "starship", ...],
│       "skills_equipped": [...],
│       "current_output": "...",
│       "inbox": [...],
│       ...
│   }
│
└── HTTP ENDPOINTS = interface to live Claude
    ├── GET /output → capture_pane()
    ├── POST /input → send_keys("your message")
    ├── GET /state → complete lifted state
    ├── GET /inspect → everything
    ├── POST /run_agent → spawn SDNA subagents
    └── POST /command → send slash commands, etc.
```

---

## Key Changes Needed

### 1. Add ClaudeCodeAgent to CAVEAgent

```python
class CAVEAgent:
    def __init__(self, config: CAVEConfig):
        # ... existing init ...

        # THE LIVE MIRROR
        self.main_agent = ClaudeCodeAgent(
            tmux_session=config.main_agent_session,  # default: "cave"
            working_directory=config.main_agent_working_dir,
        )

        # State reader
        self.state_reader = ClaudeStateReader(
            claude_home=Path.home() / ".claude",
            project_dir=config.main_agent_working_dir,
        )
```

### 2. Create ClaudeStateReader

New file: `cave/core/state_reader.py`

```python
class ClaudeStateReader:
    """Reads Claude Code state from filesystem."""

    def __init__(self, claude_home: Path, project_dir: Path):
        self.claude_home = claude_home
        self.project_dir = project_dir

    def read_settings(self) -> dict:
        """Read ~/.claude/settings.json"""
        ...

    def read_mcp_config(self) -> dict:
        """Read MCP configuration."""
        ...

    def read_project_state(self) -> dict:
        """Read .claude/ project state."""
        ...

    def read_hooks(self) -> dict:
        """Read active hooks."""
        ...

    def get_complete_state(self) -> dict:
        """Return complete Claude Code state."""
        return {
            "settings": self.read_settings(),
            "mcps": self.read_mcp_config(),
            "project": self.read_project_state(),
            "hooks": self.read_hooks(),
        }
```

### 3. Add Live Endpoints

```python
# In CAVEAgent._setup_routes()

@self.app.get("/output")
def get_output(lines: int = 100):
    """Get current terminal output."""
    return {"output": self.main_agent.capture_pane(lines=lines)}

@self.app.post("/input")
def send_input(data: dict):
    """Send input to Claude."""
    text = data.get("text", "")
    press_enter = data.get("press_enter", True)
    self.main_agent.send_keys(text, enter=press_enter)
    return {"sent": True}

@self.app.get("/state")
def get_state():
    """Get complete lifted state."""
    return {
        "session": self.main_agent.tmux_session,
        "output": self.main_agent.capture_pane(lines=50),
        "claude_state": self.state_reader.get_complete_state(),
        "context_pct": self._parse_context_pct(),
        "remote_agents": {k: v.model_dump() for k, v in self.remote_agents.items()},
    }

@self.app.post("/command")
def send_command(data: dict):
    """Send a slash command to Claude."""
    command = data.get("command", "")
    self.main_agent.send_keys(command, enter=True)
    return {"sent": command}
```

### 4. Auto-Attach on Startup

```python
class CAVEAgent:
    def __init__(self, config: CAVEConfig):
        # ...

        # Auto-attach to tmux session
        self._attach_to_session()

    def _attach_to_session(self):
        """Find and attach to tmux session."""
        session = self.config.main_agent_session

        # Check if session exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True
        )

        if result.returncode == 0:
            # Session exists, we're attached
            self.main_agent = ClaudeCodeAgent(tmux_session=session)
            self._emit_event("attached", {"session": session})
        else:
            # No session - we'll create on first use or error
            self.main_agent = None
            self._emit_event("no_session", {"session": session})
```

---

## Startup Invariant

**No matter how you start, you get the same result:**

```
Option A: ./start_cave.sh
├── Starts CAVEAgent daemon
├── Creates tmux session with Claude
├── Daemon attaches to that session
└── Result: HTTP interface to live Claude

Option B: Manual
├── You start: tmux new -s cave
├── You run: claude
├── Later: python -m cave.server.http_server &
├── Daemon auto-attaches to existing "cave" session
└── Result: SAME - HTTP interface to live Claude
```

**Hot reload preserved:**
```
1. Daemon running, attached to session
2. Edit CAVEAgent code
3. Stop daemon (Claude keeps running in tmux)
4. pip install /tmp/cave
5. Start daemon
6. Daemon re-attaches
7. No state lost - Claude never stopped
```

---

## The Point

**Claude Code through HTTP = programmable automations on the main agent**

You can:
- Watch Claude work (GET /output polling)
- Inject prompts (POST /input)
- Check state (GET /state)
- Run subagents (POST /run_agent)
- All while Claude runs autonomously

**CAVEAgent IS the programmatic interface to a live Claude Code instance.**

---

## Files to Change

| File | Change |
|------|--------|
| `cave/core/cave_agent.py` | Add main_agent, state_reader, live endpoints |
| `cave/core/state_reader.py` | NEW - reads Claude Code filesystem state |
| `cave/core/config.py` | Maybe add more session/path config options |
| `cave/core/agent.py` | Ensure ClaudeCodeAgent has all needed methods |

---

## Implementation Order (Next Session)

1. Create `state_reader.py` - filesystem reading
2. Update `cave_agent.py` - add main_agent + state_reader
3. Add live endpoints - /output, /input, /state, /command
4. Add auto-attach logic
5. Test: start tmux+claude manually, then start daemon, verify it attaches
6. Test: use HTTP to control Claude
