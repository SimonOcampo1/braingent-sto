# Roadmap

What STO does not do yet, why it would matter, and the smallest thing that
would do it. Nothing here is committed work — it is the parking lot, ordered by
impact. Anything marked **gap** is something the alternatives already solve and
STO does not.

---

## 1. `sto mcp` — recall inside the session (**gap**)

**Today.** STO *moves* files. During a session Claude only sees what Claude Code
itself loads; it cannot ask the repo anything.

**Why.** This is the single feature that separates STO from
[claude-mem](https://github.com/thedotmack/claude-mem) and
[engram](https://github.com/Gentleman-Programming/engram): they answer questions
mid-session over 20 MCP tools; we answer none. It is also what makes every other
item here worth more — a memory nobody can query is a memory nobody reads.

**Sketch.** An MCP server over stdio is JSON-RPC on stdin/stdout: `initialize`,
`tools/list`, `tools/call`. That is stdlib (`json` + a read loop), ~150 lines,
no dependency. Registered in `.mcp.json` as `python scripts/mcp_server.py`.

Start with four tools, not twenty:

| tool | maps to |
|---|---|
| `memory_search(query, project?)` | the same lexical search as `sto memory search` |
| `memory_get(project/slug)` | the file, verbatim |
| `session_search(query)` | `srv.search_sessions` over every machine |
| `sync_status()` | ahead/behind/dirty, so the agent can say "push first" |

Engram's lesson worth copying: keep the tool surface small enough that the model
picks the right one, and make the description say *when* to call it. Their
20-tool surface needs a "Memory Protocol" snippet pasted into CLAUDE.md so the
model remembers to use it after compaction — that is a smell, not a feature.

---

## 2. Sync that reminds you, and can run itself

**Today.** Push and pull are manual. Nothing tells you the laptop has three days
of unsynced memories.

**Sketch (three levels, all opt-in, one pref each in `sto-ui.json`):**

- **Nudge.** The TUI already computes what would travel; when the count crosses
  a threshold or the last sync is older than N hours, say it plainly in the
  status bar instead of only colouring the button. Zero new machinery.
- **On session end.** A Claude Code `SessionEnd` hook running `sto push --quiet`
  when the tree is clean and something actually changed. The hook is a settings
  entry; the guard already exists (`sync_stage` returns the file list).
- **On a schedule.** A Windows Scheduled Task / cron entry calling `sto push`,
  installed by `sto autosync on --at 22:00`. The one hard rule: never auto-push
  a dirty working tree, and never auto-pull over one.

**Why it is not done yet.** Auto-push means committing on your behalf. It needs
the "what exactly went up" panel to be trustworthy first (it is, since the
progress panel landed) and a quiet mode that fails silently but leaves a log.

---

## 3. Cross-platform TUI

`msvcrt` is the only thing tying `sto ui` to Windows; the engine and the CLI are
already portable. A `termios`/`tty` branch behind the same `read_key()` /
`pending_keys()` contract is ~30 lines. For a public repo this is the difference
between "a Windows tool" and "a tool".

---

## 4. `sto doctor`

One command that checks: git remote and branch, both PowerShell profiles, Python
version, `ccusage` present, plugin parity, `.gitattributes` for `.jsonl`, and
whether `knowledge/` has ever been pushed. Every alternative ships one
(`engram doctor`, `ctx doctor`) because it is the first thing a stranger needs.

---

## 5. Automatic memory drafts

**Today.** Memories are written by Claude Code when the model decides to; the
vault is curated by hand. Nothing is distilled automatically.

**Sketch.** `dream_extract.py` already parses transcripts into prompts, tool
names and errors. A `SessionEnd` hook could write a *draft* note into
`vault/raw/` — never into `wiki/`, never into `knowledge/memory/`. Curation
stays human: the value of the vault is that a person decided it was worth
keeping.

---

## 6. `sto find` — one search across everything

Three commands search three corpora with three rankings (`sto search` for
sessions, `sto memory search`, and nothing for the vault). One command over all
three, grouped by source, with the ranking `search_sessions` already implements.

---

## 7. Memory conflicts, visible

`import_memory` skips a file when it diverged since the last push — correct, and
invisible. `sto memory conflicts` should list them and show the diff, and the
Memory tab should mark the row. Engram has the same problem and answers it with
`mem_judge`/`conflicts`; a diff is cheaper and truer.

---

## 8. Team mode

A second remote for a shared vault, separate from the personal repo: `sto push
--to team` pushing only `vault/wiki/`. The substrate already supports it — it is
a prefs entry and a pathspec, not an architecture.

---

## 9. Ship it as a plugin

`claude plugin marketplace add SimonOcampo1/sto-agenticos` is how people install
things now. A `.claude-plugin/marketplace.json` plus a plugin dir with the MCP
server entry (item 1) and the optional hooks (items 2 and 5) makes STO
installable in one command instead of a clone plus a PowerShell script.

---

## 10. Local embeddings

Deliberately last. Semantic recall only pays once something queries it (item 1)
and once there is enough in the repo for lexical search to miss things. Until
then it is infrastructure without a user, and it would drag in the first real
dependency.

---

## Not planned

- **A daemon.** The CLI imports the engine directly; the server is for the web
  app only. Nothing should need to stay running.
- **A database.** Plain files are the feature: readable, diffable, revertable.
- **A cloud service.** The remote is your git host. That is the whole point.
