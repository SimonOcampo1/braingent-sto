# Simpler UI: one vocabulary, a Go TUI, a quieter band

Date: 2026-11-11. Status: approved in brainstorming, pending implementation plan.

## Why

The TUI and the sto-band speak git (`push`, `pull`, `fetch`, `ahead/behind`,
`repo`) plus internal words (`keep`, `bring`, `forget`, `parity`, modules). A
user who cloned braingent-sto without knowing git has no mental model to read
them with, and the owner finds them confusing too: `chats ↑2 ↓51` next to
`repo ↑1 ↓0`, three sync buttons, `no path`.

On top of that the Textual TUI is slow to start (import + three serial load
phases), hard to maintain (`tui_app.py` 2185 lines, `.tcss`, custom widgets,
dock bugs), needs `uv`/`textual` to run, and feels unlike gitboard, the Go TUI
whose patterns the owner prefers.

## Goals

1. One vocabulary for TUI, band and CLI, understandable without git.
2. Replace the Textual TUI with a Go + Bubble Tea v2 TUI in the gitboard idiom,
   with mouse support (click and wheel).
3. Simplify the sto-band to one state and one button.

## Non-goals

- Rewriting the engine. Sync, git, export and `~/.claude` stay in Python.
- New features. Anything not listed here is out.
- Keeping Textual as a fallback once the Go TUI reaches parity.

## 1. Concept model

**Two places.**
- *This machine*: the machine icon and name, as today.
- *The cloud*: the user's private GitHub repo. The word "repo" appears only in
  Settings and Help ("The cloud is your GitHub repo: ...").

**One main verb: `Sync`** (`Sincronizar`).
- Sync = bring down, apply to `~/.claude`, export, send up. It replaces the
  separate `p` / `l` / `f` actions.
- `bring down only` and `send up only` stay as advanced actions, listed under
  `?`, not in the footer.
- `fetch` disappears from the UI: it runs in the background.
- `update` is no longer next to sync. When a new braingent version exists, a
  notice says so with its own action ("New braingent version -> update").
- In the TUI, Sync shows one summary first ("you will bring X, send Y"); `Enter`
  confirms. This replaces the two separate push/pull manifests. Auto runs from
  the band never ask.

**One state, as a phrase.**
- `Up to date` or `51 new in the cloud · 2 to send`, summing chats, memories
  and config. Expanding it (click or key) shows the breakdown by kind and by
  machine.
- Commit-level `ahead/behind` is no longer shown anywhere; it is implementation
  and is already counted in the phrase.

**Four item states**, each with a fixed symbol and the same words everywhere. Symbols are
arrows, geometric shapes and Latin-1 only: `test_no_pictographs_in_the_source` forbids
U+2600-27BF (check marks, warning signs).

| today | new |
|---|---|
| in both | `● synced` |
| only here / local only | `↑ only on this machine` (goes up on Sync) |
| only in the repo / in repo, not installed | `↓ only in the cloud` -> action `bring` |
| dropped in the repo | `× deleted in the cloud` -> `delete here` or `send again` |

**Item verbs:** `bring`, `delete from this machine`, `remove from the cloud`,
`keep full chat` (explained: "so another machine can resume it").

**Paths:** "path" becomes *"Project folder on this machine"*. `no path`
becomes `! this project has no folder here — without it you can't resume its
chats` with the action `choose folder`.

All strings live in `scripts/i18n.py`, English and Spanish, as today. The Go
TUI receives the labels it needs from the engine (see 2), the way the band
already does, so there is still one place for strings.

## 2. Bridge between the Go TUI and the engine

The Go TUI runs `sto ... --json` as a subprocess. Same contract the band
already uses (`sto mod status`), so band and TUI read the same numbers from the
same functions and cannot disagree.

- New `sto data <view>` returning JSON, built from the existing `ui_data.py`
  functions: `status` (the state phrase, its breakdown, update notice, plan
  usage), `chats`, `memories`, `tools` (skills, plugins, config modules with
  their item state), `settings`, `search --q <text>`, `detail <kind> <id>`.
  Each response carries the labels it needs, in the configured language.
- Actions (`sync`, `bring`, `delete`, `remove-from-cloud`, `keep`,
  `set-folder`, settings changes) are `sto act <verb> ...` returning JSON.
  Long ones (`sync`) stream one JSON object per line on stdout:
  `{"step": "bringing chats"}` ... `{"done": true, "message": ...}` or
  `{"error": ...}`. The band uses the same stream for its progress text.
- Never a traceback on stdout: errors are `{"error": ...}`, like `cmd_mod`.
- The TUI paints its frame immediately and loads each view lazily, in
  parallel goroutines. No serial load phases.
- Rejected: talking HTTP to `sessions_server.py` (server lifecycle, port, more
  pieces for a public user) and reading files directly from Go (duplicates
  rules such as item state and path tokenizing).

## 3. TUI layout and navigation

```
 braingent   Chats 120   Memories 48   Tools 31   Settings          ↓51 ↑2  [Sync]  ⌂ sto-pc
 ─────────────────────────────────────────────────────────────────────────────────────────────
 my-agentic-os · 42 ────────────────────────────┬─ Fix sync timeout ──────────────────────────
 › Fix sync timeout        sto-pc     2h ago     │ ● synced
   TUI redesign            sto-nb     yesterday  │ Project          my-agentic-os
                                                 │ Folder here      ~/repos/my-agentic-os
 gitboard · 7 ──────────────────────────────────│ Machine          sto-pc · 34 prompts
   Sort on s               sto-pc     5 nov      │
                                                 │ [Resume here]  [Keep full chat]
 ─────────────────────────────────────────────────────────────────────────────────────────────
 ↵ open  r resume  / search everything  s sort  b group  ? more                5h 34% · wk 61%
```

- **No home screen.** The wordmark goes; "braingent" stays small in the header.
  The TUI opens on Chats.
- **Header:** clickable tabs with their count and no number prefix (gitboard
  lesson), the sync state always visible, the `Sync` button, the machine.
  `Up to date` is dim; pending arrows use the accent. Clicking the arrows opens
  the breakdown.
- **Tabs:** Chats · Memories · Tools (skills, plugins, config modules) ·
  Settings. Help stops being a tab and becomes `?`.
- **Levels become groups.** Today: project -> list -> detail with `Enter` /
  `Esc`. Now: one flat list grouped by project (`b` toggles), group titles as
  in gitboard, cursor skips titles and blank lines.
- **The sidebar is where things are explained.** Each item shows its state
  with the phrase from section 1 and its actions as clickable buttons. That is
  the onboarding for new users; no separate tutorial.
- **One global search, `/`, from any tab.** No per-view filter. Results have a
  "kind" column, current tab's results first; `Enter` jumps to the item in its
  tab; `Esc` closes.
- **Reader:** `Enter` on a chat or memory opens it full screen (Glamour for
  markdown); `Esc` goes back.
- **Footer:** one line, the view's keys first, `?` expands all; plan usage on
  the right.
- **Mouse:** click on tabs, rows, buttons and the state arrows; wheel scrolls
  the list and the sidebar.
- **Responsive** as gitboard: columns hide by per-view priority, the header
  compacts, the sidebar opens only when there is room.
- **Look:** same configurable accent, dark/light ground from Settings, same
  general lines as today.

## 4. sto-band

```
braingent  ↓51 ↑2  [Sync]               5h 34% · wk 61% · ctx 12%
braingent  up to date                   5h 34% · wk 61% · ctx 12%
braingent  syncing… bringing chats
braingent  ! couldn't sync: no connection  [retry]
```

- **One state, one button.** The number is the global pending count (same as
  the TUI header) plus this project's chats waiting to be kept or brought,
  because the band's Sync handles those (what `mod_sync` does today: pull,
  keep/bring this project's chats, push). `Sync` appears only when something
  is pending.
- `repo ↑↓` goes (section 1).
- `no path` goes: the band runs in the project's `cwd`, so `sto mod status`
  saves that folder as the project folder for this machine. The remaining case
  (a project with no folder here) belongs to the TUI.
- **Auto** is no longer a button. On by default (bring down on session start,
  quiet sync every 30 min). Turned off with `/sto auto` or from TUI Settings.
  When off, a dim clickable `auto: off` shows.
- Progress in words during sync, from the stream in section 2.
- Commands: `/sto` (state in one phrase), `/sto sync`, `/sto auto`. `/sto mem`
  goes; auto and Sync cover it.
- Plan usage stays as today.

## 5. Distribution

- Go code in `tui/` of the public clone, its own Go module. The engine is not
  touched by it.
- `sto ui`: runs the binary built for the current version if present; else, if
  `go` is installed, `go build` once into `~/.cache/braingent/`; else downloads
  the prebuilt binary from the GitHub Release for the current tag (an Action
  builds linux/mac/windows on each tag).
- When the Go TUI reaches parity, `tui_app.py`, `tui_widgets.py`,
  `tui_app.tcss`, `test_tui_app.py` and the `uv`/`textual` path in `cmd_ui` are
  deleted.

## 6. Order of work

1. **Vocabulary + JSON contract.** New strings in `i18n.py`, `sto data` and
   `sto act` with tests in `test_cli.py` / `test_ui_data.py`. The Textual TUI
   keeps working meanwhile.
2. **Band.** Rewrite `register.tsx` on the new status and stream; update
   `band.test.tsx`. First real user of the new vocabulary.
3. **Go TUI.** First step: verify mouse hit-testing in Bubble Tea v2
   (`bubblezone` if v2-compatible, otherwise a small rectangle registry of our
   own). Then header + Chats, then the other tabs, search, reader, sync flow.
4. **Distribution + deletion.** Release Action, `sto ui` launcher, delete
   Textual.

## 7. Testing

- Python: every `sto data` view and `sto act` verb has a test asserting the
  JSON shape and that errors never leak a traceback; the sync stream ends with
  exactly one `done` or `error` line.
- Band: `band.test.tsx` covers up to date, pending, syncing, error, auto off.
- Go: unit tests for the pure parts (state phrase rendering, grouping, column
  hiding, hit-testing); the subprocess bridge tested against a fake `sto`
  script that prints canned JSON.
- Manual: run in tmux at 80, 120 and 200 columns; click every tab, button and
  row; sync end to end between sto-pc and sto-notebook.

## Open points for the plan

- Exact `sto data` / `sto act` JSON field names.
- Whether `bubblezone` supports Bubble Tea v2 (decides step 3's first task).
- Release Action details (tag naming, binary naming per OS/arch).

## 8. Prototype verdict (2026-11-11)

Three layouts of the Chats screen were tried on real data (`sto data`), then a
fourth that merges two. Code: branch `prototype/go-tui`, `tui-prototype/main.go`
(throwaway; run `cd tui-prototype && go run .` from a project folder).

The winner is **D: section 3's layout plus a state card**:

- Header as section 3 (tabs with counts, arrows, machine) but **without the
  `Sync` button**: it lives only in the card, twice was redundant.
- One blank line, then a bordered **state card** across the width: the phrase
  plus the `Sync` button, the breakdown (`↑ 1 memories` ...) on one line, a dim
  line `N chats in the cloud you can bring  →` (jumps to Chats filtered by ↓),
  and the update notice when there is one.
- One blank line, then the grouped list with the sidebar on the right.
- **Margins:** 1 line above and below, 2+ columns on each side, content width
  capped at 150 columns and centered. Without them it read as cramped and
  overwhelming.
- **Group titles** say what they are: `my-agentic-os  ·  128 chats  ·  you are
  here ────`; only the project of the current folder carries `you are here`.
- Rows: 4 columns of air between the title and the machine.

**The header number counts only what Sync moves.** On real data the Chats tab
had 175 chats not in sync (171 ↓ old chats only in the cloud, mostly pruned by
Claude Code or from the other machine; 4 ↑). Sync must not bring 171 old chats
into `~/.claude`, so: the number and `Sync` count memories, config, skills and
the ↑ chats to send; the ↓ chats are the separate dim line in the card and are
brought by hand (one, or a whole project). `status_data` needs that mode for the
TUI (today, without `--cwd`, it counts no chats at all; with it, only that
project's).
