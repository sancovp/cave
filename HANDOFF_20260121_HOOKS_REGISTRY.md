# SESSION HANDOFF - 2026-01-21 (HookRegistry)

## COMPLETED THIS SESSION

### HookRegistry System
**File:** `/tmp/cave/cave/core/hooks.py`

Created proper registry:
- `HookRegistry` class - indexes `cave_hooks/` directory
- `RegistryEntry` dataclass - path, hook_type, hook_class, instance
- `scan()` - scans directory, returns summary
- `get_hooks_for_type(hook_type)` - returns cached hook instances
- `list()` - returns registry state

### HookRouterMixin Updated
**File:** `/tmp/cave/cave/core/mixins/hook_router.py`

- Creates `HookRegistry` on `_init_hook_router()`
- `handle_hook()` now uses registry instead of empty handlers dict
- Added `scan_hooks()` and `list_hooks()` methods
- `get_hook_status()` now includes registry + enabled state

### HTTP Endpoints Added
**File:** `/tmp/cave/cave/server/http_server.py`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/hook/{hook_type}` | POST | Receive hook signal |
| `/hooks/scan` | POST | Rescan directory |
| `/hooks` | GET | List registry |
| `/hooks/status` | GET | Full status |

### Loops Rewritten (No SDNA)
**Files:** `base.py`, `autopoiesis.py`, `guru.py`

Removed all SDNA dependencies. Now use:
- `hook_classes` - list of ClaudeCodeHook classes
- `activate(registry)` - enables hooks, writes temp files, scans
- `deactivate(registry)` - disables hooks, removes files

## THE FLOW NOW

```
1. CAVE starts → _init_hook_router() → registry.scan()
2. User puts hook.py in cave_hooks/ defining ClaudeCodeHook subclass
3. POST /hooks/scan → registry reloads
4. Hook fires → handle_hook() → HookControl check → registry.get_hooks_for_type() → run
5. Return result to Claude Code
```

## FILES CHANGED

| File | Change |
|------|--------|
| `hooks.py` | Added HookRegistry, RegistryEntry |
| `hook_router.py` | Uses registry, added scan/list |
| `http_server.py` | Added /hooks endpoints |
| `base.py` | Rewrote AgentInferenceLoop (no SDNA) |
| `autopoiesis.py` | Rewrote with ClaudeCodeHook classes |
| `guru.py` | Rewrote with ClaudeCodeHook classes |
| `__init__.py` | Added RegistryEntry export |

## TESTED

```bash
# Registry scan works
python -c "from cave import HookRegistry; r = HookRegistry(); print(r.scan())"

# Full import works
python -c "from cave import CAVEAgent, HookRegistry; print('OK')"
```

## READY TO TEST END-TO-END

**Blocking hook created:** `/tmp/heaven_data/cave_hooks/test_block_stop.py`

**To test LIVE on Claude:**

1. Kill whatever's on 8080: `lsof -i :8080 | awk 'NR>1 {print $2}' | xargs kill`
2. Start CAVE: `cd /tmp/cave && python -m cave.server.http_server --port 8080`
3. Verify: `curl http://localhost:8080/hooks` → should show test_block_stop
4. Enable stop: `echo '{"stop": true}' > /tmp/hook_config.json`
5. Try to stop Claude → should be BLOCKED with "TEST" message
6. Disable: `echo '{"stop": false}' > /tmp/hook_config.json`
7. Try to stop → should work

**Relay scripts exist:** `~/.claude/hooks/paia_stop.py` posts to CAVE

**Config fixed:** `hook_dir` now uses `HEAVEN_DATA_DIR/cave_hooks`
