# SESSION HANDOFF - 2026-01-21 (FINAL)

## CRITICAL GAP IDENTIFIED

**CAVE is NOT importing PAIAB models.** Built totally separate stuff.

Should be using existing types from PAIAB:
- ClaudeCodeHook
- MCP models
- etc.

## KEY INSIGHT FROM THIS SESSION

**USE EXISTING SDNA TYPES - DON'T INVENT NEW NAMES:**
- Ariadne IS Ariadne (not "HookAriadne", not "continue_prompt")
- HermesConfig IS HermesConfig
- SDNAC IS SDNAC
- Chains of chains of chains

**CodeAgentSDNAC typing:**
- Ariadne = hooks that return context
- HermesConfig = prompt sent on stop/continue
- Poimandres = tmux capture (agent result)

**DNA model:**
```
DNA = {
    "auto": SDNAFlow of SDNACs (runs on true stop, continues agent)
    "manual": config for human-driven mode
}
```

## NEXT SESSION MUST

1. **Check PAIAB for existing models** - ClaudeCodeHook, etc.
2. **CAVE should IMPORT those** - not reinvent
3. **Apply SDNA types directly** - AriadneChain, HermesConfig, SDNAC
4. **No new names** - use what exists

## FILES CREATED (may need rework)

- `/tmp/sdna-repo/sdna/code_agent.py` - might be redundant if PAIAB has this
- `/tmp/cave/cave/core/loops/` - needs to use proper types

## PRODUCT VISION (still valid)

CAVE = complete product with:
- Hooks + Loops defined in code (using SDNA types)
- Electron app + Docker
- Can spawn agent networks
