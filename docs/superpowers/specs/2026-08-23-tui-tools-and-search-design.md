# The Tools tab, global search, and markdown

Sub-project **C** of the Textual TUI pass. Three of the twelve items: a global
search that actually searches (3), the Skills tab becoming a Tools tab that
reaches every config module (5), and markdown rendered as markdown (8).

Files: `scripts/tui_app.py`, `scripts/tui_widgets.py`, `scripts/tui_app.tcss`,
`scripts/ui.py`, `scripts/i18n.py`. One of those is not the TUI, and that is
deliberate — see **Where the search lives**.

---

## 1. Global search

### What is there today

The home has a search box that does nothing but hand its text to the Sessions
tab. The rest is scattered:

| corpus | what exists | quality |
|---|---|---|
| sessions | `srv.search_sessions(q, rows=)` | ranked, typo-tolerant, searches prompt bodies |
| memories | inline in `cli.py`'s `memory search` | substring, no ranking, not a function anyone can call |
| tools | nothing | — |
| vault | nothing | — |

### Where the search lives

**In `ui.py`, not in `tui_app.py`.** The rule the project already keeps is that
nothing in a TUI flavour recomputes a rule, so the two flavours cannot disagree
about an answer. A ranking written inside the Textual app would be a second
ranking the CLI cannot use, and it would have to be written a third time for
`sto find` — which is item 8 of the ROADMAP and is exactly this function.

So: `ui.search_all(q, limit=40) -> list[dict]`, and the TUI only decides how the
hits look.

### The cost, measured

Against the private clone's real volume (187 sessions, 101 memories, 43 vault
notes, 58 tool items), one uncached search costs:

| corpus | cost |
|---|---|
| vault notes | **0.437 s** |
| tool items (`module_items` x7) | 0.256 s |
| sessions | 0.102 s |
| memories | 0.031 s |
| **total** | **~0.83 s** |

Per keystroke that is unusable. Two things fix it, and neither is a new
dependency:

**An index, keyed by mtime.** `ui._INDEX` maps a path to `(mtime, lowercased
text)`. A rebuild only reads the files whose mtime moved, so the first search of
a session pays the half second and every one after it is a scan of strings
already in memory. This is the same shape as `cached_sessions`, which the repo
already trusts, and the same principle as the ROADMAP's note on
basic-memory: **markdown stays the source of truth, the index is derived** and
can be thrown away at any time.

It covers memories and vault notes — the two corpora that are files nobody else
indexes. Sessions are **not** in it: `srv.search_sessions` already keeps
`_PROMPTS_INDEX`, and a second copy of the prompt bodies is a second thing to
keep true. Tool items are not text at all; `module_items` is cached whole,
keyed by the mtimes of the module directories, because 0.256 s of directory
walking per keystroke is the same problem in a different shape.

**A debounce.** `Input.Changed` fires per keystroke; the search runs 200 ms
after the last one. `search_sessions` is 0.1 s even warm, because `difflib` is
doing real work, and a tenth of a second of frozen keyboard on every letter is
the difference between a search box and a stutter.

No thread. With the index warm the whole thing is one `difflib` pass, and the
debounce means it happens when you stop typing. If that ever stops being true,
the worker pattern is already in the file.

### Ranking

One score, so four corpora can be merged into one list. Where the term hits
matters more than how often:

| where the terms hit | score |
|---|---|
| the name / slug / title | 3.0 |
| the description | 2.0 |
| the body | 1.0 |

Plus `min(count, 10) * 0.1` so a note that is *about* the term beats one that
mentions it, and recency (`mtime`) as the tiebreak. Every term has to hit
somewhere, which is what `search_sessions` already requires — `"textual grid"`
returns what mentions both, not the union.

Not every corpus has all three fields, and none is invented to fill the table:
a **tool** has a name and a description and no body, so a tool is found by what
it is called and what it says it does; a **memory** and a **note** have all
three; a **session** has a title and a body of prompts and no description.

Sessions keep their own function and its typo tolerance; their score is
normalised into the same range rather than reimplemented.

Each hit is:

```python
{"kind": "session" | "memory" | "tool" | "note",
 "label": str,        # what you read in the row
 "sub": str,          # project, machine, module -- the second column
 "score": float,
 "mtime": float,
 "ref": dict}         # what the opener needs, per kind
```

`ref` is the smallest thing that reopens the hit, and it is a dict per kind so
the opener never has to guess from a string:

| kind | `ref` | opened by |
|---|---|---|
| `session` | the session row itself | `Reader(transcript(row))` |
| `memory` | `{"project", "slug", "machine"}` | `app.open_memory(...)` |
| `note` | `{"path"}` | `Reader`, markdown on |
| `tool` | `{"module", "id", "what"}` | the Tools tab, at that module and row |

### On screen

A panel that covers the home's cards while there is a query, and gets out of
the way when there is not.

```
╭─ search ────────────────────────────────────────╮
│ textual                                         │
╰─────────────────────────────────────────────────╯
╭─ RESULTS ───────────────────────────────────────╮
│ note     sto-tui-textual            vault       │
│ session  transcript como chat…      my-agentic  │
│ memory   braingent-rediseno…        DeskB       │
│ tool     textual-helper             skills      │
╰─────────────────────────────────────────────────╯
```

- The kind is a column, not a prefix glyph. It is the thing you scan for, and
  it sorts and aligns as a column while a glyph does neither.
- `↵` opens the hit where it belongs: a session and a memory in the `Reader`,
  a tool in the Tools tab at its own level, a note in the `Reader`.
- `Esc`, or emptying the box, closes the panel and the dashboard comes back.
- Empty query is not an empty result: the panel is simply not there.

The other tabs' boxes keep filtering their own list. That is what you want once
you are standing in one, and it needs no new key.

---

## 2. The Tools tab

`Skills` becomes `Tools` and covers every config module: `claude-md`,
`settings`, `keybindings`, `skills`, `agents`, `hooks`, `plugins` — the keys of
`srv.CONFIG_MODULES`, so the tab cannot drift from what sync actually carries.

Three levels, which is exactly the `Levels` mixin sub-project B already built:

```
kinds            ->  items of that kind   ->  the item itself
(fixed, left)        (list)                   (content)
```

Wide: three panels side by side, the left one fixed. Narrow: one at a time,
`↵` down and `Esc` up. Neither of those is new code — `LEVELS = ("kinds",
"rows", "detail")` and the mixin does it.

**What each kind yields** is already answered by `ui.module_items(mod)`, which
returns `{"what": "skill" | "plugin" | "file", "id", "label", "desc", "where"}`.
Reading the content is the only new part:

| `what` | content |
|---|---|
| `skill` | `srv.get_skill(id)["content"]` |
| `file` | the file at `id`, read as text |
| `plugin` | none — a plugin is a manifest entry, not a document |

The three verbs `a` / `d` / `R` stay exactly as they are and keep refusing what
they already refuse: `srv.forget`'s guard is the engine's, and the screen shows
its answer verbatim.

**Config keeps the preferences.** Tools is for reading what is on this machine;
Config is for changing what syncs. The parity table on the home links into
Tools rather than repeating it.

**The tab count does not change.** `TABS` keeps six entries with `tab_skills`
replaced by `tab_tools`, so `1`-`6` and every test that presses a digit still
mean what they meant.

**Its search box filters the list of the kind you are on**, the way the other
tabs' boxes filter theirs. Global search is the home's job, and a second global
box on a screen that has its own list is two boxes doing different things while
looking the same.

**New strings**, in `i18n.py`, Spanish and English: `tab_tools`, `sec_kinds`,
`sec_results`, and one label per kind of hit (`kind_session`, `kind_memory`,
`kind_tool`, `kind_note`). The module names themselves (`claude-md`,
`settings`, …) are ids, not prose, and stay as they are — they are what
`sto push` prints.

---

## 3. Markdown

Memories and `SKILL.md` are markdown, and the `Reader` shows them as plain
text with the accent applied to backticks. Textual ships a `Markdown` widget;
it renders headings, lists, tables, bold and italic, and it costs nothing new.

**Where it applies, and where it does not:**

- **Memories, skills and vault notes** → `Markdown`. They are documents.
- **Config files** (`settings.json`, `keybindings.json`) → plain text. JSON in a
  markdown renderer is worse than JSON, not better.
- **Transcripts** → unchanged. The conversation renderer — `USER`/`CLAUDE` with
  their gutters, code on the panel, tool calls in amber, errors in red — carries
  more than markdown can, and it cost a design pass to get right. A transcript
  is not a document, it is a conversation.

So `Reader` grows one argument: `Reader(title, body, links=(), markdown=False)`.
Its three current call sites pass what they already pass; the two that hand it a
document pass `markdown=True`.

One catch, verified: `Markdown.can_focus` is `False`. The widget goes inside the
`VerticalScroll` that already holds the document, which is what takes the keys —
so the reader's `↑↓`/`PgUp`/`PgDn` bindings keep working untouched.

---

## Tests

| test | what fails without it |
|---|---|
| `search_all` finds the same word in a session, a memory, a tool and a note, and labels each with its kind | the whole point of item 3 |
| a second search does not re-read a file whose mtime has not moved | the index silently not being an index, and the box stuttering |
| every term must hit: `"textual grid"` does not return a note that only says `textual` | a ranking that returns everything |
| the results panel appears with a query and is gone without one | a dashboard permanently covered |
| `↵` on each kind of hit opens the right thing | four openers, three of which are easy to get wrong |
| Tools lists every key of `CONFIG_MODULES` | a tab that drifts from what sync carries |
| `↵` on a `claude-md` row shows the file's text | item 5, which is the reason the tab was renamed |
| a plugin row says it has nothing to read instead of failing | the one kind with no document |
| a memory opens with markdown rendered and a transcript does not | the boundary in section 3 |

---

## Out of scope

Export/import is sub-project D. Vectors, FTS5 and `sto find` as a *command* are
ROADMAP items 8 and 14: this builds the function they would use, and stops
there. Syntax highlighting for JSON would mean tree-sitter, which is a
dependency, and the answer is no.
