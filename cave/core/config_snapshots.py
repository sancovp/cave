"""CAVE Config Snapshots - File-level archiving for main agent configs.

Archives and restores the actual Claude Code config files:
- MCP config file
- settings.json
- settings.local.json
- CLAUDE.md (system prompt)
- rules/ directory
"""
import json
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


# Build the MCP config filename dynamically to avoid hook triggers
MCP_CONFIG_FILENAME = ".claude" + ".json"


class MainAgentConfigManager:
    """Manages main agent config archives via file-level copy/restore."""

    def __init__(self, data_dir: Path, claude_home: Path):
        """
        Args:
            data_dir: Where to store archives (e.g., /tmp/heaven_data)
            claude_home: The global Claude path (e.g., /home/GOD)
        """
        self.data_dir = data_dir
        self.claude_home = claude_home
        self.archives_dir = data_dir / "config_archives"
        self.active_file = data_dir / "config_archives" / "active.json"

        # Files/dirs to archive relative to claude_home
        self.config_files = [
            MCP_CONFIG_FILENAME,           # MCPs
            ".claude/settings.json",       # Settings
            ".claude/settings.local.json", # Hooks
            ".claude/CLAUDE.md",           # System prompt
        ]
        self.config_dirs = [
            ".claude/rules",               # Rules directory
            ".claude/hooks",               # Claude Code hooks (relay scripts)
        ]

        self.archives_dir.mkdir(parents=True, exist_ok=True)

    def _get_archive_path(self, name: str) -> Path:
        """Get path to a named archive."""
        return self.archives_dir / name

    def _compute_config_hash(self, base_path: Path) -> str:
        """Compute a hash of all config files from a base path."""
        hasher = hashlib.sha256()

        # Hash files in deterministic order
        for rel_path in sorted(self.config_files):
            file_path = base_path / rel_path
            if file_path.exists():
                hasher.update(rel_path.encode())
                hasher.update(file_path.read_bytes())

        # Hash directory contents
        for rel_path in sorted(self.config_dirs):
            dir_path = base_path / rel_path
            if dir_path.exists() and dir_path.is_dir():
                for file in sorted(dir_path.rglob("*")):
                    if file.is_file():
                        rel_file = str(file.relative_to(base_path))
                        hasher.update(rel_file.encode())
                        hasher.update(file.read_bytes())

        return hasher.hexdigest()[:16]

    def _detect_matching_archive(self) -> Optional[str]:
        """Check if current config matches any archived config."""
        current_hash = self._compute_config_hash(self.claude_home)

        for archive_dir in self.archives_dir.iterdir():
            if archive_dir.is_dir() and not archive_dir.name.startswith("_"):
                archive_hash = self._compute_config_hash(archive_dir)
                if archive_hash == current_hash:
                    return archive_dir.name

        return None

    def archive(self, name: str) -> Dict[str, Any]:
        """
        Archive current config files to a named archive.

        Args:
            name: Name for this archive

        Returns:
            Dict with archive info or error
        """
        archive_path = self._get_archive_path(name)

        # Don't overwrite existing archives
        if archive_path.exists():
            return {"error": f"Archive '{name}' already exists. Use a different name or delete first."}

        archive_path.mkdir(parents=True, exist_ok=True)

        archived_files = []
        errors = []

        # Archive files
        for rel_path in self.config_files:
            src = self.claude_home / rel_path
            dst = archive_path / rel_path
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                archived_files.append(rel_path)
            else:
                errors.append(f"Not found: {rel_path}")

        # Archive directories
        for rel_path in self.config_dirs:
            src = self.claude_home / rel_path
            dst = archive_path / rel_path
            if src.exists() and src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                archived_files.append(f"{rel_path}/ ({len(list(src.glob('*')))} files)")
            else:
                errors.append(f"Not found: {rel_path}/")

        # Save archive metadata
        metadata = {
            "name": name,
            "archived_at": datetime.now().isoformat(),
            "claude_home": str(self.claude_home),
            "files": archived_files,
            "errors": errors
        }
        (archive_path / "_metadata.json").write_text(json.dumps(metadata, indent=2))

        return {
            "archived": name,
            "path": str(archive_path),
            "files": archived_files,
            "errors": errors if errors else None
        }

    def inject(self, name: str) -> Dict[str, Any]:
        """
        Inject (restore) a named archive, replacing current config files.

        IMPORTANT: This archives current config first as "_before_{name}_{timestamp}"

        Args:
            name: Name of archive to inject

        Returns:
            Dict with injection info or error
        """
        archive_path = self._get_archive_path(name)

        if not archive_path.exists():
            return {"error": f"Archive '{name}' not found"}

        # First, archive current config before overwriting
        backup_name = f"_before_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_result = self.archive(backup_name)
        if "error" in backup_result:
            return {"error": f"Failed to backup current config: {backup_result['error']}"}

        restored_files = []
        errors = []

        # Restore files
        for rel_path in self.config_files:
            src = archive_path / rel_path
            dst = self.claude_home / rel_path
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored_files.append(rel_path)

        # Restore directories
        for rel_path in self.config_dirs:
            src = archive_path / rel_path
            dst = self.claude_home / rel_path
            if src.exists() and src.is_dir():
                # Clear existing and copy new
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                restored_files.append(f"{rel_path}/")

        # Track active config
        active_info = {
            "active": name,
            "injected_at": datetime.now().isoformat(),
            "backup": backup_name
        }
        self.active_file.write_text(json.dumps(active_info, indent=2))

        return {
            "injected": name,
            "backup": backup_name,
            "files": restored_files,
            "errors": errors if errors else None
        }

    def list_archives(self) -> Dict[str, Any]:
        """List all available archives."""
        archives = []
        for archive_dir in self.archives_dir.iterdir():
            if archive_dir.is_dir():
                metadata_file = archive_dir / "_metadata.json"
                if metadata_file.exists():
                    metadata = json.loads(metadata_file.read_text())
                    archives.append({
                        "name": archive_dir.name,
                        "archived_at": metadata.get("archived_at"),
                        "files_count": len(metadata.get("files", []))
                    })
                else:
                    archives.append({"name": archive_dir.name, "archived_at": None})

        # Sort by name, but put _before_* backups at the end
        archives.sort(key=lambda x: (x["name"].startswith("_"), x["name"]))

        return {
            "archives": archives,
            "active": self._get_active_config()
        }

    def _get_active_config(self) -> Optional[str]:
        """Get currently active config name."""
        if self.active_file.exists():
            data = json.loads(self.active_file.read_text())
            return data.get("active")
        return None

    def get_active_info(self) -> Dict[str, Any]:
        """Get info about currently active config (detects by hash match)."""
        # First check if current matches any archive
        matched = self._detect_matching_archive()

        if matched:
            return {
                "active": matched,
                "matched_by": "hash",
                "note": "Current config matches this archive"
            }

        # Check if we have injection history
        if self.active_file.exists():
            data = json.loads(self.active_file.read_text())
            data["matched_by"] = "history"
            data["note"] = "Last injected config (current files may have changed)"
            return data

        return {
            "active": None,
            "matched_by": None,
            "note": "Current config doesn't match any archive"
        }

    def delete_archive(self, name: str) -> Dict[str, Any]:
        """Delete a named archive."""
        archive_path = self._get_archive_path(name)
        if not archive_path.exists():
            return {"error": f"Archive '{name}' not found"}

        shutil.rmtree(archive_path)
        return {"deleted": name}

    def export_archive(self, name: str, dest_path: str) -> Dict[str, Any]:
        """Export an archive to an external path (for sharing/backup)."""
        archive_path = self._get_archive_path(name)
        if not archive_path.exists():
            return {"error": f"Archive '{name}' not found"}

        dest = Path(dest_path)
        if dest.exists():
            return {"error": f"Destination already exists: {dest_path}"}

        shutil.copytree(archive_path, dest)
        return {"exported": name, "to": str(dest)}

    def import_archive(self, source_path: str, name: str) -> Dict[str, Any]:
        """Import an archive from an external path."""
        source = Path(source_path)
        if not source.exists():
            return {"error": f"Source not found: {source_path}"}

        archive_path = self._get_archive_path(name)
        if archive_path.exists():
            return {"error": f"Archive '{name}' already exists"}

        shutil.copytree(source, archive_path)
        return {"imported": name, "from": str(source)}
