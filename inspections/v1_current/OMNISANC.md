# OMNISANC Logic Reference

Core enforcement logic for HOME/JOURNEY state machine. Validates tool usage based on navigation state.

## State File

**Location:** `/tmp/heaven_data/omnisanc_core/.course_state`

| Key | Type | Description |
|-----|------|-------------|
| `course_plotted` | bool | In JOURNEY mode |
| `projects` | list | Active project paths |
| `description` | str | Course description |
| `domain` | str | STARPORT categorization |
| `subdomain` | str | STARPORT sub-category |
| `process` | str | Specific process |
| `fly_called` | bool | Browsed flights |
| `flight_selected` | bool | Started waypoint journey |
| `waypoint_step` | int | Current waypoint (1-4) |
| `session_active` | bool | STARLOG session running |
| `session_shielded` | bool | Protect against auto-end |
| `session_end_shield_count` | int | Shield uses remaining |
| `mission_active` | bool | In formal mission |
| `mission_id` | str | Current mission ID |
| `mission_step` | int | Mission session index |
| `needs_review` | bool | LANDING phase active |
| `landing_routine_called` | bool | LANDING step 1 done |
| `session_review_called` | bool | LANDING step 2 done |
| `giint_respond_called` | bool | LANDING step 3 done |
| `was_compacted` | bool | Conversation compacted |
| `continue_course_called` | bool | Awaiting orient() |
| `qa_id` | str | QA tracking ID |

## Modes and Phases

```
HOME ─────────────────────────────────────────────────────────────────
  │ plot_course()
  ▼
JOURNEY ──────────────────────────────────────────────────────────────
  │
  ├─► STARPORT (course_plotted=true, fly_called=false)
  │     │ fly()
  │     ▼
  ├─► LAUNCH (fly_called=true, flight_selected=false)
  │     │ start_waypoint_journey()
  │     ▼
  ├─► SESSION (flight_selected=true, session_active=true)
  │     │ waypoint_step 1-4: check → orient → start_starlog → work
  │     │ end_starlog()
  │     ▼
  ├─► LANDING (needs_review=true) [3-step sequence]
  │     │ 1. landing_routine()
  │     │ 2. session_review()
  │     │ 3. giint.respond()
  │     ▼
  └─► MISSION (mission_active=true, session_active=false)
        │ start next session OR request_extraction()
        ▼
      HOME
```

## Tool Allowlists

### HOME_MODE_TOOLS (no course plotted)

| Category | Tools |
|----------|-------|
| Read/Search | `Read`, `Glob`, `Grep`, `Bash` (mkdir/cd/ls/pwd only) |
| Navigation | `starship.plot_course`, `starship.launch_routine` |
| Identity | `seed.home`, `seed.who_am_i`, `seed.what_do_i_do`, `seed.how_do_i` |
| Mission Mgmt | `STARSYSTEM.mission_*` (create, start, get_status, list, request_extraction, view_mission_config, complete_mission) |
| GIINT Planning | `giint.planning.*` (create_project, add_feature, add_component, add_deliverable, add_task) |
| Canopy/OPERA | `canopy.*`, `opera.*` (scheduling and pattern management) |
| Observability | `STARSYSTEM.check_selfplay_logs`, `STARSYSTEM.get_fitness_score`, `STARSYSTEM.toggle_omnisanc` |
| Registry | `heaven-framework-toolbox.registry_tool`, `heaven-framework-toolbox.matryoshka_registry_tool` |
| Escape Hatch | `heaven-framework-toolbox.network_edit_tool` |
| Status | `waypoint.get_waypoint_progress`, `waypoint.abort_waypoint_journey`, `starship.get_course_state` |
| Knowledge | `carton.*` (get_recent_concepts, query_wiki_graph, get_concept, get_concept_network) |
| Context | `toot.*` (create/update/explain train of thought) |

### Always Whitelisted

- `gnosys_kit` meta-tools: `discover_server_actions`, `get_action_details`, `search_documentation`, `manage_servers`, `execute_action`, `search_mcp_catalog`
- TreeShell tools: `gnosys_kit.run_conversation_shell`, `skill_manager_treeshell.run_conversation_shell`
- `STARSYSTEM.toggle_omnisanc` (escape hatch)

### Bash Escape Hatch

```bash
rm /tmp/heaven_data/omnisanc_core/.course_state      # Reset to HOME
rm -f /tmp/heaven_data/omnisanc_core/.course_state   # Force reset
```

## Key Functions

| Function | Purpose |
|----------|---------|
| `get_course_state()` | Load state from JSON file |
| `save_course_state(state)` | Persist state to JSON file |
| `validate_home_mode(tool, args)` | Check tool allowed in HOME |
| `validate_journey_mode(tool, state)` | Check tool allowed in JOURNEY (phase-aware) |
| `on_tool_use(tool, args)` | PreToolUse hook entry point |
| `on_tool_result(tool, args, result)` | PostToolUse hook entry point |
| `is_base_mission(state)` | Check if implicit single-session mission |
| `is_safe_bash_command(args)` | Validate bash for HOME mode |
| `log_event(mode, tool, args, allowed, reason)` | Log to matryoshka registry |
| `ensure_event_registry(name)` | Create/ensure daily event registry layer |

## Kill Switch

Create `/tmp/heaven_data/omnisanc_core/.omnisanc_disabled` to bypass all validation.

## PostToolUse Handlers

| Tool | Action |
|------|--------|
| `plot_course` | Set course_plotted=true, store projects/domain/subdomain |
| `fly` | Set fly_called=true |
| `start_waypoint_journey` | Set flight_selected=true, waypoint_step=1 |
| `end_starlog` | Clear session, enter LANDING (or HOME for base_mission) |
| `landing_routine` | Set landing_routine_called=true |
| `session_review` | Set session_review_called=true |
| `giint.respond` | Exit LANDING, clear review flags |
| `mission_start` | Set mission_active=true, course_plotted=true |
| `mission_request_extraction` | Pause mission, return to HOME |
| `complete_mission` | Clear all state, return to HOME |

## Integration Hooks

- **GIINT-Carton sync**: Dual-write GIINT planning to Carton knowledge graph
- **GIINT-TreeKanban sync**: Push deliverables/tasks to TreeKanban board
- **Canopy/OPERA**: Pattern detection after completion, auto-feed from OPERA
- **Session/Mission scoring**: Compute rewards after end_starlog/extraction
