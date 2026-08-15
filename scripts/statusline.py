#!/usr/bin/env python3
"""The STO badge for Claude Code's status line: `◆ STO ↑2 ↓16`, in your accent.

Claude Code re-runs the status line command constantly, so this reads two small
JSON files and nothing else — no git, no imports beyond the stdlib's cheapest.
Importing `sessions_server` here would cost ~200 ms on every repaint.

`.sto-cache/badge.json` is written by the TUI and by `sto status`; when it is
missing or stale the badge still shows, just without the counts. Wire it up
with `sto badge`.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
STALE = 3600  # seconds: older than an hour, show the badge but not the numbers


def _json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def badge() -> str:
    accent = _json(Path.home() / ".claude" / "sto-ui.json", {}).get("accent", "36")
    d = _json(ROOT / ".sto-cache" / "badge.json", {})
    text = "◆ STO"
    if d and time.time() - (d.get("ts") or 0) < STALE:
        up, down = d.get("up", 0), d.get("down", 0)
        if up or down:
            text += f" ↑{up} ↓{down}"
    return f"\033[{accent}m{text}\033[0m"


def chained(payload: bytes) -> str:
    """Whatever status line was installed before us, run with the same input.

    ponytail: one subprocess per repaint, and if the previous command was a
    PowerShell script it is the slow half of this script. Chaining is the price
    of not silently replacing a badge the user already had; `sto badge --off`
    puts it back and this disappears.
    """
    cmd = _json(Path.home() / ".claude" / "sto-ui.json", {}).get("statusline_chain")
    if not cmd:
        return ""
    import subprocess
    try:
        r = subprocess.run(cmd, shell=True, input=payload,
                           capture_output=True, timeout=5)
        return r.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


if __name__ == "__main__":
    # Claude Code runs this with a pipe, so Python picks the ANSI codepage and
    # `◆` blows up on cp1252. Writing the bytes ourselves sidesteps it.
    try:
        payload = sys.stdin.buffer.read()  # the session JSON Claude Code pipes in
    except OSError:
        payload = b""
    before = chained(payload)
    line = f"{before} {badge()}" if before else badge()
    sys.stdout.buffer.write(line.encode("utf-8"))
