#!/bin/bash
# Stop CAVE daemon and optionally kill tmux session

set -e

SESSION="${CAVE_SESSION:-cave}"
KILL_SESSION="${1:-}"

echo "🕳️ Stopping CAVE..."

# Kill daemon
if [ -f /tmp/cave.pid ]; then
    CAVE_PID=$(cat /tmp/cave.pid)
    if kill -0 $CAVE_PID 2>/dev/null; then
        kill $CAVE_PID
        echo "   Daemon stopped (PID: $CAVE_PID)"
    else
        echo "   Daemon not running"
    fi
    rm /tmp/cave.pid
else
    echo "   No PID file found"
    # Try to find and kill anyway
    pkill -f "cave.server.http_server" 2>/dev/null && echo "   Killed orphan process" || true
fi

# Optionally kill tmux session
if [ "$KILL_SESSION" = "--kill-session" ] || [ "$KILL_SESSION" = "-k" ]; then
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux kill-session -t "$SESSION"
        echo "   Killed tmux session: $SESSION"
    else
        echo "   No tmux session: $SESSION"
    fi
fi

echo "🕳️ CAVE stopped"
