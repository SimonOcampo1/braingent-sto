#!/usr/bin/env python3
"""Where an agent keeps the things STO syncs.

STO is built on the native memory and setup of a coding agent — it does not
write memories, it moves the ones the agent already writes. That makes the
agent a *source of state*, not a host to install into, and this module is the
only place that knows the shape of one.

Everything else in the codebase asks for a directory and gets it. The whole
coupling to Claude Code lives in the table below; a second agent is another
entry, not a patch across the engine.

**This is a boundary, not a promise.** Only `claude-code` is supported today,
and nothing here claims otherwise: adding an entry declares where files live,
which is necessary and not sufficient — the transcripts still have to be a
format `dream_extract` can read. The point of the table is that a contributor
can see exactly what a new agent has to answer.

Prior art, both read for this (see `vault/wiki/`): engram keeps 12 agents in a
293-line declarative registry with a `custom` escape hatch for the awkward ones;
DeepSeek Harness isolates the same question in a 112-line `home-paths` package
with an env override. Both are install-oriented — *where do I write my MCP
config* — while ours is state-oriented: *where does this agent keep what I want
to carry*. Same shape, different fields.

One thing the research settled: `SKILL.md` plus YAML frontmatter inside a
`skills/` directory is a de-facto format across Claude Code, `dsh` and letta.
So `skills` below is a directory name, not a parser — which is why this file is
a table and not a plugin system.
"""
import os
from pathlib import Path

AGENT_ENV = "STO_AGENT"        # which entry of AGENTS to use
HOME_ENV = "STO_AGENT_HOME"    # absolute override, mostly for tests and CI

AGENTS = {
    "claude-code": {
        "label": "Claude Code",
        "dir": ".claude",          # under the user's home
        "skills": "skills",        # personal skill bundles, one dir each
        "plugins": "plugins",      # holds installed_plugins.json + the cache
        "projects": "projects",    # transcripts, one dir per project
    },
}

DEFAULT = "claude-code"


def active_slug() -> str:
    slug = os.environ.get(AGENT_ENV, "").strip()
    return slug if slug in AGENTS else DEFAULT


def active() -> dict:
    return AGENTS[active_slug()]


def label() -> str:
    """What the TUI puts next to a row. Today it always says the same thing,
    and that is the point: the column exists before the second agent does, so
    adding one is not also a redesign."""
    return active()["label"]


def home(slug=None) -> Path:
    """The agent's directory. `STO_AGENT_HOME` wins when set."""
    override = os.environ.get(HOME_ENV, "").strip()
    if override:
        return Path(override)
    return Path.home() / AGENTS[slug or active_slug()]["dir"]


def sub(key, slug=None) -> Path:
    """A named subdirectory of the agent's home: `skills`, `plugins`, `projects`."""
    return home(slug) / AGENTS[slug or active_slug()][key]
