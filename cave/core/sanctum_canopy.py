"""Sanctum ↔ Canopy Bridge.

Sanctum defines rituals (source of truth).
Canopy tracks completion (universal lane system).

Population: ritual due → create Canopy Human-Only item
Completion: "done X" → lookup canopy item_id → mark_complete → streak++
Map file: /tmp/heaven_data/sanctum_canopy_map.json (daily reset)
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

HEAVEN_DATA_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
MAP_FILE = HEAVEN_DATA_DIR / "sanctum_canopy_map.json"
SANCTUMS_DIR = HEAVEN_DATA_DIR / "sanctums"
SANCTUM_CONFIG = SANCTUMS_DIR / "_config.json"


def _load_map() -> Dict[str, Any]:
    """Load today's ritual→canopy map. Resets if date changed."""
    today = datetime.now().strftime("%Y-%m-%d")
    if MAP_FILE.exists():
        try:
            data = json.loads(MAP_FILE.read_text())
            if data.get("date") == today:
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load canopy map: %s", e, exc_info=True)
    return {"date": today, "rituals": {}}


def _save_map(data: Dict[str, Any]) -> None:
    MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    MAP_FILE.write_text(json.dumps(data, indent=2))


def _get_active_sanctum_name() -> Optional[str]:
    """Get currently active sanctum name from config."""
    if not SANCTUM_CONFIG.exists():
        return None
    try:
        return json.loads(SANCTUM_CONFIG.read_text()).get("current")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read sanctum config: %s", e, exc_info=True)
        return None


def _load_sanctum(name: str) -> Optional[Dict[str, Any]]:
    """Load sanctum JSON by name."""
    path = SANCTUMS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load sanctum '%s': %s", name, e, exc_info=True)
        return None


def _save_sanctum(name: str, data: Dict[str, Any]) -> None:
    """Save sanctum JSON."""
    path = SANCTUMS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2))


async def _get_canopy_client():
    """Get an initialized Canopy MCP client via strata."""
    from strata.mcp_client_manager import MCPClientManager

    mgr = MCPClientManager(server_names=["canopy"])
    await mgr.initialize_from_config()
    return mgr


async def populate_ritual(ritual_name: str, ritual_description: str) -> Dict[str, Any]:
    """Create a Canopy Human-Only item for a ritual. Returns map entry.

    Idempotent: skips if ritual already in today's map.
    """
    map_data = _load_map()

    # Already populated today
    if ritual_name in map_data["rituals"]:
        return map_data["rituals"][ritual_name]

    mgr = await _get_canopy_client()
    try:
        client = mgr.get_client("canopy")
        result = await client.call_tool("add_to_schedule", {
            "item_type": "Human-Only",
            "description": f"[SANCTUM] {ritual_name}: {ritual_description}",
            "execution_type": "plotted_course",
            "execution_type_decision_explanation": "Sanctum ritual — human completes, system tracks",
            "priority": 6,
            "human_capability": f"Complete ritual: {ritual_name}",
            "metadata": {
                "source": "sanctum",
                "ritual_name": ritual_name,
                "date": map_data["date"],
            },
        })

        # Extract item_id from result
        item_id = _extract_item_id(result)
        if not item_id:
            logger.error("Canopy add_to_schedule returned no item_id: %s", result)
            return {"error": "no item_id returned"}

        entry = {"canopy_item_id": item_id, "status": "pending"}
        map_data["rituals"][ritual_name] = entry
        _save_map(map_data)
        logger.info("Populated ritual %s → canopy item %s", ritual_name, item_id)
        return entry
    finally:
        await mgr.disconnect_all()


async def complete_ritual(ritual_name: str) -> Dict[str, Any]:
    """Mark a ritual complete in Canopy + update sanctum streak.

    Returns result dict with status.
    """
    map_data = _load_map()

    # Check if ritual is in today's map
    if ritual_name not in map_data["rituals"]:
        return {"status": "error", "error": f"Ritual '{ritual_name}' not in today's schedule. Populating now..."}

    entry = map_data["rituals"][ritual_name]

    if entry.get("status") == "completed":
        return {"status": "already_completed", "ritual": ritual_name}

    item_id = entry.get("canopy_item_id")
    if not item_id:
        return {"status": "error", "error": f"No canopy_item_id for ritual '{ritual_name}'"}

    # Mark complete in Canopy
    mgr = await _get_canopy_client()
    try:
        client = mgr.get_client("canopy")
        result = await client.call_tool("mark_complete", {"item_id": item_id})
        logger.info("Canopy mark_complete(%s): %s", item_id, result)
    finally:
        await mgr.disconnect_all()

    # Update map
    entry["status"] = "completed"
    entry["completed_at"] = datetime.now().isoformat()
    _save_map(map_data)

    # Update sanctum streak
    streak = _increment_streak(ritual_name)

    return {
        "status": "completed",
        "ritual": ritual_name,
        "canopy_item_id": item_id,
        "streak": streak,
    }


async def populate_all_due_rituals() -> Dict[str, Any]:
    """Populate Canopy items for all active rituals in current sanctum.

    Called when rituals become due or on-demand via endpoint.
    Returns dict of ritual_name → populate result.
    """
    sanctum_name = _get_active_sanctum_name()
    if not sanctum_name:
        return {"error": "No active sanctum configured"}

    sanctum = _load_sanctum(sanctum_name)
    if not sanctum:
        return {"error": f"Could not load sanctum '{sanctum_name}'"}

    results = {}
    for ritual in sanctum.get("rituals", []):
        if not ritual.get("active", True):
            continue
        name = ritual["name"]
        desc = ritual.get("description", "")
        results[name] = await populate_ritual(name, desc)

    return {"sanctum": sanctum_name, "populated": results}


def _increment_streak(ritual_name: str) -> int:
    """Increment streak for a ritual in active sanctum. Returns new streak."""
    sanctum_name = _get_active_sanctum_name()
    if not sanctum_name:
        return -1

    sanctum = _load_sanctum(sanctum_name)
    if not sanctum:
        return -1

    for ritual in sanctum.get("rituals", []):
        if ritual["name"] == ritual_name:
            ritual["streak"] = ritual.get("streak", 0) + 1
            _save_sanctum(sanctum_name, sanctum)
            logger.info("Streak for %s: %d", ritual_name, ritual["streak"])
            return ritual["streak"]

    return -1


def _extract_item_id(result) -> Optional[str]:
    """Extract item_id from Canopy MCP call_tool result.

    Result is List[ContentBlock]. Each block has .text with JSON.
    """
    if not result:
        return None

    for block in result:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            data = json.loads(text)
            # Canopy returns item_id in the result
            if isinstance(data, dict):
                item_id = data.get("item_id")
                if item_id:
                    return item_id
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("Non-JSON content block in Canopy result: %s", e, exc_info=True)
            # Maybe it's just a string item_id
            if isinstance(text, str) and len(text) < 100 and not text.startswith("{"):
                return text.strip()

    return None


def get_ritual_status() -> Dict[str, Any]:
    """Get today's ritual completion status."""
    map_data = _load_map()
    return {
        "date": map_data["date"],
        "rituals": map_data["rituals"],
        "completed": sum(1 for r in map_data["rituals"].values() if r.get("status") == "completed"),
        "total": len(map_data["rituals"]),
    }
