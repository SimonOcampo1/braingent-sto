#!/usr/bin/env bash
# STO agenticOS launcher for Linux and macOS: brings up backend + Vite and
# opens the browser. The twin of start.cmd.
#
# It needs bash, not sh, because of how the two servers are held. On Windows
# each one gets its own console window and closing them is the user's problem;
# here they would be orphans sitting on 8765 and 5173 until someone hunted the
# pids down. So `set -m` gives each its own process group, a trap takes both
# groups down on Ctrl+C, and their output goes to .sto-cache/ instead of
# scrolling over each other.
set -euo pipefail
set -m

cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_PORT=${STO_SESSIONS_PORT:-8765}
APP_PORT=${STO_APP_PORT:-5173}
LOGS=.sto-cache
mkdir -p "$LOGS"

die() { echo "[ERROR] $*" >&2; exit 1; }

# ── the runtimes ──

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    die "Python is missing: https://www.python.org/downloads/"
fi
command -v npm >/dev/null 2>&1 || die "Node.js/npm is missing: https://nodejs.org/"

# ── the front-end deps (idempotent: fast when already there) ──

echo "Checking the app dependencies..."
(cd app && npm install) || die "npm install failed"

# ── graphify (repo knowledge graph) ──
#
# Optional, and here it means it: a missing graph is one tab with less in it,
# not a reason to keep the dashboard down. start.cmd exits on the same failure,
# which is worth reconciling one day.

export PATH="$HOME/.local/bin:$PATH"
if ! command -v graphify >/dev/null 2>&1; then
    if ! command -v uv >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh || true
        export PATH="$HOME/.local/bin:$PATH"
    fi
    if command -v uv >/dev/null 2>&1; then
        echo "Installing graphify..."
        uv tool install graphifyy || echo "[warn] could not install graphify" >&2
    else
        echo "[warn] no uv: skipping the repo knowledge graph" >&2
    fi
fi
if command -v graphify >/dev/null 2>&1 && [ ! -f graphify-out/graph.json ]; then
    echo "Building the repo knowledge graph..."
    graphify update . || echo "[warn] graphify update failed" >&2
fi

# ── `sto` in the terminal (idempotent; fixes the path if you moved the repo) ──

sh scripts/install_sto_cli.sh

# ── the two servers ──

pids=()
cleanup() {
    trap - INT TERM EXIT
    # the negative pid is the whole group: `npm run dev` is a parent of vite,
    # and killing only npm leaves vite holding the port
    for pid in ${pids[@]+"${pids[@]}"}; do
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

"$PY" scripts/sessions_server.py >"$LOGS/backend.log" 2>&1 &
pids+=($!)
(cd app && exec npm run dev) >"$LOGS/app.log" 2>&1 &
pids+=($!)

# Waiting on the port beats sleeping: `npm install` warms the cache, so a fixed
# delay is either too long every other boot or too short on the first one.
echo "Waiting for the app on :$APP_PORT..."
if ! "$PY" - "$APP_PORT" <<'EOF'
import socket
import sys
import time

# "localhost", not "127.0.0.1": Vite binds whatever the name resolves to, and
# on a machine that answers it with ::1 a hardcoded v4 probe never connects
# while the dev server sits there printing "ready".
port = int(sys.argv[1])
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        socket.create_connection(("localhost", port), timeout=0.5).close()
        sys.exit(0)
    except OSError:
        time.sleep(0.25)
sys.exit(1)
EOF
then
    die "the app never came up on :$APP_PORT — see $LOGS/app.log"
fi

url="http://localhost:$APP_PORT"
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
    open "$url" &                                   # macOS
else
    echo "open $url"
fi

echo "backend :$BACKEND_PORT · app :$APP_PORT · logs in $LOGS/ · Ctrl+C to stop"
wait
