# SESSION HANDOFF - 2026-01-21 (HOOKS)

## COMPLETED THIS SESSION

### ClaudeCodeHook in CAVE
**File:** `/tmp/cave/cave/core/hooks.py`

Created proper hook system:
- `ClaudeCodeHook` - base class for coded hooks
- `HookType` - enum (PreToolUse, PostToolUse, Stop, etc.)
- `HookDecision` - enum (approve, block, continue)
- `HookResult` - dataclass for hook responses
- `HookRegistry` - manages registered hooks

Concrete hooks:
- `Brainhook` - real brainhook logic as a class
- `AutopoiesisStopHook` - blocks until promise completed
- `ContextReminderHook` - injects context on pretool

### SDNA Cleanup
Removed broken `code_agent.py` from SDNA exports. That code was wrong - hooks belong in CAVE, not SDNA.

## KEY INSIGHT (finally understood)

**SDNA types are for LLM interactions:**
- Ariadne = INPUT to LLM (what model sees)
- Poimandres = OUTPUT from LLM (what model generates)
- SDNAC = Ariadne → HermesConfig → Poimandres

**Hooks are CAVE-specific:**
- Hook receives signal from Claude Code (via HTTP relay)
- Hook returns decision (approve/block/continue + context)
- Hooks are Python classes in CAVE, not SDNA types

**The hook script flow:**
```
Claude Code → paia_*.py (relay) → HTTP to CAVE → ClaudeCodeHook.handle() → response
```

## STILL TODO

1. **Update loops/base.py** - remove broken CodeAgentSDNAC import
2. **Wire `run_hooks()` into HTTP server** - call it when hook signal received
3. **Create example hook** in `HEAVEN_DATA_DIR/cave_hooks/` to test
4. **Test end-to-end** - hook signal through HTTP to ClaudeCodeHook

## HOW IT WORKS NOW

1. Put hook `.py` file in `HEAVEN_DATA_DIR/cave_hooks/`
2. File defines a `ClaudeCodeHook` subclass with `hook_type`
3. When hook fires, `run_hooks(hook_type, payload, state)` dynamically imports matching hooks
4. Each hook's `handle()` is called, results combined

## FILES CHANGED

| File | Change |
|------|--------|
| `/tmp/cave/cave/core/hooks.py` | NEW - ClaudeCodeHook system |
| `/tmp/cave/cave/__init__.py` | Added hook exports |
| `/tmp/sdna-repo/sdna/__init__.py` | Removed broken code_agent exports |

## BROKEN FILE TO DELETE

`/tmp/sdna-repo/sdna/code_agent.py` - still exists but not exported. Can delete.
