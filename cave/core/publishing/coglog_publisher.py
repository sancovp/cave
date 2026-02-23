"""CogLog Publisher — CartON → Review+Redact → Discord pipeline.

Two-schedule file-as-interface pattern:
  review (every 3h): Query Neo4j for new CogLogs → dump to review file →
    claude -p agent reads each entry, decides safe/unsafe, redacts inline if needed,
    writes back with reviewed=true + safe_to_publish + optional redacted_description.
  publish (every 6h): Read review file → post all safe entries to Discord → checkpoint.

The agent does review AND redaction in one pass. No separate redactor.

Usage:
    python coglog_publisher.py review             # run review agent
    python coglog_publisher.py publish             # post reviewed entries to Discord
    python coglog_publisher.py publish --dry-run   # skip Discord post
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHECKPOINT_FILE = Path(os.environ.get(
    "HEAVEN_DATA_DIR", "/tmp/heaven_data"
)) / "coglog_publisher_checkpoint.json"

REVIEW_PROMPT = """You are a safety reviewer and redactor for publishing AI work logs to Discord.

Read the JSON file at: {file_path}

It contains CogLog entries, each with "name", "description", "timestamp", and "reviewed" (null).

For EACH entry, do this:
1. Is it safe to publish as-is? Most CogLogs are safe — semantic work descriptions like
   "general::paiab::testing::verified log extraction works" are FINE.
2. If UNSAFE (contains API keys, tokens, secrets, file paths with usernames, session IDs,
   personal info, or exploitable architecture details) → redact the description:
   - File paths → "[path]", API keys/tokens → "[redacted]", UUIDs → "[id]", usernames → "[user]"
   - Add "redacted_description" field with the cleaned version.
3. Set "reviewed": true and "safe_to_publish": true on EVERY entry (unsafe ones get redacted
   then marked safe). Only set safe_to_publish=false if the entry is so sensitive it cannot
   be redacted meaningfully.

Write the annotated array back to the SAME file path.
Use the Read tool to read the file and the Write tool to write it back."""


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            data = json.loads(CHECKPOINT_FILE.read_text())
            # Migrate from old timestamp-based format
            if "posted" not in data:
                data = {"posted": [], "stats": {}}
            return data
        except Exception:
            pass
    return {"posted": [], "stats": {}}


def save_checkpoint(data):
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2))


def query_all_coglogs():
    """Query Neo4j for ALL CogLogs, chronological order."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j driver not installed: pip install neo4j")
        return []

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")

    query = """
    MATCH (c:Wiki)-[:IS_A]->(:Wiki {n: "General_Coglog"})
    RETURN c.n as name, c.d as description, toString(c.t) as timestamp
    ORDER BY c.t ASC
    """

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            result = session.run(query)
            return [dict(record) for record in result]
    finally:
        driver.close()



WORK_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "coglog_work"


def _run_agent(prompt, timeout=600):
    """Run claude -p with a prompt. Agent reads/writes files itself.

    Returns True if agent succeeded, False otherwise.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--allowedTools", "Read,Write"],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            logger.error("Agent failed (rc=%d): %s", result.returncode, result.stderr[:500])
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("Agent timed out after %ds", timeout)
        return False


def strip_wiki_links(text):
    """Strip CartON wiki markdown links: [word](../Path/File.md) → word"""
    return re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)


def format_coglog_message(entries):
    """Format CogLog entries as a Discord message string."""
    lines = [f"**CogLog Digest** ({len(entries)} entries)\n"]
    for entry in entries:
        desc = entry.get("redacted_description", entry.get("description", ""))
        desc = strip_wiki_links(desc)
        ts = entry.get("timestamp", "")[:19]
        lines.append(f"`{ts}` {desc}")
    return "\n".join(lines)


DISCORD_CONFIG_FILE = Path(os.environ.get(
    "HEAVEN_DATA_DIR", "/tmp/heaven_data"
)) / "discord_config.json"


def load_discord_config():
    """Load Discord configuration from JSON file."""
    if not DISCORD_CONFIG_FILE.exists():
        logger.error("Discord config not found: %s", DISCORD_CONFIG_FILE)
        return None
    try:
        return json.loads(DISCORD_CONFIG_FILE.read_text())
    except Exception as e:
        logger.error("Failed to read Discord config: %s", e)
        return None


def post_to_discord(channel_name, entries):
    """Post CogLog entries to Discord via DiscordMCPClient (cave_discord_fork).

    Reads channel_id from discord_config.json by channel_name.
    DISCORD_TOKEN and DISCORD_GUILD_ID still from env (secrets stay out of JSON).
    """
    config = load_discord_config()
    if not config:
        return False

    channel_id = config.get("channels", {}).get(channel_name)
    if not channel_id:
        logger.error("Channel '%s' not in discord_config.json", channel_name)
        return False

    token = config.get("token", "")
    guild_id = config.get("guild_id", "")
    if not token or not guild_id:
        logger.error("token and guild_id required in discord_config.json")
        return False

    sys.path.insert(0, "/tmp/cave_discord_fork")
    from discord_mcp_client import DiscordMCPClient

    client = DiscordMCPClient(token, guild_id)
    try:
        client.start()

        # Post in chunks (Discord 2000 char limit)
        message = format_coglog_message(entries)
        for i in range(0, len(message), 1900):
            chunk = message[i:i + 1900]
            client.send_message(channel_id, chunk)

        return True
    except Exception as e:
        logger.error("Discord post failed: %s", e)
        return False
    finally:
        client.stop()


def review():
    """Review new CogLogs. Schedule: every 3h.

    Queries Neo4j for unreviewed entries, appends to review file,
    runs claude -p to review+redact in one pass. No-op if nothing new.
    """
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    review_file = WORK_DIR / "review_queue.json"

    # 1. Load checkpoint + existing reviewed entries
    checkpoint = load_checkpoint()
    reviewed_set = set(checkpoint.get("reviewed", []))

    # Load already-reviewed entries from file (may exist from prior runs)
    existing = []
    if review_file.exists():
        try:
            existing = json.loads(review_file.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []

    # 2. Query Neo4j for all CogLogs
    all_coglogs = query_all_coglogs()
    if not all_coglogs:
        return {"status": "no_coglogs"}

    # 3. Find new unreviewed entries
    new_entries = [c for c in all_coglogs if c["name"] not in reviewed_set]
    if not new_entries:
        logger.info("No new CogLogs to review (%d total)", len(all_coglogs))
        return {"status": "nothing_new", "total": len(all_coglogs)}

    logger.info("New entries to review: %d", len(new_entries))

    # 4. Prep new entries with reviewed=null, append to file
    for entry in new_entries:
        entry["reviewed"] = None
        entry["safe_to_publish"] = None
    all_entries = existing + new_entries
    review_file.write_text(json.dumps(all_entries, indent=2))

    # 5. Run review+redact agent (one pass)
    if not _run_agent(REVIEW_PROMPT.format(file_path=str(review_file))):
        logger.error("Review agent failed — entries left unreviewed")
        return {"status": "agent_failed", "unreviewed": len(new_entries)}

    # 6. Read back, update checkpoint with newly reviewed names
    reviewed = json.loads(review_file.read_text())
    newly_reviewed = [e["name"] for e in reviewed if e.get("reviewed")]
    reviewed_set.update(newly_reviewed)
    checkpoint["reviewed"] = list(reviewed_set)
    checkpoint["last_review"] = datetime.now().isoformat()
    save_checkpoint(checkpoint)

    safe = sum(1 for e in reviewed if e.get("safe_to_publish"))
    logger.info("Reviewed: %d new, %d total safe", len(newly_reviewed), safe)

    return {
        "status": "reviewed",
        "new_reviewed": len(newly_reviewed),
        "total_in_file": len(reviewed),
        "safe": safe,
    }


def publish(channel_name="coglog", dry_run=False):
    """Publish reviewed CogLogs to Discord. Schedule: every 6h.

    Reads review file, posts all safe_to_publish=true entries, checkpoints posted names.
    """
    review_file = WORK_DIR / "review_queue.json"

    if not review_file.exists():
        return {"status": "no_review_file"}

    # 1. Load reviewed entries
    entries = json.loads(review_file.read_text())
    checkpoint = load_checkpoint()
    posted_set = set(checkpoint.get("posted", []))

    # 2. Filter: safe + not yet posted
    to_post = [
        e for e in entries
        if e.get("safe_to_publish") and e["name"] not in posted_set
    ]
    if not to_post:
        logger.info("Nothing new to publish")
        return {"status": "nothing_to_post", "total_posted": len(posted_set)}

    logger.info("Publishing %d entries to #%s", len(to_post), channel_name)

    # 3. Post to Discord
    if dry_run:
        for e in to_post:
            desc = e.get("redacted_description", e.get("description", ""))
            logger.info("  DRY [%s] %s", e["name"][:30], desc[:80])
    else:
        if not post_to_discord(channel_name, to_post):
            return {"status": "discord_error", "entries": len(to_post)}

    # 4. Checkpoint posted
    posted_set.update(e["name"] for e in to_post)
    checkpoint["posted"] = list(posted_set)
    checkpoint["last_publish"] = datetime.now().isoformat()
    checkpoint["stats"] = {
        "total_posted": len(posted_set),
        "last_batch": len(to_post),
    }
    save_checkpoint(checkpoint)

    # 5. Remove posted entries from review file (keep unreviewed + unpublishable)
    remaining = [e for e in entries if e["name"] not in posted_set]
    if remaining:
        review_file.write_text(json.dumps(remaining, indent=2))
    else:
        review_file.unlink(missing_ok=True)

    return {
        "status": "published" if not dry_run else "dry_run",
        "posted": len(to_post),
        "total_posted": len(posted_set),
        "remaining": len(remaining),
    }


# Legacy compat — run() does review then publish
def run(channel_name="coglog", dry_run=False):
    """Run both review and publish in sequence."""
    r = review()
    if r.get("status") in ("agent_failed",):
        return r
    return publish(channel_name=channel_name, dry_run=dry_run)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CogLog Publisher — review+redact then publish")
    parser.add_argument("command", choices=["review", "publish", "run"], default="run", nargs="?")
    parser.add_argument("--dry-run", action="store_true", help="Skip Discord posting")
    parser.add_argument("--channel", default="coglog", help="Discord channel name")
    args = parser.parse_args()

    if args.command == "review":
        result = review()
    elif args.command == "publish":
        result = publish(channel_name=args.channel, dry_run=args.dry_run)
    else:
        result = run(channel_name=args.channel, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
