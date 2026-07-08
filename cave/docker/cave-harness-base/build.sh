#!/usr/bin/env bash
# Build cave-harness-base:latest — the NEUTRAL CAVE-server runtime base.
# Stages a temp build context (this dir + the 5 monorepo source dirs + a generated
# requirements-base.txt), runs docker build, then cleans the temp context.
set -euo pipefail

MONO="${MONO:-/home/GOD/gnosys-plugin-v2}"
IMAGE="${IMAGE:-cave-harness-base:latest}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# the 5 OUR-source packages: <dest-name>:<monorepo-relpath>
SRCS=(
  "heaven-framework:base/heaven-framework"
  "sdna:base/sdna"
  "cave:application/cave"
  "cave-teams:application/cave-teams"
  "llegos:base/sanctuary-system/llegos"
)

CTX="$(mktemp -d /tmp/cave-harness-base-ctx.XXXXXX)"
cleanup() { rm -rf "$CTX"; }
trap cleanup EXIT

echo ">> build context: $CTX"

# Dockerfile
cp "$HERE/Dockerfile" "$CTX/Dockerfile"

# requirements-base.txt = frozen.full.txt minus the 5 '@ file://' (our-source) lines.
# Generated here so the build is reproducible from the committed frozen.full.txt.
grep -v '@ file://' "$HERE/frozen.full.txt" > "$CTX/requirements-base.txt"
echo ">> requirements-base.txt: $(wc -l < "$CTX/requirements-base.txt") lines (from $(wc -l < "$HERE/frozen.full.txt") frozen)"

# stage the 5 source dirs, excluding heavy/irrelevant artifacts
mkdir -p "$CTX/src"
for entry in "${SRCS[@]}"; do
  name="${entry%%:*}"; rel="${entry#*:}"
  src="$MONO/$rel"
  [ -d "$src" ] || { echo "!! MISSING source dir: $src" >&2; exit 1; }
  echo ">> staging $name  <-  $src"
  rsync -a \
    --exclude='__pycache__' \
    --exclude='*.egg-info' \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='*.pyc' \
    "$src/" "$CTX/src/$name/"
done

echo ">> docker build -t $IMAGE"
docker build -t "$IMAGE" "$CTX"

echo ">> done: $IMAGE"
docker images "$IMAGE"
