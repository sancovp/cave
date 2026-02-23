# DNA Workflow System Architecture

**Date:** 2026-01-26
**Status:** Design specification

---

## Overview

CAVEAgent has a workflow system. DNA is what gets plugged into it. CAVEAgent runs it, DNA is just data.

---

## Layer Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    SancRevAgent                          │
│         (our CAVEAgent subclass for SancRev)            │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  run_omnisanc()                                  │    │
│  │  - THE ACTUAL WORKFLOW LOGIC                     │    │
│  │  - reads state, runs transitions, activates hooks│    │
│  └─────────────────────────────────────────────────┘    │
│                          │                               │
│                          ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │  self.dna = OMNISANC                             │    │
│  │  - loops: HOME_DAY, HOME_NIGHT, STARPORT, etc.   │    │
│  │  - transitions: state check functions            │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                          │
                          │ inherits from
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    CAVEAgent                             │
│              (CAVE library - generic)                    │
│                                                          │
│  - dna: DNA = None (slot for subclass to fill)          │
│  - run_impl(): pass (override point)                    │
│  - run(): setup, then calls run_impl()                  │
│  - get_omnisanc_state(): reads .course_state            │
│  - HookRouter: manages hook execution                   │
│  - all the infrastructure mixins                        │
└─────────────────────────────────────────────────────────┘
```

---

## Components

### 1. CAVEAgent (CAVE library - generic)

```python
class CAVEAgent:
    dna: DNA = None  # slot for DNA, filled by subclass

    def run_impl(self):
        pass  # OVERRIDE POINT - subclass implements this

    def run(self):
        # ... setup ...
        self.run_impl()

    # Infrastructure (already exists via mixins):
    # - get_omnisanc_state() → reads .course_state file
    # - HookRouter → manages hook execution
    # - etc.
```

CAVEAgent provides infrastructure. It does NOT know about OMNISANC specifically.

### 2. DNA (CAVE library - generic data class)

```python
@dataclass
class DNA:
    name: str
    loops: Dict[str, AgentInferenceLoop]  # available loops
    transitions: List[TransitionFn]        # state → loop name functions
```

DNA is pure data. No execution logic. No CAVEAgent reference.

### 3. AgentInferenceLoop (CAVE library - generic)

```python
@dataclass
class AgentInferenceLoop:
    name: str
    description: str
    active_hooks: Dict[str, List[str]]  # which hooks to activate
    # ... other config ...
```

Loops define WHAT hooks to run. They don't run them.

### 4. TransitionFn (CAVE library - type alias)

```python
TransitionFn = Callable[[Dict[str, Any]], Optional[str]]
# Takes state dict, returns loop name (or None)
```

Transition functions are the SMART part - they check state and decide which loop should be active. One transition per hook basically.

### 5. Hooks (CAVE library - Python classes)

```python
class OmnisancHomeHook(ClaudeCodeHook):
    """DUMB hook - just produces a prompt."""

    def __call__(self, payload, state) -> dict:
        mode = state.get("mode", "DAY")
        if mode == "NIGHT":
            return {"additionalContext": NIGHT_PROMPT}
        return {"additionalContext": DAY_PROMPT}
```

Hooks are DUMB. They don't self-select. They just produce output when called. The transition decides WHETHER to call them.

---

## SancRev Implementation

### 6. OMNISANC (SancRev - specific DNA instance)

```python
# In sancrev/dna/omnisanc.py

OMNISANC = DNA(
    name="omnisanc",
    loops={
        "HOME_DAY": OMNISANC_HOME_DAY,
        "HOME_NIGHT": OMNISANC_HOME_NIGHT,
        "STARPORT": OMNISANC_STARPORT,
        "LAUNCH": OMNISANC_LAUNCH,
        "SESSION": OMNISANC_SESSION,
        "LANDING": OMNISANC_LANDING,
    },
    transitions=[
        omnisanc_home_transition,
        omnisanc_starport_transition,
        omnisanc_launch_transition,
        omnisanc_session_transition,
        omnisanc_landing_transition,
    ],
)
```

OMNISANC is a specific DNA instance. It's OUR default configuration.

### 7. SancRevAgent (SancRev - our CAVEAgent subclass)

```python
# In sancrev/agent.py

class SancRevAgent(CAVEAgent):
    def __init__(self, config=None):
        super().__init__(config)
        self.dna = OMNISANC  # plug in our DNA

    def run_impl(self):
        """Override - run OMNISANC workflow."""
        self.run_omnisanc()

    def run_omnisanc(self):
        """THE ACTUAL OMNISANC WORKFLOW LOGIC."""
        while self.dna:
            # 1. Get current state
            state = self.get_omnisanc_state()
            state["mode"] = self.get_paia_mode()  # DAY/NIGHT

            # 2. Run transitions to find current loop
            current_loop = None
            for transition_fn in self.dna.transitions:
                loop_name = transition_fn(state)
                if loop_name:
                    current_loop = self.dna.loops.get(loop_name)
                    break

            if not current_loop:
                continue  # no loop matched

            # 3. Activate that loop's hooks
            self.config.main_agent_config.active_hooks = current_loop.active_hooks

            # 4. Hooks fire through HookRouter when Claude responds
            # ... workflow continues ...
```

---

## Transition Functions (Smart State Checks)

```python
# In sancrev/dna/transitions.py

def omnisanc_home_transition(state: dict) -> Optional[str]:
    """Check if we should be in HOME loop."""
    if not state.get("course_plotted"):
        if state.get("mode") == "NIGHT":
            return "HOME_NIGHT"
        return "HOME_DAY"
    return None  # not HOME

def omnisanc_starport_transition(state: dict) -> Optional[str]:
    """Check if we should be in STARPORT loop."""
    if state.get("course_plotted") and not state.get("fly_called"):
        return "STARPORT"
    return None

def omnisanc_launch_transition(state: dict) -> Optional[str]:
    """Check if we should be in LAUNCH loop."""
    if (state.get("course_plotted") and
        state.get("fly_called") and
        not state.get("flight_selected")):
        return "LAUNCH"
    return None

def omnisanc_session_transition(state: dict) -> Optional[str]:
    """Check if we should be in SESSION loop."""
    if (state.get("flight_selected") and
        state.get("session_active") and
        not state.get("needs_review")):
        return "SESSION"
    return None

def omnisanc_landing_transition(state: dict) -> Optional[str]:
    """Check if we should be in LANDING loop."""
    if state.get("needs_review"):
        return "LANDING"
    return None
```

---

## Where Things Live

| Component | Location | Description |
|-----------|----------|-------------|
| CAVEAgent | CAVE library | Generic base class with infrastructure |
| DNA class | CAVE library | Generic data class for workflow definition |
| AgentInferenceLoop | CAVE library | Generic loop definition |
| Hook base classes | CAVE library | Generic hook infrastructure |
| OMNISANC | SancRev | Specific DNA instance (our default) |
| SancRevAgent | SancRev | Our CAVEAgent subclass with run_omnisanc() |
| Transition functions | SancRev | OMNISANC-specific state checks |
| Zone hooks (impl) | CAVE library | Dumb prompt producers (rewritten from standalone files) |
| Persistent state | Files | .course_state, paia_mode.txt, etc. |

---

## Configurability Model

- **Default**: Everything runs with OMNISANC
- **Override parts of OMNISANC**: Subclass SancRevAgent, override specific methods
- **Replace OMNISANC entirely**: Create new DNA, plug into your own CAVEAgent subclass
- **Hack mode**: Fork and modify directly

```python
# Example: Override just the HOME behavior
class MyAgent(SancRevAgent):
    def __init__(self):
        super().__init__()
        # Replace just the HOME transition
        self.dna.transitions[0] = my_custom_home_transition
```

---

## Hooks Refactor Summary

**Before (HACK):**
- Standalone Python files in `~/.claude/hooks/omnisanc_*.py`
- Each hook reads state files directly
- Each hook self-selects (checks if it should fire)
- Decoupled from CAVE runtime, hard to debug

**After (PROPER):**
- Python classes in CAVE registered in HookRouter
- Hooks are DUMB - just produce prompts
- Transitions are SMART - check state, decide which loop
- CAVEAgent subclass (SancRevAgent) runs the workflow
- Everything unified in one runtime, debuggable
