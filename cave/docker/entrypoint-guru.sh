#!/bin/bash
# PAIA Guru-Aware Entrypoint
# Wraps the base entrypoint with guru instruction support

set -e

STATE_DIR="${STATE_DIR:-/agent/state}"
GURU_INSTRUCTION="${GURU_INSTRUCTION:-}"

# Write initial state
echo '{"status": "starting", "timestamp": "'$(date -Iseconds)'"}' > "$STATE_DIR/agent_state.json"

# Start tmux session (same as base entrypoint)
tmux new-session -d -s cave -n main

# If guru instruction provided, write it and queue for injection
if [ -n "$GURU_INSTRUCTION" ]; then
    echo "$GURU_INSTRUCTION" > "$STATE_DIR/guru_instruction.txt"
    echo '{"status": "guru_queued", "timestamp": "'$(date -Iseconds)'"}' > "$STATE_DIR/agent_state.json"
fi

# Start handoff server in background
python /usr/local/bin/handoff_server.py &
HANDOFF_PID=$!

# Wait for handoff server to be ready
sleep 2

# Launch Claude in tmux
tmux send-keys -t cave "claude" Enter

# Wait for Claude to start
sleep 5

# If guru instruction exists, send it via tmux
if [ -f "$STATE_DIR/guru_instruction.txt" ]; then
    INSTRUCTION=$(cat "$STATE_DIR/guru_instruction.txt")
    tmux send-keys -t cave "$INSTRUCTION" Enter
    echo '{"status": "guru_sent", "timestamp": "'$(date -Iseconds)'"}' > "$STATE_DIR/agent_state.json"
fi

# Wait for handoff server (keeps container alive)
wait $HANDOFF_PID
