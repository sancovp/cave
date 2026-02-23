"""ClaudeStateReader - Reads Claude Code state from filesystem.

This is the "sensing" layer of the live mirror. CAVEAgent uses this
to know the current state of Claude Code without needing hooks to report.

Reads:
- ~/.claude/settings.json - global settings
- ~/.claude/projects/{hash}/ - project-specific state
- .claude/ in cwd - local project config
- MCP configs - which MCPs are loaded
- Hook configs - which hooks are active
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import re


@dataclass
class ClaudeStateReader:
    """Reads Claude Code state from filesystem.

    This class provides read-only access to Claude Code's filesystem state.
    It does NOT modify anything - it only observes.
    """

    claude_home: Path = field(default_factory=lambda: Path.home() / ".claude")
    project_dir: Path = field(default_factory=Path.cwd)

    def __post_init__(self):
        """Ensure paths are Path objects."""
        self.claude_home = Path(self.claude_home)
        self.project_dir = Path(self.project_dir)

    # === GLOBAL SETTINGS ===

    def read_settings(self) -> Dict[str, Any]:
        """Read ~/.claude/settings.json - global Claude Code settings."""
        settings_path = self.claude_home / "settings.json"
        if not settings_path.exists():
            return {}
        try:
            return json.loads(settings_path.read_text())
        except (json.JSONDecodeError, IOError):
            return {"_error": "failed to parse settings.json"}

    def read_settings_local(self) -> Dict[str, Any]:
        """Read ~/.claude/settings.local.json - local overrides."""
        settings_path = self.claude_home / "settings.local.json"
        if not settings_path.exists():
            return {}
        try:
            return json.loads(settings_path.read_text())
        except (json.JSONDecodeError, IOError):
            return {"_error": "failed to parse settings.local.json"}

    # === MCP CONFIG ===

    def read_mcp_config(self) -> Dict[str, Any]:
        """Read MCP configuration from multiple sources.

        Claude Code loads MCPs from:
        1. ~/.claude/settings.json mcpServers
        2. ~/.claude/settings.local.json mcpServers (overrides)
        3. .claude/settings.json in project (project-specific)
        """
        result = {
            "global": {},
            "local": {},
            "project": {},
            "active_servers": [],
        }

        # Global MCPs
        settings = self.read_settings()
        result["global"] = settings.get("mcpServers", {})

        # Local overrides
        local_settings = self.read_settings_local()
        result["local"] = local_settings.get("mcpServers", {})

        # Project MCPs
        project_settings_path = self.project_dir / ".claude" / "settings.json"
        if project_settings_path.exists():
            try:
                project_settings = json.loads(project_settings_path.read_text())
                result["project"] = project_settings.get("mcpServers", {})
            except (json.JSONDecodeError, IOError):
                pass

        # Compute active servers (merged)
        all_servers = {}
        all_servers.update(result["global"])
        all_servers.update(result["local"])
        all_servers.update(result["project"])
        result["active_servers"] = list(all_servers.keys())

        return result

    # === PROJECT STATE ===

    def read_project_state(self) -> Dict[str, Any]:
        """Read .claude/ project state in current directory.

        The .claude/ directory contains:
        - settings.json - project-specific settings
        - rules/ - project rules
        - CLAUDE.md - project instructions
        """
        claude_dir = self.project_dir / ".claude"
        result = {
            "exists": claude_dir.exists(),
            "settings": {},
            "rules": [],
            "has_claude_md": False,
        }

        if not claude_dir.exists():
            return result

        # Settings
        settings_path = claude_dir / "settings.json"
        if settings_path.exists():
            try:
                result["settings"] = json.loads(settings_path.read_text())
            except (json.JSONDecodeError, IOError):
                pass

        # Rules
        rules_dir = claude_dir / "rules"
        if rules_dir.exists():
            result["rules"] = [f.name for f in rules_dir.glob("*.md")]

        # CLAUDE.md
        claude_md = self.project_dir / "CLAUDE.md"
        result["has_claude_md"] = claude_md.exists()

        return result

    # === HOOKS ===

    def read_hooks(self) -> Dict[str, Any]:
        """Read active hooks configuration.

        Hooks are defined in settings under "hooks" key.
        """
        result = {
            "global": {},
            "project": {},
            "all_hooks": [],
        }

        # Global hooks
        settings = self.read_settings()
        result["global"] = settings.get("hooks", {})

        # Project hooks
        project_settings = self.read_project_state().get("settings", {})
        result["project"] = project_settings.get("hooks", {})

        # Flatten to list
        all_hooks = set()
        for hook_type, hooks in result["global"].items():
            if isinstance(hooks, list):
                all_hooks.add(hook_type)
        for hook_type, hooks in result["project"].items():
            if isinstance(hooks, list):
                all_hooks.add(hook_type)
        result["all_hooks"] = list(all_hooks)

        return result

    # === GLOBAL RULES ===

    def read_global_rules(self) -> List[str]:
        """Read global rules from ~/.claude/rules/."""
        rules_dir = self.claude_home / "rules"
        if not rules_dir.exists():
            return []
        return [f.name for f in rules_dir.glob("*.md")]

    # === CLAUDE.md (global) ===

    def read_global_claude_md(self) -> Optional[str]:
        """Read global CLAUDE.md content."""
        claude_md = self.claude_home / "CLAUDE.md"
        if not claude_md.exists():
            return None
        try:
            return claude_md.read_text()
        except IOError:
            return None

    # === PLUGINS ===

    def read_plugins(self) -> Dict[str, Any]:
        """Read installed plugins from ~/.claude/plugins/."""
        plugins_dir = self.claude_home / "plugins"
        result = {
            "installed": [],
            "marketplaces": [],
        }

        if not plugins_dir.exists():
            return result

        # Direct plugins
        for item in plugins_dir.iterdir():
            if item.is_dir() and item.name != "marketplaces":
                result["installed"].append(item.name)

        # Marketplace plugins
        marketplaces_dir = plugins_dir / "marketplaces"
        if marketplaces_dir.exists():
            for item in marketplaces_dir.iterdir():
                if item.is_dir():
                    result["marketplaces"].append(item.name)

        return result

    # === SUBAGENTS ===

    def read_subagents(self) -> List[str]:
        """Read custom subagent definitions from settings."""
        settings = self.read_settings()
        agents = settings.get("agents", {})
        return list(agents.keys())

    # === SKILLS ===

    def read_skills_dir(self) -> Dict[str, Any]:
        """Read skills from ~/.claude/skills/.

        Skills are directories containing:
        - SKILL.md - main skill content
        - reference.md - optional reference material
        - scripts/ - optional executable scripts
        - templates/ - optional templates
        """
        skills_dir = self.claude_home / "skills"
        result = {
            "path": str(skills_dir),
            "exists": skills_dir.exists(),
            "skills": [],
        }

        if not skills_dir.exists():
            return result

        for item in skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith((".", "_")):
                skill_info = {
                    "name": item.name,
                    "has_skill_md": (item / "SKILL.md").exists(),
                    "has_reference": (item / "reference.md").exists(),
                    "has_scripts": (item / "scripts").is_dir(),
                    "has_templates": (item / "templates").is_dir(),
                }
                result["skills"].append(skill_info)

        return result

    # === HOOKS DIRECTORY ===

    def read_hooks_dir(self) -> Dict[str, Any]:
        """Read hooks from ~/.claude/hooks/.

        Hooks are Python files that get executed on Claude Code events.
        This reads the actual files, not the config (read_hooks does config).
        """
        hooks_dir = self.claude_home / "hooks"
        result = {
            "path": str(hooks_dir),
            "exists": hooks_dir.exists(),
            "hook_files": [],
        }

        if not hooks_dir.exists():
            return result

        for item in hooks_dir.iterdir():
            if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
                result["hook_files"].append(item.name)

        return result

    # === UNIFIED STATE ===

    def get_complete_state(self) -> Dict[str, Any]:
        """Return complete Claude Code state.

        This is the primary method - gives a full picture of Claude Code config.
        """
        return {
            "settings": self.read_settings(),
            "settings_local": self.read_settings_local(),
            "mcps": self.read_mcp_config(),
            "project": self.read_project_state(),
            "hooks_config": self.read_hooks(),
            "hooks_dir": self.read_hooks_dir(),
            "skills_dir": self.read_skills_dir(),
            "global_rules": self.read_global_rules(),
            "plugins": self.read_plugins(),
            "subagents": self.read_subagents(),
            "paths": {
                "claude_home": str(self.claude_home),
                "project_dir": str(self.project_dir),
            }
        }

    # === CONTEXT WINDOW PARSING ===

    @staticmethod
    def parse_context_pct(pane_output: str) -> Optional[int]:
        """Parse context window percentage from tmux pane output.

        Claude Code shows context usage like: "Context: 45% used"
        This parses that from the captured output.
        """
        # Look for patterns like "Context: 45%" or "45% context"
        patterns = [
            r'Context:\s*(\d+)%',
            r'(\d+)%\s*context',
            r'context.*?(\d+)%',
        ]

        for pattern in patterns:
            match = re.search(pattern, pane_output, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None
