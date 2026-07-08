# cave-harness-base:latest
# NEUTRAL CAVE-server runtime base. Reproduces the runtime stack of the proven
# jobworld-cave:latest image WITHOUT any jobworld product code / branding / entrypoint.
# Downstream products (PromptWorld, other x-CAVE products) build FROM this and set
# their own ENTRYPOINT. This base does NOT auto-serve anything.
FROM python:3.11-slim

# --- system packages: curl bash tmux git + Node.js 20 ---
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl bash tmux git ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# --- Claude CLI (pinned to the proven version) ---
RUN npm install -g @anthropic-ai/claude-code@2.1.144

# --- user: ceo (uid/gid 1000), workdir /agent ---
RUN groupadd -g 1000 ceo \
 && useradd -m -u 1000 -g 1000 -s /bin/bash ceo \
 && mkdir -p /agent/.claude /shared \
 && chown -R ceo:ceo /agent /shared /home/ceo

# --- third-party python deps (exact pins from the proven image, minus our 5 source pkgs) ---
# Installed with --no-deps ON PURPOSE: frozen.full.txt is the COMPLETE pip-freeze closure of the
# proven jobworld-cave:latest image (every transitive dep is already an explicit == pin here), so
# --no-deps plants the exact proven versions and reproduces that environment precisely. A plain
# `-r` (strict resolver) FAILS here because the proven image's own pins are mutually inconsistent
# under strict resolution (langchain 1.3.1 declares langchain-core>=1.4.0, yet the proven image
# actually runs langchain-core==0.3.86 — verified). The proven image works with that exact pair;
# --no-deps reproduces it instead of letting the resolver reject the proven reality.
COPY requirements-base.txt /tmp/requirements-base.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements-base.txt

# --- our source python packages (installed AFTER pinned deps, --no-deps, from monorepo source) ---
# staged into the build context by build.sh
COPY src/heaven-framework /tmp/src/heaven-framework
COPY src/sdna           /tmp/src/sdna
COPY src/cave           /tmp/src/cave
COPY src/cave-teams     /tmp/src/cave-teams
COPY src/llegos         /tmp/src/llegos
RUN pip install --no-cache-dir --no-deps \
      /tmp/src/heaven-framework \
      /tmp/src/sdna \
      /tmp/src/cave \
      /tmp/src/cave-teams \
      /tmp/src/llegos \
 && rm -rf /tmp/src /tmp/requirements-base.txt

WORKDIR /agent
USER ceo

# NEUTRAL entrypoint: no jobworld, no auto-serve on 8501. Downstream sets its own.
CMD ["bash"]
