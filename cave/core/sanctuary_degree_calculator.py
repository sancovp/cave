"""Sanctuary Degree Calculator.

Computes SD (Sanctuary Degree) from actual behavioral data:
- Ritual completion rate from CartON (Ritual_Completion_*, Ritual_Skip_*)
- Journal assessment scores from CartON (Sanctuary_Degree_*)

Sanctuary vs Wasteland is determined by ritual completion rate.
In Sanctuary → OVP (intent declared, compounding).
In Sanctuary + completed VEC → OVA (knows the way). OEVESE implied by OVA.
In Wasteland → DC (not doing what's defined).
In Wasteland + almost nothing → DE (nothing being done).
In Wasteland + zero activity → Moloch (nothing can be done about nothing).

Writes:
    sanctuary_degree.json — conductor reads this for identity + display
    conductor_prompt_blocks/sanctuary_orientation.md — orientation text for conductor
"""
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

HEAVEN_DATA = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
SD_FILE = HEAVEN_DATA / "sanctuary_degree.json"
ORIENTATION_FILE = HEAVEN_DATA / "conductor_prompt_blocks" / "sanctuary_orientation.md"
SANCTUMS_DIR = HEAVEN_DATA / "sanctums"

# Sanctuary threshold — above this completion rate = in sanctuary
SANCTUARY_THRESHOLD = 0.4  # 40% of rituals completed = in sanctuary

# Wasteland sub-thresholds (below SANCTUARY_THRESHOLD)
DE_THRESHOLD = 0.1   # Below 10% = Demon Elite (almost nothing)
MOLOCH_THRESHOLD = 0.02  # Below 2% = Moloch (nothing can be done about nothing)


def _orientation_text(realm: str, identity: str, concentrate_on: str) -> str:
    """Build conductor orientation prompt."""
    return (
        f"## Sanctuary Degree Orientation\n"
        f"THIS WakingDreamer's state is a **{realm}**, "
        f"specifically it lifts into the identity **{identity}**.\n\n"
        f"Your current abstract identity {identity} means you should concentrate on "
        f"{concentrate_on}"
    )


# Orientation prompts per identity
ORIENTATIONS = {
    "oevese": _orientation_text(
        "sanctuary", "OEVESE",
        "maintaining the continuous positive attractor. Everything is compounding. "
        "Protect the rhythm, celebrate what's working, suggest deeper practice. "
        "This is aspirational — implied by OVA."
    ),
    "ova": _orientation_text(
        "sanctuary", "OVA",
        "deepening what works. Isaac is IN sanctuary and knows the way. "
        "A VEC is complete — the transformation loop is proven. "
        "Support ambitious expansion while protecting the foundation. "
        "(STUB: OVA requires completed VECs — not yet implemented.)"
    ),
    "ovp": _orientation_text(
        "sanctuary", "OVP",
        "helping the user to compound what already exists by ensuring patterns "
        "remain coherent and stable and compounding. Rituals are being done. "
        "The system IS functioning as sanctuary. Reinforce, don't overload."
    ),
    "demon_champion": _orientation_text(
        "wasteland", "Demon Champion",
        "helping the user to break bad patterns and replace them with what they "
        "actually want to be happening. Rituals are defined but not being done "
        "consistently. Be gentle and direct. Focus on ONE thing to restart."
    ),
    "demon_elite": _orientation_text(
        "wasteland", "Demon Elite",
        "helping the user to break bad patterns and replace them with what they "
        "actually want to be happening. Almost nothing is being done. "
        "Don't overwhelm — suggest just one ritual to start with. "
        "Ask about energy and wellbeing before suggesting work."
    ),
    "moloch": _orientation_text(
        "wasteland", "Moloch",
        "helping the user to break bad patterns and replace them with what they "
        "actually want to be happening. Nothing is functioning as sanctuary and "
        "seemingly nothing can be done about it. Check in with Isaac directly. "
        "Do NOT suggest work tasks. Ask: what's one thing that would help right now?"
    ),
}


def _get_active_sanctum() -> Optional[Dict[str, Any]]:
    """Load active sanctum data from JSON."""
    config_path = SANCTUMS_DIR / "_config.json"
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text())
        name = config.get("current")
        if not name:
            return None
        sanctum_path = SANCTUMS_DIR / f"{name}.json"
        if not sanctum_path.exists():
            return None
        return json.loads(sanctum_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load sanctum: %s", e)
        return None


def _count_rituals_due(sanctum: Dict[str, Any], days: int = 7) -> int:
    """Count total rituals due in the last N days."""
    rituals = sanctum.get("rituals", [])
    total = 0
    for r in rituals:
        if not r.get("active", True):
            continue
        freq = r.get("frequency", "daily")
        if freq == "daily":
            total += days
        elif freq == "weekly":
            total += max(1, days // 7)
        elif freq == "monthly":
            total += max(1, days // 30)
    return total


def _query_carton_completions(days: int = 7) -> Tuple[int, int]:
    """Query CartON for ritual completions and skips in last N days.

    Uses timestamp property (n.t) for date filtering since concept names
    have ritual name before date (e.g. Ritual_Completion_Morning_Journal_2026_04_25).

    Returns (completions, skips).
    """
    try:
        from carton_mcp.carton_utils import CartOnUtils
        utils = CartOnUtils()

        cutoff = datetime.now() - timedelta(days=days)
        cutoff_cypher = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

        # Count completions (use datetime() for proper timestamp comparison)
        result = utils.query_wiki_graph(
            "MATCH (n:Wiki) WHERE n.n STARTS WITH 'Ritual_Completion_' "
            "AND n.n <> 'Ritual_Completion' AND n.n <> 'Ritual_Completions' "
            f"AND n.t >= datetime('{cutoff_cypher}') RETURN count(n) as cnt"
        )
        completions = _extract_count(result)

        # Count skips
        result = utils.query_wiki_graph(
            "MATCH (n:Wiki) WHERE n.n STARTS WITH 'Ritual_Skip_' "
            "AND n.n <> 'Ritual_Skip' "
            f"AND n.t >= datetime('{cutoff_cypher}') RETURN count(n) as cnt"
        )
        skips = _extract_count(result)

        return completions, skips

    except Exception as e:
        logger.warning("Failed to query CartON for completions: %s", e)
        return 0, 0


def _extract_count(result) -> int:
    """Extract count from CartON query result.

    CartOnUtils.query_wiki_graph returns dict with 'data' key containing
    list of row dicts, e.g. {"data": [{"cnt": 2}], "success": True}.
    """
    try:
        if isinstance(result, dict):
            data = result.get("data", [])
            if data and isinstance(data, list) and len(data) > 0:
                row = data[0]
                if isinstance(row, dict):
                    # Try 'cnt' key directly
                    for key in ("cnt", "count", "count(n)"):
                        if key in row:
                            return int(row[key])
                    # Try first numeric value
                    for v in row.values():
                        if isinstance(v, (int, float)):
                            return int(v)
        # Fallback: regex on string representation
        import re
        match = re.search(r'cnt["\s:]+(\d+)', str(result))
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0


def _get_latest_journal_score() -> Optional[float]:
    """Get most recent journal sanctuary score from CartON."""
    try:
        from carton_mcp.carton_utils import CartOnUtils
        utils = CartOnUtils()
        result = utils.query_wiki_graph(
            "MATCH (n:Wiki) WHERE n.n STARTS WITH 'Sanctuary_Degree_' "
            "RETURN n.n, n.d ORDER BY n.t DESC LIMIT 1"
        )
        # Extract composite score from description field
        import re
        desc = ""
        if isinstance(result, dict):
            data = result.get("data", [])
            if data and isinstance(data, list) and len(data) > 0:
                desc = str(data[0].get("n.d", ""))
        else:
            desc = str(result)

        # Score format in description: "**Sanctuary**: 0.75" or just "0.75"
        match = re.search(r'(\d+\.\d+)', desc)
        if match:
            score = float(match.group(1))
            if 0 <= score <= 1:
                return score
    except Exception as e:
        logger.warning("Failed to get journal score: %s", e)
    return None


def _completion_rate_to_identity(completion_rate: float, has_vec: bool = False) -> Tuple[str, str, str]:
    """Map completion rate to (identity_key, identity_label, realm).

    Sanctuary (rituals being done) → OVP, or OVA if VEC completed.
    Wasteland (not being done) → DC, DE, or Moloch depending on severity.
    """
    if completion_rate >= SANCTUARY_THRESHOLD:
        # In sanctuary
        if has_vec:
            return "ova", "OVA", "sanctuary"
        return "ovp", "OVP", "sanctuary"
    elif completion_rate >= DE_THRESHOLD:
        return "demon_champion", "Demon Champion", "wasteland"
    elif completion_rate >= MOLOCH_THRESHOLD:
        return "demon_elite", "Demon Elite", "wasteland"
    else:
        return "moloch", "Moloch", "wasteland"


def compute_sanctuary_degree(days: int = 7) -> Dict[str, Any]:
    """Compute Sanctuary Degree from actual behavioral data.

    Combines ritual completion rate (70% weight) with journal scores (30% weight).
    Completion rate is the floor — you can't score high while missing rituals.

    Returns dict with sd, identity, orientation, and breakdown.
    """
    sanctum = _get_active_sanctum()
    if not sanctum:
        logger.info("No active sanctum — defaulting to Moloch")
        return _build_result(0.0, "moloch", "Moloch", "wasteland", "No active sanctum")

    # Ritual completion rate
    total_due = _count_rituals_due(sanctum, days)
    completions, skips = _query_carton_completions(days)

    if total_due > 0:
        completion_rate = completions / total_due
    else:
        completion_rate = 0.0

    # Journal score (latest)
    journal_score = _get_latest_journal_score()

    # TODO: check for completed VECs when VEC system is wired
    has_vec = False

    # Identity from completion rate
    identity_key, identity_label, realm = _completion_rate_to_identity(
        completion_rate, has_vec=has_vec
    )

    # SD float = completion rate (primary signal)
    sd = max(0.0, min(1.0, completion_rate))

    breakdown = {
        "days": days,
        "total_due": total_due,
        "completions": completions,
        "skips": skips,
        "missed": max(0, total_due - completions - skips),
        "completion_rate": round(completion_rate, 3),
        "journal_score": journal_score,
        "has_vec": has_vec,
        "realm": realm,
    }

    return _build_result(sd, identity_key, identity_label, realm, json.dumps(breakdown))


def _build_result(sd: float, identity_key: str, identity_label: str, realm: str, breakdown_info: str) -> Dict[str, Any]:
    """Build result dict and write state files."""
    orientation = ORIENTATIONS.get(identity_key, "")

    result = {
        "sd": round(sd, 3),
        "degree": identity_label,
        "identity": identity_key,
        "realm": realm,
        "orientation": orientation,
        "breakdown": breakdown_info,
        "computed_at": datetime.now().isoformat(),
    }

    # Write sanctuary_degree.json (conductor reads this)
    try:
        SD_FILE.parent.mkdir(parents=True, exist_ok=True)
        SD_FILE.write_text(json.dumps(result, indent=2))
        logger.info("Sanctuary degree updated: SD=%.3f → %s", sd, identity_label)
    except OSError as e:
        logger.error("Failed to write sanctuary_degree.json: %s", e)

    # Write orientation prompt block (conductor system prompt includes this)
    try:
        ORIENTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        ORIENTATION_FILE.write_text(orientation)
        logger.info("Sanctuary orientation written for conductor")
    except OSError as e:
        logger.error("Failed to write sanctuary orientation: %s", e)

    return result
