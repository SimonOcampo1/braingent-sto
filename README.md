# STO agenticOS

**Your Claude Code brain — config, memory and sessions — living in one git repo you own.**

STO agenticOS turns a private git repository into the substrate that Claude Code is missing: your `~/.claude` config, your skills and plugins, the memories your agent writes, and the transcripts of every session, all synced between machines with two keystrokes. No daemon, no API key, no third-party service — a Python stdlib backend, `git`, and a terminal UI.

---

## Why it exists

Claude Code still has [no native way to sync config and skills across machines](https://github.com/anthropics/claude-code/issues/36693), and [no cloud sync for skills, settings and memory](https://github.com/anthropics/claude-code/issues/57678). The ecosystem answers with three separate families of tools:

| Need | Existing tools | What they leave out |
|---|---|---|
| Persistent memory | [claude-mem](https://github.com/thedotmack/claude-mem), [engram](https://github.com/Gentleman-Programming/engram), [agentmemory](https://github.com/rohitg00/agentmemory) | Config, skills and plugins stay on one machine; memory lives in a SQLite/vector store you can't read or diff |
| Config sync | [claude-sync](https://github.com/renefichtmueller/claude-sync), [claude-code-dotfiles](https://github.com/elizabethfuentes12/claude-code-dotfiles) | No sessions, no usage, no UI — sync and nothing else |
| Session browsing | [claude-code-log](https://github.com/daaain/claude-code-log), [claude-code-trace](https://github.com/delexw/claude-code-trace), [claude-history](https://github.com/raine/claude-history) | Local-only: what you did on the laptop is invisible from the desktop |

STO is the union of the three, on one substrate. Every artifact is **plain text in your own repo** — memories are markdown with frontmatter, sessions are trimmed and redacted JSONL, config is the real files. You can read them, `grep` them, edit them by hand, and roll them back with `git revert`.

---

## 🚀 Features

- **One repo, everything in it.** `sto push` exports sessions, memories, `~/.claude` modules and your vault, commits and pushes. `sto pull` applies them on the other machine — including installing missing plugins and marketplaces.
- **Modular sync.** Pick exactly which parts of `~/.claude` travel: `claude-md`, `settings`, `keybindings`, `skills`, `agents`, `hooks`, `plugins`. Memories, sessions and vault always travel.
- **Redaction on export.** Session transcripts are trimmed to what a reader needs (prompts, tool names, errors) and scrubbed of API-key-shaped strings before they ever hit a commit.
- **Terminal UI (`sto ui`).** Five tabs — Home, Sessions, Memory, Config, Help — over pure stdlib: `msvcrt` for keys, raw ANSI for pixels. No Ink, no `rich`, no dependencies. Alt screen, diff-based repaint, 2 KB of Python per frame.
- **Live push/pull progress.** Every step of a sync reports itself (`exporting sessions → staging → committing → pushing to origin`) with a spinner, instead of freezing the screen until git returns.
- **Memory graph.** A real graph of *your memories*: one node per memory, one per project, edges from `[[wikilinks]]`. Opens as a chrome-less window with a project/type/machine sidebar, click-to-inspect detail panel and search. Built from the same files the repo syncs, so it shows every machine and every session, not just this one.
- **Config parity at a glance.** The Home dashboard shows what is local-only, what is in the repo but not installed, and which plugins are missing on this machine.
- **Plan usage.** Live limit bars and the last days of token spend, straight from `ccusage` when it is installed.
- **Bilingual chrome.** English by default, Spanish one keystroke away — commands never change, only what they print.
- **Optional web app.** A React dashboard over the same backend, for when a terminal is not enough.

---

## 📂 Structure

```
sto-agentic-os/
├── scripts/
│   ├── sessions_server.py   # engine: sessions, memory, config sync, git — stdlib only
│   ├── cli.py               # `sto` — presentation over the engine
│   ├── ui.py                # the TUI: state + key → state, state → lines
│   ├── i18n.py              # every user-facing string, en/es
│   ├── memory_graph.html    # graph window template (canvas 2D, no CDN)
│   ├── dream_extract.py     # transcript parsing and redaction
│   ├── install_sto_cli.ps1  # installs the `sto` function into both PowerShell profiles
│   └── test_*.py            # the suite: no framework, no fixtures
├── app/                     # React + Vite dashboard (optional)
├── knowledge/               # what travels: sessions/, memory/, config/
├── vault/                   # curated knowledge: raw/ → wiki/ → outputs/
└── start.cmd                # double-click launcher: backend + app + `sto`
```

---

## 🛠️ Stack

- **Backend** — Python 3.11+, standard library only. No `pip install`, no virtualenv, no server to keep alive for the CLI: `cli.py` imports the engine directly.
- **Sync** — plain `git`. Your repo, your remote, your history. Conflicts are git conflicts, and you already know how to resolve those.
- **TUI** — `msvcrt` + ANSI escapes. Alternate screen buffer, per-line diffing, keyboard drain per frame.
- **Graph** — one HTML file, canvas 2D, hand-rolled force layout. Opens offline in a Chromium `--app` window.
- **App** — React 19, Vite 8, Tailwind 4, `react-force-graph` for the 2D/3D views.

---

## 💻 Setup

```bash
git clone https://github.com/<you>/sto-agentic-os.git
cd sto-agentic-os
powershell -ExecutionPolicy Bypass -File scripts/install_sto_cli.ps1
```

Open a new terminal and you have `sto`. Then point it at a repo of your own:

```bash
# 1. create an empty PRIVATE repo at github.com/new (no README)
git remote add origin git@github.com:<you>/<your-repo>.git
git push -u origin main
sto push
```

On every other machine: clone *your* repo, run `scripts/install_sto_cli.ps1` inside the clone, and `sto pull`. From then on `sto push` / `sto pull` — or `p` / `l` inside `sto ui` — keep both machines identical.

> Keep the repo **private**. It carries your session transcripts and memories.

Want the web app too? `start.cmd` installs the front-end dependencies, starts the backend and Vite, and opens the dashboard.

---

## Commands

| Command | What it does |
|---|---|
| `sto` / `sto status` | where sync stands: branch, ahead/behind, dirty |
| `sto push` / `sto pull` | export and upload / download and apply |
| `sto ui` | the terminal UI |
| `sto sessions [project]` | sessions, most recent first |
| `sto show <id>` | one transcript, through the pager |
| `sto search <text>` | full-text search across every session, every machine |
| `sto memory [project\|show\|search\|sync]` | the memories in the repo |
| `sto skills [id]` | installed skills, or one in full |
| `sto config` | which `~/.claude` modules are syncing |
| `sto machines` | the machines feeding the repo |
| `sto usage` | plan limits and recent spend |
| `sto graph [--memory\|--open\|<note>]` | memory graph window, repo graph, or a node's neighbours |

---

## What STO does not do

Honesty beats a feature matrix:

- **No embeddings, no semantic recall.** Search is lexical. If you want vector recall inside the agent loop, run [claude-mem](https://github.com/thedotmack/claude-mem) or [engram](https://github.com/Gentleman-Programming/engram) alongside it — they solve a different problem.
- **No MCP server.** The agent does not query STO at runtime; STO moves the files Claude Code already reads.
- **No automatic memory extraction.** Memories are written by the agent under your conventions, not distilled by a background job.
- **Windows-first.** The TUI needs `msvcrt` and the installer is PowerShell. The engine and CLI are portable; the terminal UI is not, yet.
- **Single user.** It syncs *your* machines. It is not a team knowledge base.

---

## What is next

The parking lot lives in [ROADMAP.md](ROADMAP.md): an MCP server so the agent can
query the repo mid-session, sync that reminds you (or runs itself), a
cross-platform TUI, and a few smaller things — each with the smallest sketch that
would do it.

## Tests

```bash
cd scripts
python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui.py
```

No framework, no fixtures, no mocks beyond swapping a function for a lambda. The TUI suite drives `handle()` and `draw()` directly, so it needs neither a terminal nor a pty.
