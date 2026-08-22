#!/usr/bin/env python3
"""Dreaming job extractor: distill recent Claude Code sessions for STO.

Deterministic preprocessing. Finds Claude Code .jsonl transcripts modified since
the last successful run, extracts cheap signal (user prompts, tool names, errors),
and writes a small distilled.txt. Kept as the session-parsing library for STO
(the Hermes dreaming runner was removed 2026-07-17).

Usage:
  python dream_extract.py              # guard + distill (prints a STATUS line)
  python dream_extract.py --mark-done  # record today as the last successful run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path

import agents

HOME = Path.home()
HERMES_HOME = Path(os.environ.get("HERMES_HOME", HOME / "AppData" / "Local" / "hermes"))
PROJECTS_DIR = Path(os.environ.get("DREAM_PROJECTS_DIR", agents.sub("projects")))
STATE_DIR = Path(os.environ.get("DREAM_STATE_DIR", HERMES_HOME / "dreaming"))
MARKER = STATE_DIR / "last_run"
OUT = STATE_DIR / "distilled.txt"
MAX_SESSIONS = 40
MAX_CHARS = 24000  # ponytail: token ceiling; raise or summarize-per-session if it bites

# Secrets can appear in pasted prompts; the digest is git-pushed, so mask them.
# ponytail: covers the key shapes we actually handle; widen if a new one leaks.
_SECRET_RE = re.compile(
    r"sk-[A-Za-z0-9-]{20,}"
    r"|AQ\.[A-Za-z0-9._-]{20,}"
    r"|AIza[A-Za-z0-9_-]{30,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
)


def _redact(s):
    return _SECRET_RE.sub("[REDACTED]", s)


def parse_lines(lines):
    """Extract cheap signal from one session's .jsonl lines.

    Returns {"prompts": [str], "tools": Counter, "errors": int, "cwd": str|None}.
    Skips malformed JSON and slash-command/caveat noise.
    """
    prompts, tools, errors, cwd = [], Counter(), 0, None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue  # malformed line → skip, keep going
        if cwd is None and isinstance(o.get("cwd"), str) and o["cwd"]:
            cwd = o["cwd"]
        msg = o.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if o.get("type") == "user" and isinstance(content, str):
            s = content.strip()
            if s and not s.startswith("<"):  # filter slash-command/caveat wrappers
                prompts.append(_redact(s))
        elif o.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name"):
                    tools[b["name"]] += 1
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    errors += 1
    return {"prompts": prompts, "tools": tools, "errors": errors, "cwd": cwd}


def build_distilled(sessions, max_chars=MAX_CHARS):
    """Render per-project signal to compact markdown, capped at max_chars.

    sessions: list of (project_name, data) most-recent-first. The whole text is
    truncated to max_chars (most-recent content survives), with a marker appended.
    """
    out = []
    for project, data in sessions:
        block = [f"## {project}"]
        if data["prompts"]:
            block.append("Prompts:")
            block += [f"- {p[:200]}" for p in data["prompts"]]
        if data["tools"]:
            block.append("Tools: " + ", ".join(f"{k}({v})" for k, v in data["tools"].most_common()))
        if data["errors"]:
            block.append(f"Errors: {data['errors']}")
        out.append("\n".join(block) + "\n\n")
    text = "".join(out).strip() + "\n"
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + f"\n[truncated: {max_chars} char cap reached]\n"
    return text


def read_marker(path=MARKER):
    try:
        return date.fromisoformat(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def ran_today(path=MARKER, today=None):
    return read_marker(path) == (today or date.today())


def mark_done(path=MARKER, today=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((today or date.today()).isoformat(), encoding="utf-8")


def find_sessions(since, projects_dir=PROJECTS_DIR, max_sessions=MAX_SESSIONS):
    """Return (project_name, path) for .jsonl with mtime >= since (or all if
    since is None), most-recent-first, capped to max_sessions."""
    if not projects_dir.exists():
        return []
    files = []
    for p in projects_dir.rglob("*.jsonl"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if since is None or mtime >= since:
            files.append((mtime, p))
    files.sort(reverse=True)
    return [(p.parent.name, p) for _, p in files[:max_sessions]]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mark-done", action="store_true",
                    help="record today as the last successful run")
    args = ap.parse_args(argv)

    if args.mark_done:
        mark_done()
        print("MARKED", date.today().isoformat())
        return 0

    if ran_today():
        print("ALREADY_RAN")
        return 0

    marker = read_marker()
    since = datetime.combine(marker, time.min).timestamp() if marker else None
    found = find_sessions(since)
    if not found:
        print("NO_NEW_SESSIONS")
        return 0

    agg, order = {}, []
    for project, path in found:
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                data = parse_lines(fh)
        except OSError:
            continue
        if project not in agg:
            agg[project] = {"prompts": [], "tools": Counter(), "errors": 0}
            order.append(project)
        agg[project]["prompts"] += data["prompts"]
        agg[project]["tools"] += data["tools"]
        agg[project]["errors"] += data["errors"]

    distilled = build_distilled([(p, agg[p]) for p in order])
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(distilled, encoding="utf-8")
    print(f"DISTILLED sessions={len(found)} projects={len(order)} out={OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
