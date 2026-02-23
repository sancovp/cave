# DNA + OMNISANC Architecture

**Date:** 2026-01-26
**Status:** Design discussion, not yet implemented

---

## Layered Architecture

```
PAIAB (the product/offer)
├── CAVE (infra library - generic)
├── PAIA-builder (tools)
├── Frontend
└── OMNISANC (implemented THROUGH CAVE)
```

- **CAVE** = generic AI agent infrastructure (anyone can use)
- **OMNISANC** = our specific DNA implementation (NOT in CAVE library)
- **PAIAB** = bundled product that includes CAVE + OMNISANC + builder + frontend
- **SancRev** = game experience layer on top of PAIAB

---

## What is DNA?

DNA = **a bundle of loops** (data only, no execution logic)

```python
@dataclass
class DNA:
    name: str
    loops: Dict[str, AgentInferenceLoop]
    transitions: TransitionRegistry  # optional
```

---

## What is OMNISANC?

OMNISANC = **a specific DNA bundle** with:
- Loops: HOME, STARPORT, LAUNCH, SESSION, LANDING
- Transitions: omnisanc_home_next, omnisanc_starport_next, etc.
- Hooks: omnisanc_home.py, omnisanc_starport.py, etc. (files, read state)

```python
OMNISANC = DNA(
    name="omnisanc",
    loops=OMNISANC_LOOPS,
    transitions=TRANSITIONS,
)
```

OMNISANC lives OUTSIDE the CAVE library - it's released as part of PAIAB.

---

## CAVEAgent Pattern

CAVEAgent provides hook points, implementations override them:

```python
# CAVE base
class CAVEAgent:
    self.dna: DNA = None  # just data

    def run(self):
        # ... setup ...
        self.run_impl()

    def run_impl(self):
        pass  # Override me

# Your implementation
class MyPAIA(CAVEAgent):
    def __init__(self):
        self.dna = OMNISANC  # plug in the bundle

    def run_omnisanc(self):
        # State machine logic using self.dna.loops, self.dna.transitions
        zone = self.detect_zone()
        next_loop = self.dna.transitions.resolve(zone, self.paia_state)
        self.activate_loop(next_loop)

    def run_impl(self):  # Override
        self.run_omnisanc()
```

---

## Key Principles

1. **Lower pieces are DUMB** - loops, transitions, hooks don't need CAVEAgent reference
2. **CAVEAgent is SMART** - wires everything together
3. **Hooks are independent** - they read `.course_state` files, no Python imports of CAVEAgent
4. **CAVE stays generic** - no OMNISANC code in it
5. **Override pattern** - CAVE provides `run_impl`, you override to wire in your DNA

---

## OMNISANC Zones

```
HOME → STARPORT → LAUNCH → SESSION → LANDING → STARPORT (loop)
 ↑                                              |
 └──────────────────────────────────────────────┘ (clear_course)
```

| Zone | Condition |
|------|-----------|
| HOME | `!course_plotted` + DAY/NIGHT mode |
| STARPORT | `course_plotted && !fly_called` |
| LAUNCH | `fly_called && !flight_selected` |
| SESSION | `flight_selected && session_active` |
| LANDING | `needs_review` (3 sub-phases) |

---

## Current State

**Created (need to move out of CAVE):**
- `/tmp/cave/cave/core/loops/omnisanc_loops.py` - loop definitions
- `/tmp/cave/cave/core/loops/transitions.py` - transition functions
- `~/.claude/hooks/omnisanc_*.py` - hook files

**TODO:**
1. Move OMNISANC code out of `/tmp/cave/` to separate location
2. Refactor CAVEAgent to have `run_impl` override pattern
3. Split AutoModeDNA: data → DNA, execution → run_impl
4. Create OMNISANC bundle that MyPAIA can import and wire up

---

## What AutoModeDNA Becomes

**Current AutoModeDNA** = loops list + execution logic (start, check_and_transition)

**Splits into:**
- **DNA** = just the bundle (data)
- **run_impl override** = execution logic moves to CAVEAgent subclass
