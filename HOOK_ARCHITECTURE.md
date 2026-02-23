# CAVEAgent Hook Architecture

## Core Concept

CAVEAgent becomes the **hook execution layer**. All user hooks run INSIDE CAVEAgent, not directly in Claude Code.

## The Flow

```
User's Claude Config (has hooks)
        ↓
    "Make this a CAVEAgent main agent config"
        ↓
    CAVEAgent LIFTS hooks out
        ↓
    Converts hooks to callable modules
        ↓
    Bakes hook routing config
        ↓
    Replaces Claude config with ONLY paia hooks
        ↓
    DONE - now at runtime:

Claude event → paia_hook → CAVEAgent → routing config → lifted hooks execute → return → paia_hook → Claude
```

## What Gets Built

### 1. Hook Lifter
- Read hook files from user's Claude config
- Convert to importable Python modules
- Store in CAVEAgent runtime

### 2. Hook Routing Config
- Maps hook types to lifted hooks
- Example:
```json
{
  "UserPromptSubmit": ["hook_a", "hook_b"],
  "PreToolUse": ["hook_c"],
  "PostToolUse": ["hook_d", "hook_e"]
}
```

### 3. Runtime Executor
- Endpoint receives PAIA hook calls
- Looks up routing config
- Executes the right lifted hooks
- Returns results

### 4. PAIA Hooks
- Thin forwarders installed in Claude config
- ONLY hooks in the actual Claude config
- Forward all inputs to CAVEAgent HTTP endpoint
- Return CAVEAgent's response to Claude

## Why This Matters

**Self-awareness**: CAVEAgent KNOWS all hooks because they run inside it.

**Causal chaining**: CAVEAgent can trace every hook execution because it controls them.

**Hot modification**: CAVEAgent can modify hook behavior at runtime without touching Claude config.

**Centralized control**: All hook logic in one place, one runtime, one state.

## Implementation Steps

1. **HookLifter class**
   - `lift_from_config(claude_home: Path)` - reads all hooks
   - `convert_to_module(hook_file: Path)` - makes importable
   - `generate_routing_config()` - builds the map

2. **Update HookRouterMixin**
   - Store lifted hooks as modules
   - Store routing config
   - `execute_hooks(hook_type, payload)` - runs the right ones

3. **Add endpoint**
   - `POST /hook_signal` - receives PAIA hook calls
   - Passes to HookRouterMixin
   - Returns results

4. **Create PAIA hooks**
   - `paia_userpromptsubmit.py`
   - `paia_pretooluse.py`
   - `paia_posttooluse.py`
   - etc.
   - All just HTTP POST to CAVEAgent

5. **Update config archiver**
   - When archiving, include the routing config
   - When injecting, also inject routing config
