# Cave Hooks Documentation

Location: `/tmp/heaven_data/cave_hooks/`

## Overview

These hooks use the `cave` framework (`ClaudeCodeHook`, `HookType`, `HookDecision`, `HookResult`). They form a loop control system for Claude Code sessions.

---

## Hook Files

### 1. brainhook.py

**Class:** `Brainhook`
**Trigger:** `HookType.STOP`
**Purpose:** Blocks stop to keep agent in an infinite work loop until manually disabled.

**State Read:**
- `/tmp/brainhook_state.txt` - contains "on" or "off"
- Optional prompt file (configurable)

**State Written:** None

**Behavior:**
- If state file contains "on": BLOCK stop with a prompt telling agent to "look again"
- If state file missing or "off": APPROVE stop
- Default prompt encourages agent to re-examine work for missed aspects

**Relationships:** Base-level loop. Can be toggled externally via bash command.

---

### 2. autopoiesis_stop.py

**Class:** `AutopoiesisStopHook`
**Trigger:** `HookType.STOP`
**Purpose:** Blocks exit until an autopoiesis promise is completed.

**State Read:**
- `/tmp/autopoiesis_promise.txt` - existence indicates active promise

**State Written:** None (MCP writes the promise file)

**Behavior:**
- If promise file exists: BLOCK with "complete or release before stopping"
- If no promise file: APPROVE stop

**Relationships:** Works with autopoiesis MCP which manages the promise file.

---

### 3. context_reminder.py

**Class:** `ContextReminderHook`
**Trigger:** `HookType.PRE_TOOL_USE`
**Purpose:** Injects context reminders before tool execution.

**State Read:** None (configured at init)

**State Written:** None

**Behavior:**
- If tool_filter set and tool not in filter: CONTINUE (no injection)
- Otherwise: CONTINUE with `additional_context` containing reminder

**Relationships:** Passive - adds context without blocking. Can be filtered to specific tools.

---

### 4. guru_pretool.py

**Class:** `GuruPreToolHook`
**Trigger:** `HookType.PRE_TOOL_USE`
**Purpose:** Tracks work and reminds about emanation requirement.

**State Read:**
- `state["guru"]["work_summary"]` - list of tool names
- `state["guru"]["emanation_created"]` - boolean

**State Written:**
- `state["guru"]["work_summary"]` - appends current tool name

**Behavior:**
- Appends tool name to work_summary
- If >10 tools used AND no emanation created: inject reminder context
- Always CONTINUE

**Relationships:** Part of guru loop. Works with guru_posttool and guru_stop.

---

### 5. guru_posttool.py

**Class:** `GuruPostToolHook`
**Trigger:** `HookType.POST_TOOL_USE`
**Purpose:** Detects when agent creates an emanation (skill/flight).

**State Read:**
- `payload["tool_name"]`
- `payload["tool_input"]["file_path"]`

**State Written:**
- `state["guru"]["emanation_created"]` - set True when detected
- `state["guru"]["emanation_type"]` - "skill" or "flight"
- `state["guru"]["emanation_path"]` - path of created file

**Behavior:**
- If tool is "Write" and path contains "/skills/" or "SKILL.md": mark skill emanation
- If tool is "Write" and path contains "flight_config": mark flight emanation
- Always CONTINUE

**Relationships:** Part of guru loop. Sets state that guru_stop checks.

---

### 6. guru_stop.py

**Class:** `GuruStopHook`
**Trigger:** `HookType.STOP`
**Purpose:** Blocks exit unless emanation created or loop paused.

**State Read:**
- `state["guru"]["paused"]` - boolean
- `state["guru"]["emanation_created"]` - boolean
- `state["guru"]["emanation_type"]` - string

**State Written:** None

**Behavior:**
- If paused: APPROVE with "Paused - exit allowed"
- If emanation_created: APPROVE with confirmation message
- Otherwise: BLOCK with "Cannot exit without creating an emanation"

**Relationships:** Final gate of guru loop. Requires guru_posttool to set emanation_created.

---

### 7. test_block_stop.py

**Class:** `TestBlockStopHook`
**Trigger:** `HookType.STOP`
**Purpose:** Testing hook that always blocks stop.

**State Read:** None
**State Written:** None

**Behavior:** Always BLOCK with test message.

**Relationships:** Standalone test hook.

---

## Hook Relationships Diagram

```
PRE_TOOL_USE:
  context_reminder.py  -->  [inject reminder]
  guru_pretool.py      -->  [track tools, remind if >10 without emanation]

POST_TOOL_USE:
  guru_posttool.py     -->  [detect skill/flight creation]

STOP:
  brainhook.py         -->  [block if /tmp/brainhook_state.txt == "on"]
  autopoiesis_stop.py  -->  [block if /tmp/autopoiesis_promise.txt exists]
  guru_stop.py         -->  [block unless emanation_created or paused]
  test_block_stop.py   -->  [always block - testing only]
```

## Loop Stack

The hooks form a layered loop control system:

1. **Brainhook** - Basic infinite loop (file-based toggle)
2. **Autopoiesis** - Promise-based loop (file-based, MCP-controlled)
3. **Guru** - Emanation-required loop (in-memory state, multi-hook coordination)

All STOP hooks must APPROVE for agent to exit. Any BLOCK prevents exit.

## State Files

| File | Hook | Purpose |
|------|------|---------|
| `/tmp/brainhook_state.txt` | brainhook | "on"/"off" toggle |
| `/tmp/autopoiesis_promise.txt` | autopoiesis_stop | Existence = active promise |

## In-Memory State Keys

| Key | Written By | Read By |
|-----|------------|---------|
| `guru.work_summary` | guru_pretool | guru_pretool |
| `guru.emanation_created` | guru_posttool | guru_pretool, guru_stop |
| `guru.emanation_type` | guru_posttool | guru_stop |
| `guru.emanation_path` | guru_posttool | - |
| `guru.paused` | (external) | guru_stop |
