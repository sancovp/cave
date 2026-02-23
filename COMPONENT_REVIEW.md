# CAVE Component Review Checklist

## Purpose
Track review progress of all CAVE library components. Mark status and notes as we review each file.

---

## Reviewed Components

### core/agent.py
- **Status:** ✅ REVIEWED
- **Lines:** ~487
- **Contains:** CodeAgent, ClaudeCodeAgent, CodeAgentConfig, message types (InboxMessage, UserPromptMessage, etc.)
- **Decision:** KEEP in CAVE - this is base library
- **Notes:** Uses llegos Actor model for inbox. Solid base class for any code agent.

### core/remote_agent.py
- **Status:** ✅ REVIEWED
- **Lines:** ~140
- **Contains:** RemoteAgent, RemoteAgentConfig, RemoteAgentResult
- **Decision:** KEEP in CAVE - SDNA wrapper
- **Notes:** Bridges CAVE to SDNA for claude -p execution.

### core/harness.py
- **Status:** ✅ REVIEWED
- **Lines:** ~380
- **Contains:** PAIAHarness, HarnessConfig
- **Decision:** SPLIT - base harness stays, psyche/world/system modules move to SR
- **Notes:** Has tick loop, tmux control, event injection. Game-specific module imports need removal.

### core/event_router.py
- **Status:** ✅ REVIEWED
- **Lines:** ~383
- **Contains:** EventRouter, Event, EventSource, EventOutput, HookInjection, InTerminalObject
- **Decision:** KEEP in CAVE - generic event routing
- **Notes:** The psyche_event/world_event/system_event helpers are SR-specific, but EventRouter itself is generic.

### core/output_watcher.py
- **Status:** ✅ REVIEWED
- **Lines:** ~238
- **Contains:** OutputWatcher, DetectedEvent, PatternMatcher, EventType
- **Decision:** KEEP in CAVE - generic pattern matching
- **Notes:** DEFAULT_PATTERNS are PAIA-specific (CogLog, SkillLog), but pattern system is generic. Make patterns configurable.

### core/terminal_ui.py
- **Status:** ✅ REVIEWED
- **Lines:** ~307
- **Contains:** TerminalUI, InTerminalNotification, InTerminalOverlay, InTerminalPanel, NotificationType
- **Decision:** KEEP in CAVE - generic tmux UI
- **Notes:** NotificationType.PSYCHE and notify_psyche() are SR-specific. Base notification system is generic.

### server/http_server.py
- **Status:** ✅ REVIEWED
- **Lines:** ~138
- **Contains:** FastAPI app, /health, /run_agent, /hook_signal endpoints
- **Decision:** KEEP in CAVE - base server
- **Notes:** Simple base. CAVEAgent will extend this with more endpoints.

### server/orchestrator.py
- **Status:** ✅ REVIEWED - DEPRECATED
- **Lines:** ~595
- **Contains:** Docker orchestration via docker.sock
- **Decision:** DELETE - marked deprecated, replaced by http_server pattern
- **Notes:** Historical reference only.

---

## Reviewed (Session 2)

### core/hook_control.py
- **Status:** ✅ REVIEWED
- **Lines:** ~87
- **Contains:** HookControl class - enable/disable/toggle hooks via JSON file flag
- **Decision:** KEEP in CAVE - generic hook toggling infrastructure
- **Notes:** Static methods, file-based persistence at /tmp/hook_config.json

### core/self_command_generator.py
- **Status:** ✅ REVIEWED
- **Lines:** ~212
- **Contains:** RestartConfig, CompactConfig, InjectConfig dataclasses + SelfCommandGenerator
- **Decision:** KEEP in CAVE - generic tmux control infrastructure
- **Notes:** Generates bash scripts dynamically from config, execute via subprocess

### adapters/heaven_integration.py
- **Status:** ✅ REVIEWED
- **Lines:** ~145
- **Contains:** ClaudeCodeProvider factory, wiring docs for "Heaven" system
- **Decision:** DELETE - app-specific example, not library code
- **Notes:** "Heaven" is a specific application, not base CAVE

### adapters/langchain_adapter.py
- **Status:** ✅ REVIEWED
- **Lines:** ~139
- **Contains:** ClaudeCodeChatModel extending LangChain's BaseChatModel
- **Decision:** DELETE - keeping CAVE lean, no LangChain dependency
- **Notes:** User decision to exclude

### mcp/harness_client_mcp.py
- **Status:** ✅ REVIEWED
- **Lines:** ~169
- **Contains:** FastMCP server wrapping harness HTTP API (hooks, persona, self-commands, harness control)
- **Decision:** KEEP in CAVE - this IS the MCP interface to CAVEAgent
- **Notes:** Core library component - how agents call harness

### docker/container_handoff.py
- **Status:** ✅ REVIEWED
- **Lines:** ~398
- **Contains:** Container-side handoff server (DEPRECATED)
- **Decision:** DELETE - explicitly deprecated, replaced by http_server.py
- **Notes:** Historical reference only

### utils/rng/base.py
- **Status:** ✅ REVIEWED
- **Lines:** ~86
- **Contains:** RNGModule, RNGEvent, EventDomain enum (PSYCHE, WORLD, SYSTEM)
- **Decision:** MOVE TO SR - game-specific probabilistic event injection
- **Notes:** EventDomain.PSYCHE/WORLD/SYSTEM are Sanctuary Revolution concepts

---

## Summary

| Category | Reviewed | KEEP | DELETE | MOVE TO SR |
|----------|----------|------|--------|------------|
| core/ | 8 | 6 | 0 | 0 |
| server/ | 2 | 1 | 1 | 0 |
| adapters/ | 2 | 0 | 2 | 0 |
| mcp/ | 1 | 1 | 0 | 0 |
| docker/ | 1 | 0 | 1 | 0 |
| utils/ | 1 | 0 | 0 | 1 |
| **TOTAL** | **15** | **8** | **4** | **1** |

---

## Key Decisions Made

1. **CAVEAgent** = god object with mixins (PAIAStateMixin, AgentRegistryMixin, MessageRouterMixin, HookRouterMixin, RemoteAgentMixin, SSEMixin)

2. **CAVEConfig** = Pydantic model with system prompt templating

3. **orchestrator.py** = DELETE (deprecated)

4. **Pattern for SR extension:** SR extends CAVEAgent class, adds game-specific builders/modules

5. **Input vs Output channels:**
   - Input: Hooks/HTTP → CAVEAgent → inbox
   - Output: capture_pane() → OutputWatcher → events → SSE

---

## Files Created This Session

- `/tmp/cave/CAVEAGENT_DESIGN.md` - Full CAVEAgent design with mixins, config, extension points
- `/tmp/cave/COMPONENT_REVIEW.md` - This file

## Docs Updated This Session

- `/tmp/launch_v0/roadmap_complete_jan18/CAVE_ARCHITECTURE.md`
  - Added "The Vibe Coding Scalability Problem" section
  - Added "That's Just Coding!" section (what CAVE actually is)
