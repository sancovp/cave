#!/bin/bash
# PAIA Agent Container Entrypoint
# Starts tmux session for Claude + handoff server

# Start tmux server
tmux new-session -d -s cave -n main

# Start handoff server (foreground, keeps container alive)
python /usr/local/bin/handoff_server.py
