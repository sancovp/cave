# Session Summary: CAVE OMNISANC Alignment (v2)

**Date:** 2026-01-27

## What Was Done This Session

### 1. Added backwards-compatible script registration to HookRegistry
**File:** `/tmp/cave/cave/core/hooks.py`

- Added `ScriptHookAdapter` class - wraps scripts with `main()` to be callable like ClaudeCodeHook
- Added `register_script(name, hook_type, path)` - register any script
- Added `load_scripts_config()` / `save_scripts_config()` - JSON persistence
- Modified `get_hooks_for_type()` to return both class hooks AND script hooks

### 2. Created scripts.json registry
**File:** `/tmp/heaven_data/cave_hooks/scripts.json`

```json
{
  "omnisanc_home_day": {"hook_type": "stop", "path": "~/.claude/hooks/omnisanc_home.py"},
  "omnisanc_home_night": {"hook_type": "stop", "path": "~/.claude/hooks/omnisanc_home.py"},
  "metabrainhook": {"hook_type": "stop", "path": "~/.claude/hooks/metabrainhook.py"},
  "omnisanc_router_pretooluse": {"hook_type": "pretooluse", "path": "~/.claude/hooks/omnisanc_router.py"},
  "omnisanc_router_posttooluse": {"hook_type": "posttooluse", "path": "~/.claude/hooks/omnisanc_router.py"}
}
```

### 3. Updated run_omnisanc() to set all hook types
**File:** `/tmp/cave/cave/core/cave_agent.py:278`

```python
self.config.main_agent_config.active_hooks = {
    "stop": active,  # zone-specific stop hooks
    "pretooluse": ["omnisanc_router_pretooluse"],
    "posttooluse": ["omnisanc_router_posttooluse"],
}
```

### 4. Cleaned settings.local.json
Removed from Claude Code hooks (now controlled by CAVE):
- `omnisanc_home.py` (Stop)
- `metabrainhook.py` (Stop)
- `omnisanc_router.py` (PreToolUse)
- `omnisanc_router.py` (PostToolUse)

Kept `paia_*` hooks as bridges to CAVE.

---

## Architecture (Now Aligned)

```
Claude Code hooks (settings.local.json):
  └── paia_* only (bridges to CAVE)

CAVE registry (scripts.json):
  └── everything else (omnisanc_home, metabrainhook, omnisanc_router)

Flow:
  Claude event → paia_*.py → CAVE /hook/{type}
    → run_omnisanc() sets active_hooks
    → handle_hook() calls registered scripts based on active_hooks
```

---

## Key Files

| File | Purpose |
|------|---------|
| `/tmp/cave/cave/core/hooks.py` | ScriptHookAdapter, register_script, load/save config |
| `/tmp/cave/cave/core/cave_agent.py` | run_omnisanc() with all hook types |
| `/tmp/cave/cave/core/mixins/hook_router.py` | Loads scripts.json on init |
| `/tmp/heaven_data/cave_hooks/scripts.json` | Script registry (agent-editable) |
| `~/.claude/settings.local.json` | Only paia_* hooks remain |

---

## What's Next

1. **Test the flow** - trigger a Stop hook and verify CAVE controls it
2. **Create prompt files** for HOME modes
3. **Set up canopy integration** for DAY+AUTO work tasks

---

## Added: AUTO/MANUAL Mode (2026-01-27)

### Two Flags Now
| | MANUAL | AUTO |
|------|--------|------|
| **DAY** | User driving (no hooks) | Canopy work tasks |
| **NIGHT** | (rare) | Maintenance mode |

### Files
- `/tmp/heaven_data/paia_mode.txt` → DAY or NIGHT
- `/tmp/heaven_data/paia_auto.txt` → AUTO or MANUAL

### Endpoints
- `GET /paia/mode` → returns both mode and auto
- `POST /paia/mode` → `{"mode": "DAY"}` or `{"mode": "NIGHT"}`
- `POST /paia/auto` → `{"mode": "AUTO"}` or `{"mode": "MANUAL"}`

### Logic in run_omnisanc()
```python
if HOME zone:
    if AUTO:
        if NIGHT: metabrainhook + omnisanc_home_night
        else: omnisanc_home_day (DAY + AUTO)
    else: # MANUAL
        no HOME hooks (user driving)
```

### scripts.json Updated
- Points to `omnisanc_home_v2.py` (has DAY/NIGHT awareness)
