# Roadmap

What STO does not do yet, why it would matter, and the smallest thing that would
do it. Nothing here is committed work — it is the parking lot. Items marked
**gap** are things the alternatives already solve and STO does not.

**The thesis all of it serves:** shared, cross-machine memories and knowledge
*plus* setup sync (skills, plugins, settings), free, over a private repo you own.
The agent-memory category is crowded; that combination is not.

---

## The loop we are aiming at

Out of the box, with nobody typing a command and nobody telling the agent to go
look:

1. **Claude writes a memory** — already happens. Claude Code's auto memory saves
   markdown into `~/.claude/projects/<repo>/memory/` when it judges something
   worth keeping. STO adds nothing here, and should not.
2. **It leaves the machine** — item **2**. A `SessionEnd` hook runs `sto push
   --quiet` when something changed and the tree is clean.
3. **It lands on the other machine** — item **2** from the other side: a
   `SessionStart` hook runs `sto pull --quiet` when behind, so the session opens
   with what the other machine learned.
4. **The agent sees it without being asked** — item **3**. Same-repo memories are
   already loaded natively (`MEMORY.md`, every session). What is missing is
   *cross-project and cross-machine* recall: a thin, budgeted block injected at
   session start.
5. **And can dig when it needs to** — item **1**. MCP tools over every memory,
   session and vault note in the repo.

Steps 2–5 are the whole gap. The rest of this list is polish around them.

---

## 1. `sto mcp` — recall inside the session (**gap**)

**Today.** STO *moves* files. During a session Claude only sees what Claude Code
itself loads; it cannot ask the repo anything.

**Why.** This is what separates STO from
[claude-mem](https://github.com/thedotmack/claude-mem),
[engram](https://github.com/Gentleman-Programming/engram) and
[agentmemory](https://github.com/rohitg00/agentmemory): they answer questions
mid-session, we answer none. A memory nobody can query is a memory nobody reads.

**Sketch.** An MCP server over stdio is JSON-RPC on stdin/stdout: `initialize`,
`tools/list`, `tools/call`. That is stdlib (`json` + a read loop), ~150 lines, no
dependency, launched as a short-lived subprocess. Registered through the plugin
(item 10) or `.mcp.json`.

Four tools, not twenty:

| tool | maps to |
|---|---|
| `memory_search(query, project?)` | the same lexical search as `sto memory search` |
| `memory_get(project/slug)` | the file, verbatim |
| `session_search(query)` | `srv.search_sessions`, across every machine |
| `sync_status()` | ahead/behind/dirty, so the agent can say "push first" |

Follow the **three-layer progressive disclosure** everyone converged on (engram,
claude-mem, agentmemory): search returns ids + snippets, a second call returns
context around a hit, only the third returns full text. The token budget is the
design constraint, not completeness.

Engram's lesson, in the negative: their 20 tools (agentmemory's 53) need a
"Memory Protocol" pasted into `CLAUDE.md` so the model remembers to use them
after compaction. A surface small enough not to need that is the better answer.

---

## 2. Sync that reminds you, and can run itself

**Today.** Push and pull are manual. Nothing tells you the laptop has three days
of unsynced memories.

**Sketch — four levels, all opt-in, one pref each in `sto-ui.json`:**

- **Nudge.** The TUI already computes what would travel; when the count crosses a
  threshold or the last sync is older than N hours, say it in the status bar
  instead of only colouring the button. Zero new machinery.
- **On session end.** A `SessionEnd` hook running `sto push --quiet` when the
  tree is clean and something actually changed.
- **On session start.** A `SessionStart` hook running `sto pull --quiet` when
  behind — this is what makes the other machine's memories already *be there*.
- **On a schedule.** `sto autosync on --at 22:00`, installing a Scheduled Task or
  a cron entry.

Hard rules for all four: never auto-push a dirty tree, never auto-pull over one,
always leave a log, and never block the session — queue and return, the way
claude-mem's `PostToolUse` hook queues observations instead of processing them
inline.

---

## 3. Automatic cross-project recall (**gap**)

**Today.** Native auto memory loads `MEMORY.md` for *the repo you are in*. What
you learned in another repo, or on the other machine, surfaces only if you
remember to ask.

**Sketch.** A `SessionStart` hook printing a small block that Claude Code injects
as context — the pattern claude-mem, agentmemory, Memori and
[memanto](https://memanto.ai/) all use ("brief the agent the moment it starts"),
except the source is plain files in your own repo:

```
## From your other work (STO)
- honda-frelife-bot/global-pause-feature — global pause: Config sheet, fail-open (LaptopA, 3d)
- sto-agentic-os/use-opus-for-design — prefers Opus for design passes (DeskB, 1w)
→ detail: memory_get, or `sto memory show <project>/<slug>`
```

Design constraints, in order:

- **Budgeted.** One line per memory, hard cap (~20 lines / 2 KB). It competes for
  the same context as `CLAUDE.md`; longer blocks get skimmed.
- **Ranked, not dumped.** Reuse `search_sessions`' ranking against the current
  repo name and recent prompts, recency as tiebreak.
- **Never full text.** The block is an index; detail comes from item 1.
- **Off by default until it earns trust**, and one pref to turn it off.

---

## 4. `sto bootstrap` — day one, not day zero

**Today.** A first `sto push` already carries **every** local memory: it walks
every `~/.claude/projects/*/memory/` directory, not only the repos you touched
this week. Sessions come too, capped at the 500 most recent and 10 MB per file.
So the migration mostly happens by itself — silently, and with caps nobody was
told about.

**Sketch.** An explicit first run:

- **Dry run first.** "Found 13 projects, 56 memories, 214 sessions (38 skipped:
  over 10 MB), 7 config modules. Push?" — the manifest the TUI already shows on
  confirm, before anything is committed.
- **Resolve dormant projects.** A project whose sessions were pruned by
  `cleanupPeriodDays` but whose `memory/` survived cannot name itself;
  `_slug_project` writes a `.sto-project` marker when it can. Bootstrap should
  resolve and write those markers up front, so old memories arrive under the
  right project instead of a raw slug.
- **`--all-sessions`** to lift the 500 cap for the first push, when you do want
  the whole history.
- **Adopt, don't invent.** `~/.claude/CLAUDE.md`, rules, skills and plugins are
  already covered by the config modules; bootstrap only has to say so and let you
  untick what should stay local.

---

## 5. Cross-platform TUI

`msvcrt` is the only thing tying `sto ui` to Windows; the engine and the CLI are
already portable. A `termios`/`tty` branch behind the same `read_key()` /
`pending_keys()` contract is ~30 lines. For a public repo this is the difference
between "a Windows tool" and "a tool".

---

## 6. `sto doctor`

One command checking: git remote and branch, both PowerShell profiles, Python
version, `ccusage` present, plugin parity, `.gitattributes` for `.jsonl`, whether
`knowledge/` was ever pushed, and whether the hooks from item 2 are installed.
Every alternative ships one (`engram doctor`, `bm doctor`) because it is the
first thing a stranger needs.

---

## 7. The public repo as a product: README, banner, CI

For a tool nobody has heard of, the README *is* the product. In impact order:

**1. A terminal recording.** The single highest-return asset for a TUI project,
and the one thing no screenshot replaces. Script it with
[vhs](https://github.com/charmbracelet/vhs) (a `.tape` file is reproducible and
re-recordable when the UI changes) or asciinema + `agg`. One take, under 20
seconds: switch tabs → `p` → the confirmation manifest → the progress panel
ticking → `g` on the Memory tab → the graph window. It goes right under the
pitch, above every table.

**2. A banner that is ours.** The wordmark already exists: the Block Elements
`STO` glyphs the TUI paints. Trace it to SVG in the accent palette, and serve
light/dark with `<picture>` + `prefers-color-scheme` so it does not sit on a
white slab in light mode. A banner drawn from the app's own typography beats any
generator. Keep the SVG in `docs/` and never inline a raster.

**3. Four badges, all true.** `license MIT`, `python 3.11+`, `dependencies: 0`,
`tests: N passing`. One row, right under the banner. The tests badge only after
the CI in point 5 exists — a build badge that runs nothing is noticed and it
costs credibility.

**4. Above the fold, in this order.** Banner → one-sentence pitch → three-command
quickstart → GIF. Nothing else. The comparison table, "what it does not do" and
the command reference all move below, and the long ones fold into `<details>` so
the page stays scannable.

**5. CI.** A GitHub Action running the four suites on push. It makes the badge
honest and catches a broken `ui.py` before someone else clones it.

**6. A screenshot of the memory graph.** Wide, dark, detail panel open, filters
visible. It is the most distinctive thing on screen and the hardest to imagine
from prose.

**7. Repo metadata.** Description, topics (`claude-code`, `agent-memory`,
`dotfiles-sync`, `tui`, `knowledge-management`), and a social preview image —
without them the repo is invisible in search and ugly when linked.

**8. LICENSE** — MIT, done. Without one, "public" legally means all rights
reserved.

---

## 8. `sto find` — one search across everything

Three corpora, three commands, three rankings (`sto search` for sessions, `sto
memory search`, nothing for the vault). One command over all three, grouped by
source. [basic-memory](https://github.com/basicmachines-co/basic-memory)'s design
is the one to copy: **markdown stays the source of truth, the index is derived** —
a `sqlite3` FTS5 table under `.sto-cache/`, rebuilt from files, deletable at any
time without losing anything. `sqlite3` with FTS5 is in the standard library, so
this stays dependency-free.

---

## 9. Memory conflicts, visible

`import_memory` skips a file when it diverged since the last push — correct, and
invisible. `sto memory conflicts` should list them with the diff, and the Memory
tab should mark the row.

Worth stealing from [graphiti](https://github.com/getzep/graphiti): resolve
contradictions by **invalidation, not deletion**. A superseding memory writes
`supersedes: <slug>` in its frontmatter; the old file stays and the graph dims
it. Git keeps the history anyway — this makes it legible without digging.

---

## 10. Ship it as a plugin

`claude plugin marketplace add SimonOcampo1/sto-agentic-os` is how people install
things now. A `.claude-plugin/marketplace.json` plus a plugin dir carrying the
MCP server (item 1) and the optional hooks (items 2 and 3) makes STO installable
in one command instead of a clone plus a PowerShell script.

---

## 11. Memory drafts and curation

**Today.** Memories are written by Claude Code, the vault is curated by hand, and
nothing is distilled.

**Sketch.** `dream_extract.py` already parses transcripts into prompts, tool names
and errors. A `SessionEnd` hook can queue a *draft* into `vault/raw/` — never into
`wiki/`, never into `knowledge/memory/`. Then `sto curate` walks the drafts and
proposes, per item, one of mem0's four verbs: **ADD / UPDATE / DELETE / NOOP**.
That vocabulary is the useful part of their pipeline, and it works fine with a
human pressing the key instead of an LLM deciding alone.

Engram's **topic key** belongs here too: one evolving file per topic, updated,
instead of five near-duplicates. Our frontmatter `name` already is that key —
`sto memory merge <a> <b>` would make it usable.

---

## 12. A web UI as a first-class surface

**Today.** `app/` exists (React + Vite over the same endpoints) but the TUI is
where the work went, and the app lags behind it: no memory graph parity, no
progress panel, no config parity view.

**Why revisit.** [memanto](https://memanto.ai/) is the reference for how good this
can look, and it makes the case that a local dashboard (`127.0.0.1/ui`) is a
legitimate primary surface, not a toy. A terminal is the right home for `push`;
it is the wrong home for *browsing* three hundred memories.

**What to take from the field:**

- **A local dashboard, not a service** — same posture as the TUI: it reads your
  repo, it does not phone anywhere.
- **Memory categories** — memanto ships 13 semantic categories; Claude Code's
  frontmatter already has `type` (user / feedback / project / reference). Colour
  and filter by it, in the graph and in the list.
- **Provenance** — memanto distinguishes what the user said from what the agent
  inferred. We can show something better and cheaper: which machine wrote it,
  when, and the commit that brought it in.
- **The live stream** — claude-mem's viewer shows observations arriving in real
  time over SSE. The backend is already an HTTP server; "saved 2 memories" as a
  live feed is a small addition.
- **Timeline over graph, sometimes** — the graph answers "what connects to what";
  a timeline answers "what did I learn this week", which is the question people
  actually ask.

Ordering note: this is worth doing **after** items 1–3. A pretty browser over a
loop that still needs manual syncing is polish on the wrong end.

---

## 13. Team mode

A second remote for a shared vault, separate from the personal repo: `sto push
--to team`, pushing only `vault/wiki/`. The substrate already supports it — a
prefs entry and a pathspec, not an architecture.

---

## 14. Local embeddings

Deliberately last. Semantic recall only pays once something queries it (item 1)
and once lexical search visibly misses things. Until then it is infrastructure
without a user, and the first real dependency.

When it happens, the shape to copy is **hybrid retrieval with rank fusion**
(agentmemory, mem0): BM25 + vectors + graph neighbours merged by Reciprocal Rank
Fusion, not vectors alone. Two of those three signals — lexical and the wikilink
graph — already exist here.

---

## Ideas worth stealing

Distilled from reading the field. Each row is a mechanism, not a dependency.

| Idea | Seen in | Our version |
|---|---|---|
| Three-layer progressive disclosure (ids → context → full text) | engram, claude-mem, agentmemory | shapes the MCP tools (1) and the injected block (3) |
| Brief the agent the moment it starts | memanto, claude-mem, Memori | the `SessionStart` block, budgeted and ranked (3) |
| Hooks that **queue** instead of processing inline | claude-mem (`PostToolUse` → pending table) | drafts and auto-push queue to a file, processed on the next `sto` run (2, 11) |
| ADD / UPDATE / DELETE / NOOP as the curation vocabulary | mem0 | `sto curate` proposes, you press the key (11) |
| Topic key → upsert one evolving memory | engram | frontmatter `name` + `sto memory merge` (11) |
| Invalidate, do not delete, on contradiction | graphiti, memanto | `supersedes:` in frontmatter, dimmed in the graph (9) |
| Markdown is the source of truth, the index is derived | basic-memory | FTS5 cache under `.sto-cache/`, rebuildable (8) |
| `[category] content #tags` observations inside notes | basic-memory | a light convention that makes the graph richer than wikilinks alone |
| Semantic categories as a first-class filter | memanto (13 categories) | `type` already exists in the frontmatter — colour and filter by it (12) |
| Hybrid retrieval with rank fusion | agentmemory, mem0 | lexical + graph now, vectors later (14) |
| Scoping keys (user / agent / app / run) | mem0 | we already scope by project + machine + type; stop there |
| Live stream of what was just saved | claude-mem viewer | over the existing HTTP endpoints (12) |
| Background augmentation off the hot path | Memori | anything expensive runs on the next push, never in the session |
| P2P mesh sync | agentmemory | **skip** — git is the mesh, and it is free |
| 20–53 MCP tools | engram, agentmemory | **skip** — a surface that needs a protocol snippet to be remembered is too big |
| An LLM in the write path | claude-mem, mem0, Memori | **skip** — Claude Code already writes the memory, for free |

---

## Prior art: where memories come from

|  | Who writes the memory | Where it lives | Recall |
|---|---|---|---|
| **Claude Code (auto memory)** | Claude itself, when it judges something worth keeping | `~/.claude/projects/<repo>/memory/*.md`, plain markdown | `MEMORY.md` index loaded every session (first 200 lines / 25 KB); topic files on demand |
| **STO** | nobody new — it syncs the files above | the same files, mirrored into `knowledge/memory/<project>/<machine>/` | what Claude Code already does, plus `sto memory search` and the graph |
| **[engram](https://github.com/Gentleman-Programming/engram)** | the agent, calling `mem_save` | its own SQLite (FTS5) | 20 MCP tools; a protocol snippet in `CLAUDE.md` to survive compaction |
| **[claude-mem](https://github.com/thedotmack/claude-mem)** | hooks, distilling the session with an LLM | its own SQLite + Chroma vectors | injected at session start; 4 MCP search tools |
| **[agentmemory](https://github.com/rohitg00/agentmemory)** | 12 lifecycle hooks + LLM compression | its own store | BM25 + vector + graph fused by RRF; 53 MCP tools |
| **[mem0](https://github.com/mem0ai/mem0)** | LLM extraction over the conversation, single pass | vector + graph store | semantic + BM25 + entity matching, temporal reasoning |
| **[Memori](https://github.com/MemoriLabs/Memori)** | wraps the LLM client, captures every call | SQL (Postgres/MySQL/SQLite) + embeddings | `Recall` with a relevance threshold, injected into the next prompt |
| **[memanto](https://memanto.ai/)** | its own pipeline, no tokens on write | managed or on-prem service | sub-100 ms semantic recall, 13 categories, conflict resolution |

STO is the only one **built on the native memory** instead of beside it: nothing
new writes memories, nothing has to be taught to the model, and there is no
second store to keep in sync with the first. Anthropic's docs are explicit that
auto memory is machine-local — "files are not shared across machines or cloud
environments" — and that is the hole this fills.

The corollary is the ceiling: native recall is an index in context plus Claude
opening files. No vectors, no cross-project search, and the index is capped.
Items 1 and 3 raise it without a second store; item 14 goes past it, if ever.

---

## Naming

`agenticOS` is aspirational and slightly wrong: there is no scheduler, no
processes, no sandbox. What there *is* is continuity — your setup and your memory
keep existing on the other machine — plus a control plane over both. The name
should say that, not operating system.

Two tests any candidate has to pass:

- **Does it cover both halves?** Memory *and* setup (skills, plugins, settings).
  A name that only says memory sells half the product, and the memory half is the
  crowded one.
- **Is the metaphor already taken?** `claude-sync` ships under "one Claude brain
  across all your devices"; "second brain" belongs to the PKM world. Walking into
  someone else's metaphor makes you sound like their clone.

Candidates:

| Name | Covers both halves | Free metaphor | Note |
|---|---|---|---|
| **STO Continuum** | yes — continuity of *everything* | yes | says the value, promises no kernel |
| **STO Control Plane** | yes | yes | precise, cold, infrastructural |
| **STO Carryover** / **STO Relay** | yes | yes | shorter, less solemn |
| **STO BrainKit** | yes — brain = memory, kit = the setup | yes | keeps the warmth of "brain" and adds the half it was missing |
| **STO Portable Brain** | yes, by saying it | yes | explicit; the name *is* the tagline, at the cost of length |
| **STO Brainstem** | yes — the brain plus the wiring | yes | evocative, slightly clinical |
| **STO Agentic Brain** | no — brain ≠ skills/plugins | no — `claude-sync`'s tagline | warm and instantly readable, which is worth something |
| **STO Brain** | no | no | same, minus the filler adjective; "agentic" adds no information |
| keep **agenticOS** | yes, vaguely | crowded | free: the repo is already public under it |

The trap the "brain" family walks into: **memory is the crowded half**. Eight
projects do agent memory; the thing none of them does is carry the *setup* — the
skills, plugins and settings — in the same private repo. A name that says brain
and nothing else sells the half you would have to win on someone else's turf. The
fix is not to drop the metaphor, it is to pair it with the other half
(`BrainKit`) or to state the portability outright (`Portable Brain`).

Implementation note if the name changes: keep the TUI wordmark as plain `STO`.
`WORDMARK` is hand-built Block Elements glyphs and only `S`, `T` and `O` exist —
any new word means drawing a new glyph set by hand, for a banner nobody asked to
change. The command stays `sto` in every case.

Whatever wins, the tagline carries the weight: *shared memory and setup for
Claude Code, across your machines, in a repo you own.*

---

## Not planned

- **A daemon.** The CLI imports the engine directly; the server is for the web app
  only. Nothing should need to stay running.
- **A database as the source of truth.** Plain files are the feature: readable,
  diffable, revertable. A derived index is fine (item 8); a store is not.
- **A cloud service.** The remote is your git host. That is the whole point.
