#!/usr/bin/env python3
"""Review CogLog entries for safety before Discord publishing."""
import json
import re


def check_safety(entry):
    name = entry.get("name", "")
    desc = entry.get("description", "")
    combined = f"{name} {desc}"

    reasons = []

    # Real file paths with usernames - check both raw and stripped
    # Markdown links like [home](../Home/Home_itself.md) hide the word but GOD/.claude/ still leaks
    stripped = re.sub(r'\[.*?\]\(.*?\)', '', combined)
    if re.search(r'/home/GOD/', stripped) or re.search(r'/home/GOD/', combined):
        reasons.append("Contains file path with username (/home/GOD/)")
    # Also catch when markdown stripping breaks the path but GOD/.claude remains
    elif re.search(r'GOD/\.claude/', stripped) or re.search(r'GOD/\.claude/', combined):
        reasons.append("Contains file path with username (GOD/.claude/)")

    # API keys/tokens
    if re.search(r'(?:api[_-]?key|token|secret|password|auth)\s*[=:]\s*\S+', combined, re.IGNORECASE):
        reasons.append("Potential API key/secret")

    # Bearer tokens
    if re.search(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', combined):
        reasons.append("Contains bearer token")

    # UUIDs in description body (name UUIDs are CogLog IDs, fine)
    desc_uuids = re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', desc, re.IGNORECASE)
    if desc_uuids:
        reasons.append("Contains UUID in description (potential session/user ID)")

    # Email addresses
    if re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', combined):
        reasons.append("Contains email address")

    # IP addresses (skip loopback/broadcast)
    for ip in re.findall(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', combined):
        parts = ip.split('.')
        if all(0 <= int(p) <= 255 for p in parts) and ip not in ('0.0.0.0', '127.0.0.1', '255.255.255.255'):
            reasons.append(f"Contains IP address ({ip})")
            break

    # Private keys
    if re.search(r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY', combined):
        reasons.append("Contains private key")

    # Long hex tokens in description
    if re.findall(r'\b[0-9a-fA-F]{32,}\b', desc):
        reasons.append("Contains long hex string (potential token)")

    # Connection strings
    if re.search(r'(?:mysql|postgres|mongodb|redis|amqp)://\S+', combined, re.IGNORECASE):
        reasons.append("Contains database connection string")

    # Sensitive system paths
    if re.search(r'/etc/(passwd|shadow|ssh|ssl)', combined):
        reasons.append("Contains sensitive system path")

    # Stack traces
    if re.search(r'Traceback \(most recent call last\)', combined):
        reasons.append("Contains stack trace (may expose internal architecture)")

    safe = len(reasons) == 0
    reason = "; ".join(reasons) if reasons else "Semantic work description, safe to publish"

    return {"name": name, "safe_to_publish": safe, "reason": reason}


def main():
    with open("/tmp/tmp7kf1_shg.json") as f:
        entries = json.load(f)

    results = [check_safety(entry) for entry in entries]

    with open("/tmp/coglog_review.json", "w") as f:
        json.dump(results, f, indent=2)

    safe_count = sum(1 for r in results if r["safe_to_publish"])
    unsafe_count = sum(1 for r in results if not r["safe_to_publish"])
    print(f"Total: {len(results)}")
    print(f"Safe: {safe_count}")
    print(f"Unsafe: {unsafe_count}")

    if unsafe_count > 0:
        print("\nUnsafe entries:")
        for r in results:
            if not r["safe_to_publish"]:
                print(f"  - {r['name']}: {r['reason']}")


if __name__ == "__main__":
    main()
