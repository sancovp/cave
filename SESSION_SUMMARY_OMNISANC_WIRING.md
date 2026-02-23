# Session Summary: CAVE OMNISANC Wiring

**Date:** 2026-01-26

## What Was Done

### 1. Wired `run_omnisanc()` to HTTP server
**File:** `/tmp/cave/cave/server/http_server.py:213`

Added `cave.run_omnisanc()` call before `handle_hook()` in `/hook/{hook_type}` endpoint. Now zone detection + active_hooks update happens on every hook signal.

### 2. Fixed Stop hook output formats

**`~/.claude/hooks/omnisanc_home.py`:**
- Changed from `{"continue": True, "additional_context": ...}` to `{"decision": "block", "reason": ...}`
- Changed all `{"continue": True}` to `{"decision": "approve"}`

**`~/.claude/hooks/metabrainhook.py`:**
- Changed from `{"stopMessage": ...}` to `{"decision": "block", "reason": ...}`

**Key insight:** Stop hooks ONLY inject context when they BLOCK with a reason. The correct pattern (from autopoiesis_stop_hook.py) is `{"decision": "block", "reason": "<prompt>"}`.

### 3. Turned off metabrainhook
Was firing because `/tmp/metabrainhook_state.txt` said "on".

---

## Architecture Understanding

### The Flow (how it SHOULD work):
```
Claude Stop event → paia_stop.py → POST /hook/stop
    → run_omnisanc() sets active_hooks based on zone
    → handle_hook() filters registry hooks by active_hooks
    → Hook returns BLOCK with reason
    → paia_stop.py outputs block to Claude
```

### Current Reality (still broken):
- Standalone hooks (`omnisanc_home.py`, `metabrainhook.py`) self-select based on state files
- They don't check CAVE's `active_hooks`
- CAVE's HookRegistry (`/tmp/heaven_data/cave_hooks/`) is separate from Claude Code's `settings.local.json` hooks

---

## What's Still Needed

1. **Connect standalone hooks to CAVE control** - Either:
   - Have each hook call CAVE to check if it should fire, OR
   - Move hook logic into CAVE registry, remove from settings.local.json

2. **CAVE registry hooks** - `/tmp/heaven_data/cave_hooks/` needs omnisanc hooks that match names used by `run_omnisanc()`:
   - `omnisanc_home_day`
   - `omnisanc_home_night`
   - `omnisanc_starport`
   - `omnisanc_launch`
   - `omnisanc_session`
   - `omnisanc_landing`
   - `metabrainhook`

3. **paia_stop.py is the bridge** - Already calls CAVE, but CAVE needs proper hooks in registry

---

## Key Files

| File | Purpose |
|------|---------|
| `/tmp/cave/cave/core/cave_agent.py` | `run_omnisanc()` method (lines 235-304) |
| `/tmp/cave/cave/server/http_server.py` | Hook endpoint with run_omnisanc call |
| `/tmp/cave/cave/core/mixins/hook_router.py` | `handle_hook()` respects `active_hooks` |
| `~/.claude/hooks/omnisanc_home.py` | Fixed output format |
| `~/.claude/hooks/metabrainhook.py` | Fixed output format |
| `~/.claude/hooks/paia_stop.py` | Bridge to CAVE |
| `~/.claude/plugins/.../autopoiesis_stop_hook.py` | Reference - correct Stop hook pattern |

---

## run_omnisanc() Logic (cave_agent.py)

```python
def run_omnisanc(self) -> Dict[str, Any]:
    if not self.is_omnisanc_enabled():
        return {"status": "disabled", "active_hooks": []}

    state = self.get_omnisanc_state()
    mode = self.get_paia_mode()  # DAY or NIGHT
    is_autonomous = mode == "NIGHT"

    active = []
    zone = "HOME"

    if not state.get("course_plotted"):
        zone = "HOME"
        if is_autonomous:  # HOME AND autonomous
            active.append("metabrainhook")
            active.append("omnisanc_home_night")
        else:
            active.append("omnisanc_home_day")
    elif state.get("needs_review"):
        zone = "LANDING"
        active.append("omnisanc_landing")
    elif state.get("flight_selected") or state.get("session_active"):
        zone = "SESSION"
        active.append("omnisanc_session")
    elif state.get("fly_called"):
        zone = "LAUNCH"
        active.append("omnisanc_launch")
    else:
        zone = "STARPORT"
        active.append("omnisanc_starport")

    self.config.main_agent_config.active_hooks = {"stop": active}
    return {"status": "active", "zone": zone, "mode": mode, "active_hooks": active}
```
