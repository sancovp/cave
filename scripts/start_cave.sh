#!/bin/bash
# CAVE Entry Point
# Start CAVE daemon and attach to tmux session

set -e

# Configuration
CONFIG_FILE="${1:-}"
SESSION="${CAVE_SESSION:-cave}"
WORKDIR="${CAVE_WORKDIR:-$(pwd)}"
AGENT_CMD="${CAVE_AGENT_CMD:-claude --debug}"
PORT="${CAVE_PORT:-8080}"

# Start CAVE daemon in background
python -m cave.server.http_server --port "$PORT" > /tmp/cave_daemon.log 2>&1 &
CAVE_PID=$!
echo $CAVE_PID > /tmp/cave.pid
echo "   Daemon started (PID: $CAVE_PID, port: $PORT)"

# Wait for server to be ready
echo "   Waiting for server..."
for i in {1..10}; do
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo "   Server ready!"
        break
    fi
    sleep 1
done

# Check if server started successfully
if ! curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
    echo "❌ Failed to start CAVE server"
    kill $CAVE_PID 2>/dev/null
    exit 1
fi

# Attach to tmux session or create new one
if tmux -u has-session -t "$SESSION" 2>/dev/null; then
    echo "   Attaching to existing session: $SESSION"
    tmux -u attach -t "$SESSION"
else
    echo "   Creating new session: $SESSION"
    # Create session with shell first, then run claude inside it
    # This way when claude exits, you drop to shell (not exit tmux)
    tmux -u new-session -d -s "$SESSION" -c "$WORKDIR"
    tmux send-keys -t "$SESSION" "$AGENT_CMD" Enter
    tmux -u attach -t "$SESSION"
fi

echo "🕳️ CAVE session ended (daemon still running)"
echo "   To stop daemon: ./stop_cave.sh"
