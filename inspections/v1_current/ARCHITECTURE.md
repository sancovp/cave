# CAVE Architecture

Code Agent Virtualization Environment - Live mirror and control harness for Claude Code agents.

## File Map

| File | Purpose |
|------|---------|
| `cave_agent.py` | God object composing 7 mixins, owns all runtime state |
| `config.py` | Pydantic config, persists to `cave_agent_config.json` |
| `models.py` | Data models (PAIAState, AgentRegistration, MainAgentConfig) |
| `agent.py` | ClaudeCodeAgent - tmux wrapper for main agent |
| `state_reader.py` | Parses Claude Code terminal output (context %) |
| `dna.py` | AutoModeDNA - orchestrates loop sequences |
| `hooks.py` | Hook definitions |
| `hook_control.py` | Hook enable/disable logic |
| `config_snapshots.py` | MainAgentConfigManager for archive/inject |
| `remote_agent.py` | RemoteAgentHandle for spawned agents |
| `server/http_server.py` | FastAPI endpoints, global CAVEAgent instance |

### Mixins (7)

| Mixin | Responsibility |
|-------|---------------|
| `PAIAStateMixin` | PAIA state dict management |
| `AgentRegistryMixin` | Agent registration tracking |
| `MessageRouterMixin` | Message routing between agents |
| `HookRouterMixin` | Hook signal dispatch, `_hook_state` dict |
| `LoopManagerMixin` | Loop lifecycle (start/stop/pause/resume) |
| `RemoteAgentMixin` | Spawn/track remote claude -p agents |
| `SSEMixin` | Server-sent events for real-time updates |

### Loops

| File | Loop |
|------|------|
| `loops/base.py` | `AgentInferenceLoop` dataclass |
| `loops/autopoiesis.py` | `AUTOPOIESIS_LOOP` |
| `loops/guru.py` | `GURU_LOOP` |

## HTTP Endpoints

### Config Archives
| Method | Path | Action |
|--------|------|--------|
| GET | `/configs` | List archives |
| GET | `/configs/active` | Current config info |
| POST | `/configs/archive` | Save current as named |
| POST | `/configs/inject` | Restore named archive |
| DELETE | `/configs/{name}` | Delete archive |
| POST | `/configs/export` | Export to path |
| POST | `/configs/import` | Import from path |

### Loops
| Method | Path | Action |
|--------|------|--------|
| GET | `/loops/state` | Current loop state |
| GET | `/loops/available` | List loop configs |
| POST | `/loops/start` | Start loop by type |
| POST | `/loops/stop` | Stop current loop |
| POST | `/loops/trigger` | Trigger transition |
| POST | `/loops/pause` | Pause loop |
| POST | `/loops/resume` | Resume loop |

### DNA (Auto Mode)
| Method | Path | Action |
|--------|------|--------|
| GET | `/dna/status` | DNA status |
| POST | `/dna/start` | Start with loop sequence |
| POST | `/dna/stop` | Stop auto mode |

### Live Mirror
| Method | Path | Action |
|--------|------|--------|
| GET | `/output` | Capture tmux pane |
| POST | `/input` | Send keys to tmux |
| GET | `/state` | Full state (terminal + claude + runtime) |
| POST | `/command` | Send slash command |
| POST | `/attach` | Attach to session |
| GET | `/inspect` | Full CAVEAgent inspection |

### Hooks
| Method | Path | Action |
|--------|------|--------|
| POST | `/hook/{type}` | Receive hook signal |
| POST | `/hooks/scan` | Rescan hook dir |
| GET | `/hooks` | List hooks |
| GET | `/hooks/status` | Full hook status |
| GET | `/hooks/active` | Active hooks config |
| POST | `/hooks/active` | Set active hooks |

### Modules
| Method | Path | Action |
|--------|------|--------|
| GET | `/modules` | List modules |
| POST | `/modules/load` | Hot-load module |
| POST | `/modules/unload` | Unload module |
| GET | `/modules/history` | Load history |

### Other
| Method | Path | Action |
|--------|------|--------|
| GET | `/health` | Health check |
| GET | `/paias` | List PAIA states |
| POST | `/paias/{id}` | Update PAIA state |
| POST | `/run_agent` | Spawn remote agent |
| GET | `/remote_agents` | List remote agents |
| GET | `/remote_agents/{id}` | Get remote agent |
| GET | `/messages/inbox/{id}/count` | Inbox count |
| GET | `/events` | SSE stream |

## State Locations

| State | Location |
|-------|----------|
| CAVEConfig | `/tmp/heaven_data/cave_agent_config.json` |
| Config archives | `/tmp/heaven_data/cave_config_archives/{name}.json` |
| Hook scripts | `/tmp/heaven_data/cave_hooks/` |
| Main agent hooks | `~/.claude/hooks/` (via config.claude_home) |
| Loop state | In-memory `_loop_state` dict |
| Hook state | In-memory `_hook_state` dict |
| PAIA states | In-memory `paia_states` dict |
| Agent registry | In-memory `agent_registry` dict |

## DNA/Loop System

```
AutoModeDNA
  |-- loops: List[AgentInferenceLoop]
  |-- exit_behavior: one_shot | cycle
  |-- current_index: int

AgentInferenceLoop
  |-- prompt: str (injected via tmux)
  |-- active_hooks: Dict[str, List[str]]
  |-- exit_condition: Callable[[Dict], bool]
  |-- next: Optional[str] (chain to loop)
```

**Flow:**
1. `dna.start()` activates first loop
2. Loop sets `active_hooks` on config, sends prompt via tmux
3. On hook signals, `check_and_transition()` tests exit condition
4. If exit met: deactivate current, activate next (or cycle/stop)

**Available Loops:** `autopoiesis`, `guru`
