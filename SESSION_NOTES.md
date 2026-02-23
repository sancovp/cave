# CAVE Integration Roadmap Notes

## CURRENT STATE - What Exists

### 1. omnisanc_logic.py (2170 lines)
**Location:** `/home/GOD/omnisanc_core_daemon/omnisanc_logic.py`
**What it does:** HOME/JOURNEY state machine enforcing workflow via Claude Code hooks
**State file:** `/tmp/heaven_data/omnisanc_core/.course_state`
**State keys:** course_plotted, projects, flight_selected, waypoint_step, session_active, mission_active, mission_id, needs_review, landing phases, domain/subdomain/process, etc.
**Entry points:** on_tool_use() (PreToolUse), on_tool_result() (PostToolUse)
**Dependencies:** heaven_base.registry, starsystem.mission, llm_intelligence (GIINT), canopy, strata_unwrap

### 2. CAVE (`/tmp/cave/`)
**What it is:** HTTP server + CAVEAgent class composed of mixins
**CAVEAgent state:**
- paia_states, agent_registry, remote_agents
- main_agent (tmux control)
- dna (AutoModeDNA for loop orchestration)
- _hook_state, _hook_history (from HookRouterMixin)

**Mixins:** HookRouterMixin, LoopManagerMixin, PAIAStateMixin, AgentRegistryMixin, MessageRouterMixin, RemoteAgentMixin, SSEMixin

**DNA System:**
- AutoModeDNA: orchestrates list of AgentInferenceLoop
- AgentInferenceLoop: name + prompt + active_hooks + exit_condition + next
- Exit mechanism: check_and_transition() called every hook pass, checks exit_condition against _hook_state

### 3. Hooks in `/tmp/heaven_data/cave_hooks/`
- autopoiesis_stop.py - blocks stop if promise file exists
- brainhook.py - ?
- guru_pretool.py, guru_posttool.py, guru_stop.py - emanation detection
- context_reminder.py - ?

### 4. autopoiesis_mcp (`/tmp/autopoiesis_mcp/`)
**What it does:** Promise-based self-continuation via MCP tool
**Key tool:** be_autopoietic(mode="promise"|"blocked")
**State:** File-based - /tmp/active_promise.md exists = working, gone = done

---

## THE 5 SYSTEMS TO PORT INTO CAVE

1. **OMNISANC** - HOME/JOURNEY state machine (2170 lines)
2. **GURU** - Emanation detection, bodhisattva vow (can't exit without creating reusable artifact)
3. **AUTOPOIESIS** - Promise-based self-continuation
4. **BRAINHOOK** - Recursion protection (?)
5. **METABRAINHOOK** - Top-level, agent can't turn off (?)

---

## RELATIONSHIP PROBLEM

Currently omnisanc and CAVE are **separate systems that don't talk to each other**:
- omnisanc has its own state file, runs as daemon, called by ~/.claude/hooks/
- CAVE has its own state (_hook_state), runs as HTTP server, has its own hook system

**Goal:** All 5 systems unified inside CAVEAgent with shared state

---

## QUESTIONS THAT NEED ANSWERS

1. What does BRAINHOOK do exactly?
2. What does METABRAINHOOK do exactly?
3. How should omnisanc's 2170 lines be restructured for CAVE?
4. What is the unified state schema?
5. What is the loop stack order? (brainhook → autopoiesis → guru → metabrainhook?)

---

## WHAT WE DID THIS SESSION

1. Read omnisanc_logic.py (full 2170 lines)
2. Read CAVE codebase (cave_agent.py, mixins, dna.py, loops)
3. Read autopoiesis_mcp (be_autopoietic MCP tool)
4. Read cave_hooks (autopoiesis_stop, guru_*, brainhook)
5. Fixed autopoiesis.py exit_condition to use file-based check (matching autopoiesis_mcp pattern)

---

## NEXT SESSION NEEDS TO

1. Define what BRAINHOOK and METABRAINHOOK actually do
2. Design unified state schema for CAVEAgent
3. Design loop stack architecture
4. Start porting systems one by one
