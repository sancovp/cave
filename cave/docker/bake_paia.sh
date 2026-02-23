#!/bin/bash
# bake_paia.sh - Build PAIA Docker images
#
# Usage:
#   ./bake_paia.sh base                    # Build base image
#   ./bake_paia.sh run <name> <instruction> # Run container with guru instruction
#   ./bake_paia.sh commit <container> <tag> # Commit container as new image
#
# The pattern:
#   1. Build base image (Claude Code + base MCPs)
#   2. Run container with guru instruction
#   3. Agent self-organizes via guru loop
#   4. Human scores, commits if good

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${PAIA_REGISTRY:-paia}"
BASE_TAG="paia-agent:latest"           # Existing base image
EXTENDED_TAG="${REGISTRY}/extended:latest"  # With guru + MCPs

usage() {
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  base                     Build base image"
    echo "  run <name> <instruction> Run PAIA with guru instruction"
    echo "  attach <name>            Attach to running PAIA tmux"
    echo "  status <name>            Check PAIA status"
    echo "  commit <name> <tag>      Commit PAIA as new image"
    echo "  logs <name>              Show PAIA logs"
    exit 1
}

build_base() {
    echo "Building extended PAIA image (from paia-agent:latest)..."
    docker build -t "$EXTENDED_TAG" -f "$SCRIPT_DIR/Dockerfile.extended" "$SCRIPT_DIR"
    echo "Extended image built: $EXTENDED_TAG"
    echo "Base image: $BASE_TAG"
}

run_paia() {
    local name="$1"
    local instruction="$2"

    if [ -z "$name" ] || [ -z "$instruction" ]; then
        echo "Error: name and instruction required"
        echo "Usage: $0 run <name> <instruction|@file>"
        exit 1
    fi

    # Support @file syntax for loading instruction from file
    if [[ "$instruction" == @* ]]; then
        local file="${instruction:1}"
        if [ -f "$file" ]; then
            instruction=$(cat "$file")
        else
            echo "Error: File not found: $file"
            exit 1
        fi
    fi

    # Create state directory on host
    local state_dir="/tmp/paia-state/$name"
    mkdir -p "$state_dir"

    echo "Starting PAIA: $name"
    echo "Guru instruction: $instruction"

    # Find available port starting from 8421
    local port=8421
    while netstat -tuln 2>/dev/null | grep -q ":$port " || ss -tuln 2>/dev/null | grep -q ":$port "; do
        port=$((port + 1))
    done

    docker run -d \
        --name "paia-$name" \
        -e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" \
        -e "GURU_INSTRUCTION=$instruction" \
        -p "$port:8421" \
        -v "$state_dir:/agent/state" \
        -v "/var/run/docker.sock:/var/run/docker.sock" \
        "$EXTENDED_TAG"

    echo "Command server: http://localhost:$port"

    echo "PAIA started. State dir: $state_dir"
    echo "Attach with: $0 attach $name"
}

attach_paia() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Error: name required"
        exit 1
    fi
    docker exec -it "paia-$name" tmux attach -t claude
}

status_paia() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Error: name required"
        exit 1
    fi

    local state_dir="/tmp/paia-state/$name"
    if [ -f "$state_dir/agent_state.json" ]; then
        cat "$state_dir/agent_state.json"
    else
        echo "No state file found"
    fi
}

commit_paia() {
    local name="$1"
    local tag="$2"

    if [ -z "$name" ] || [ -z "$tag" ]; then
        echo "Error: name and tag required"
        echo "Usage: $0 commit <name> <tag>"
        exit 1
    fi

    echo "Committing paia-$name as $REGISTRY/$tag"
    docker commit "paia-$name" "$REGISTRY/$tag"
    echo "Committed: $REGISTRY/$tag"
}

logs_paia() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Error: name required"
        exit 1
    fi
    docker logs -f "paia-$name"
}

# Main
case "${1:-}" in
    base)
        build_base
        ;;
    run)
        run_paia "$2" "$3"
        ;;
    attach)
        attach_paia "$2"
        ;;
    status)
        status_paia "$2"
        ;;
    commit)
        commit_paia "$2" "$3"
        ;;
    logs)
        logs_paia "$2"
        ;;
    *)
        usage
        ;;
esac
