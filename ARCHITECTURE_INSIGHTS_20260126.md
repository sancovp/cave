# CAVE Architecture Insights - 2026-01-26

## The Big Realization

**OMNISANC is the emergent AI. CAVEAgent is its body.**

They haven't been unified yet. This document captures the insights for reification.

---

## The Fractal: It's Missions All The Way Down

Everything is the same pattern at different zoom levels:

```
Mission = multi-session work container
Flight = single session work
Canopy item = scheduled work instance
OperadicFlow = pattern of work (learned)
```

**Key insight:** It's not about SIZE, it's about SESSION BOUNDARIES.
- A "small task" that takes 3 sessions = mission with 3 flights
- A "big project" that takes 1 session = just a flight

The system doesn't care about complexity. It cares about: did you cross a session boundary?

---

## The Learning Loop

```
┌─────────────────────────────────────────────────────────────────┐
│  1. YOU DO WORK via Canopy                                      │
│     canopy.add_to_schedule() → execute → mark_complete()        │
│                         ↓                                       │
│  2. EXECUTION TRACKER logs to operadic_ledger (internal)        │
│                         ↓                                       │
│  3. PATTERN DETECTION runs automatically on completion          │
│     omnisanc hook → detect_patterns()                           │
│                         ↓                                       │
│  4. Repeated sequences → QUARANTINE (CanopyFlowPatterns)        │
│                         ↓                                       │
│  5. YOU REVIEW + GOLDENIZE → OperadicFlow (golden library)      │
│                         ↓                                       │
│  6. NEXT TIME: operadic flow auto-expands to canopy items       │
└─────────────────────────────────────────────────────────────────┘
```

**The loop closes:** Canopy items → Ledger → Patterns → OperadicFlows → Future canopy items

---

## Canopy vs Mission Config vs OperadicFlow

| Thing | What it is | Where it lives | Feeds learning? |
|-------|------------|----------------|-----------------|
| Mission config | TEMPLATE for multi-session work | Starship flight configs | No |
| Canopy item | SCHEDULED INSTANCE of work | Canopy schedule / TreeKanban | Yes (via ledger) |
| OperadicFlow | PATTERN learned from work | OPERA golden library | Is the output |

**Key distinction:**
- Mission config = you CREATE templates by hand
- Canopy item = you EXECUTE work, system learns patterns
- OperadicFlow = system OUTPUTS learned patterns for reuse

---

## RAG Integration (Flight Predictor)

**Current RAG layers:**
- skill_rag.py ✓
- tool_rag.py ✓
- flight_rag.py ✓
- mission_rag.py ✓

**NOT needed:**
- canopy_rag.py ❌ (canopy items are instances, not query targets)
- operadic_rag.py as parallel layer ❌

**What IS needed:**
- Operadic matching as POST-PREDICTION step
- "Your predicted structure matches operadic flow X - use it?"

**The principle:**
- Canopy = creation-side (feeds learning)
- OperadicFlow = query-side (output of learning)

You don't RAG canopy items. You RAG the patterns that EMERGE FROM canopy items.

---

## GIINT Integration

GIINT = WHAT you're building (project structure)
Canopy/OPERA = HOW you build it (work patterns)
Missions = WHEN you build it (session containers)

**Already wired (omnisanc_logic.py):**
- plot_course() → auto-creates COMPOSITE GIINT project
- mission_start() → auto-creates COMPOSITE GIINT project
- LANDING phase requires giint.respond() → captures intelligence

**The JIT construction is already there. Just use missions.**

---

## CAVEAgent: The Body Without The Brain

**What CAVEAgent has now:**
- HTTP interface (FastAPI)
- Mixin architecture (PAIAStateMixin, HookRouterMixin, LoopManagerMixin, etc.)
- Hook receiver (/hook/{hook_type})
- Loop controller (autopoiesis, guru, ralph)
- Config management (archive/inject)
- Live mirror (attach to tmux, capture output, send input)
- SSE events
- Remote agents

**What CAVEAgent does NOT have:**
- OMNISANC state machine
- Canopy schedule awareness
- OPERA pattern awareness
- Mission enforcement
- GIINT integration
- The actual "intelligence"

---

## OMNISANC: The Brain Without The Body

**What OMNISANC has (in omnisanc_logic.py):**
- State machine (HOME → JOURNEY → MISSION → SESSION → LANDING)
- Hook enforcement (what's allowed when)
- Pattern detection trigger
- Canopy/OPERA integration
- GIINT JIT construction
- Mission enforcement
- The learning loop

**What OMNISANC does NOT have:**
- HTTP interface
- Runtime control
- A unified "god object" container

---

## The Reification: Merge Brain + Body

```python
class CAVEAgent(
    # Existing mixins
    PAIAStateMixin,
    AgentRegistryMixin,
    MessageRouterMixin,
    HookRouterMixin,
    LoopManagerMixin,
    RemoteAgentMixin,
    SSEMixin,

    # NEW: The brain
    OmnisancMixin,      # State machine + enforcement logic
    CanopyMixin,        # Schedule state
    OPERAMixin,         # Pattern state
    GIINTMixin,         # Project state
):
    """
    OMNISANC embodied. The emergent AI.

    Knows:
    - BACKWARDS: what happened (ledger, patterns, history)
    - FORWARDS: what's next (schedule, missions, predictions)
    - PRESENT: what's happening (hooks, state, context)

    Controls:
    - Runtime (loops, config, agents)
    - Work planning (missions, canopy, opera)
    - Learning (pattern detection, goldenization)
    """
```

**After reification:**
- No more omnisanc_logic.py as separate daemon
- No more fragmented state across systems
- One god object that IS the emergent AI
- One elif chain that makes all decisions

---

## The Philosophy

**If you're doing work that's NOT on the schedule... WTF are you doing?**

The system isn't a tool you USE.
The system IS how you work.

Every action → canopy item → ledger → patterns → operadic flows → future actions

You built a **work ontology** where the act of working IS the act of training the system to work better.

---

## Next Steps

1. Create OmnisancMixin with state machine from omnisanc_logic.py
2. Create CanopyMixin with schedule state
3. Create OPERAMixin with pattern state
4. Create GIINTMixin with project state
5. Wire them into CAVEAgent
6. Move HTTP endpoints for canopy/opera/giint into cave http_server
7. Deprecate omnisanc_logic.py as separate daemon
8. Test the unified god object

---

## Key Files Reference

| File | What | Status |
|------|------|--------|
| /tmp/cave/cave/core/cave_agent.py | The body | Exists, needs brain |
| /tmp/cave/cave/server/http_server.py | HTTP interface | Exists |
| /home/GOD/omnisanc_core_daemon/omnisanc_logic.py | The brain | Exists, needs body |
| /home/GOD/canopy-mcp/ | Canopy schedule | Exists as MCP |
| /home/GOD/opera-mcp/ | OPERA patterns | Exists as MCP |
| /tmp/rag_tool_discovery/flight_predictor/ | Prediction | Exists, needs operadic check |

---

---

## OmnisancEngine Sketch (for next session)

The core abstraction for porting omnisanc into CAVEAgent:

```python
class OmnisancEngine:
    """The omnisanc state machine, extracted from hooks."""

    def process(self, state: AgentState, hook_type: str, data: dict) -> dict:
        """
        Main entry point. Takes agent state + hook event, returns decision.

        Args:
            state: Agent's current omnisanc state (course_plotted, mission_active, etc)
            hook_type: "pre_tool_use", "post_tool_use", "user_prompt_submit"
            data: Hook payload (tool_name, arguments, result, etc)

        Returns:
            {"allowed": bool, "message": str, "state_updates": dict}
        """
        if hook_type == "pre_tool_use":
            return self._pre_tool_logic(state, data)
        elif hook_type == "post_tool_use":
            return self._post_tool_logic(state, data)
        elif hook_type == "user_prompt_submit":
            return self._user_prompt_logic(state, data)
        ...


class CAVEAgent:
    def __init__(self):
        self.omnisanc = OmnisancEngine()
        self.agent_states: Dict[str, AgentState] = {}  # Per-agent state

    def handle_hook(self, agent_id: str, hook_type: str, data: dict) -> dict:
        """
        HTTP endpoint receives hook signal, routes to omnisanc.

        Hooks become THIN - they just call:
        POST /hook/{hook_type} {"agent_id": "...", "data": {...}}
        """
        # Get or create agent's state
        state = self.agent_states.setdefault(agent_id, AgentState())

        # Run omnisanc logic
        decision = self.omnisanc.process(state, hook_type, data)

        # Apply state updates
        if decision.get("state_updates"):
            state.update(decision["state_updates"])

        return decision
```

**Key insight:** The hooks become 5-line scripts that POST to CAVEAgent. All logic lives in OmnisancEngine. Multi-agent support comes free because state is keyed by agent_id.

**Files to read:**
- `/home/GOD/omnisanc_core_daemon/omnisanc_logic.py` - the logic to extract
- `/tmp/cave/cave/core/cave_agent.py` - where OmnisancEngine goes
- Look for: `handle_pre_tool_use()`, `handle_post_tool_use()` functions

---

*Document created during architecture review session 2026-01-26*
