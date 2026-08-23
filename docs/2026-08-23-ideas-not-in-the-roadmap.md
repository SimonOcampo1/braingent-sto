# Ideas the roadmap does not have

An outside read of `ROADMAP.md` and of the research in `vault/wiki/`, looking
for the thing this project can do that nobody else can — and for the places the
roadmap is planning work the research already argues against.

Written 2026-08-23, after the TUI pass. Nothing here is committed work.

---

## 1. The asset nobody else has, and nobody is using

Every competitor stores memory in a database: engram in SQLite, claude-mem in
SQLite plus Chroma, agentmemory in its own store, mem0 and Memori in vectors,
memanto in a service. STO stores it in **git**, and the roadmap treats that as a
transport decision — a free, private, ownable sync channel.

It is much more than that. A database knows the current state. Git knows **how
the state got here**, and it is the only memory system in the field that does:

| git gives | no competitor has it | because |
|---|---|---|
| `blame` per line | when a belief entered the agent's head | they overwrite rows |
| `log -L` | how a belief changed over time | they store the latest |
| `bisect` | which change caused a behaviour | they have no changesets |
| signatures | who wrote a memory | they have no authorship |
| branches | a memory state you can try and throw away | there is one store |

And STO holds **three corpora that are versioned together**: memories, the
config that shapes the agent (skills, plugins, settings), and the transcripts of
what actually happened. Nobody else has all three, because nobody else syncs
setup at all.

Almost every idea below is a consequence of one of those two facts.

---

## 2. Five things worth building

### 2.1 `sto why <memory>` — blame for knowledge

**The problem.** An agent tells you something with total confidence and you have
no idea where it got it. This is the most common complaint about agent memory
and there is **no standard answer**: every system can tell you *what* it
remembers and none can tell you *when it decided that, or from what*.

**Why we can.** A memory is a file in git. Every line has a commit. Every commit
has a date and a machine. If the commit message carries the session id that
produced it — which `sync_push` is already in a position to write — then
`git blame` becomes provenance:

```
sto why braingent-rediseno-agent-agnostic

  line 4   "sync ya no es aditivo"      DeskB   22 ago   session a3f21c
  line 9   "el borde de adapter"        DeskB   22 ago   session a3f21c
  line 14  "no re-litigar las tres"     LaptopA 26 ago   session 7d9e04
```

And `↵` on any of those opens the conversation where it was decided.

**Size.** Small. `git blame --porcelain` on one file, plus one line added to the
commit message in `sync_push`. No new storage, no index. The hard part is
deciding to write the session id, and that is a one-line change made once.

**Why it matters more than it looks.** It turns "the agent's memory" from an
oracle into a document with sources. That is the difference between trusting it
and auditing it, and auditing is what makes people willing to let it grow.

### 2.2 Memories that report whether anyone reads them

**The problem.** Memory stores grow and nothing ever leaves. Every project in
the field has a curation story (mem0's ADD/UPDATE/DELETE, engram's topic key,
this roadmap's item 11) and all of them ask a **human or an LLM to judge value**
by reading the memory. Nobody measures.

**Why we can measure.** Claude Code loads `MEMORY.md` every session and opens
topic files on demand — and that open is a `Read` tool call, which lands in the
transcript, which STO already collects and parses. `dream_extract.py` walks
exactly this.

So STO can answer a question no competitor can even ask: **which memories has
the agent actually read, and when.**

```
sto memory unused --since 90d

  14 memories nobody opened in 90 days
  3 of them are in projects with no sessions since May
```

**Size.** Medium. One pass over the sessions already cached, counting `Read`
calls whose path is under a `memory/` directory. The counting is easy; the
honest part is not deleting anything — it ranks, and a human presses the key.

**The twist that makes it a feature rather than a metric.** Feed it back: a
memory nobody reads in six months is a candidate to fold into `MEMORY.md` as one
line, or to drop. That is roadmap item 11's curation with evidence attached
instead of vibes.

### 2.3 `sto replay <session>` — the environment, not just the transcript

**The problem.** You look at a session from three weeks ago that went well, or
badly, and you cannot tell what the agent was working with. Which skills were
installed? What was in `CLAUDE.md`? Which memories existed? The transcript shows
what was said, never what was loaded.

**Why we can.** This is the payoff of syncing setup. A session has a timestamp;
git can answer what `knowledge/config/` and `knowledge/memory/` looked like at
that timestamp. Reconstructing the environment of a past session is a
`git show` at the right commit.

```
sto replay 7d9e04

  session   7d9e04 · my-agentic-os · 26 ago · LaptopA
  config    38 skills, 11 plugins, CLAUDE.md @ 4e91a2
  memories  12 in this project, 3 written after this session
  diff to now:  +6 skills, -1 plugin, CLAUDE.md changed twice
```

**Size.** Medium. Everything needed is already on disk; it is a query, not a
feature. The value is entirely in the last line — the diff between then and now.

**Why nobody else can.** They do not version config, so they cannot say what the
agent was configured with. It is not a hard problem for them; it is an
impossible one, and it stays impossible for as long as they store memory beside
the agent instead of the whole setup with it.

### 2.4 A changelog for your agent's behaviour

**The problem, and it is the one I would bet on.** You install a skill, edit
`CLAUDE.md`, add a plugin — and the agent behaves differently. Better or worse,
you cannot tell, and you certainly cannot tell *which* change did it. Everyone
running Claude Code seriously has this problem. **There is no standard solution
and barely any acknowledgement that it is a problem.** People A/B their prompts
by feel.

**Why we can.** The config is versioned, the sessions are collected, and the
sessions carry measurable things `dream_extract` already extracts: prompts per
session, tool calls, errors, how often the human had to correct course.

```
sto drift --since 30d

  6 ago   +skill superpowers        sessions after: 24
  14 ago  CLAUDE.md +12 lines       errors/session  3.1 -> 1.4
  19 ago  +plugin context7          tools/session   180 -> 240
```

**Say the honest thing loudly:** this is correlation over a tiny sample and it
must be presented as such — a timeline of changes with session metrics beside
it, never a claim of cause. A tool that says "this skill made your agent 40%
better" would be lying. One that says "here is what changed and here is what
happened after" is giving you the only evidence that exists.

**Size.** Medium-large, and it wants item 2 (automatic sync) first so the
timeline has data.

**Why this is the flagship candidate.** Points 2.1 to 2.3 make STO a better
memory tool. This one makes it a **different category**: version control for
agent configuration, with an evidence trail. The comparison table in the roadmap
stops being "us versus five memory stores" and starts being a table nobody else
is in.

### 2.5 The brain outlives the agent

**The problem.** Every memory tool locks its memory to one agent. Move from
Claude Code to Codex, Cursor or whatever comes next and you start from zero.
This is a real fear and it is getting realer as the field churns.

**Why we can.** `srv.agents` and the adapter edge already exist — that decision
was made and documented (`vault/wiki/sto-borde-de-adapter.md`). The memories are
plain markdown with typed frontmatter, and the vault is plain markdown. Almost
nothing in `knowledge/` is Claude-shaped except the paths.

The pitch writes itself: **your agent is rented, your brain is yours.** That is
a stronger line than anything in the current README, and it is nearly true
already rather than being a thing to build.

**Size.** Small to state, medium to prove. The work is one second adapter and
an export that is not Claude-shaped — which is also most of the export/import
item that is already on the list.

---

## 3. Three places the roadmap plans work the research argues against

### 3.1 Item 14 (embeddings) is correctly last, and item 8 may be too early

`vault/wiki/papers-memoria-procedural.md` records ConvoMem's measurement: full
context reaches 70-82% accuracy where RAG systems like Mem0 reach 30-45%, under
150 conversations. The roadmap already puts vectors last for the right reason.

The same finding cuts at **item 8's FTS5 index**. `ui.search_all` now searches
all four corpora in 0.07 s warm, 0.39 s cold, with a dict keyed by mtime and
zero dependencies. FTS5 buys a durable index that survives the process — real,
but only worth it once `sto find` from a shell is a thing people run constantly.
Ship the command over the existing function first and see whether the cold cost
is ever actually annoying.

### 3.2 Letta's retreat is a warning about item 11

`vault/wiki/letta-por-dentro.md` records that Letta **removed** its per-project
memory blocks — the ones that carried skills — and went back to injecting skills
as system reminders. They tried to make capability live inside memory and
reversed it.

Item 11 (`sto curate`) is not the same thing, but it is adjacent: it is the item
most likely to drift into "STO decides what the agent should know". The lesson
is to keep curation as **proposal plus keypress**, which the roadmap already
says, and to never let it write unattended.

### 3.3 Syncthing is the competitor, and the README does not know it

`vault/wiki/agenticos-en-la-practica.md` has the strongest market signal in the
whole research pile: a 32,000-view video answers "how does my agent get my
skills on another machine" with **Syncthing**. People have the problem and are
patching it with a generic file syncer.

That belongs in the README's comparison, above the memory stores. The memory
stores are what STO looks like to someone who already knows the category;
Syncthing is what the actual user is doing today. The pitch against it is
concrete: it does not know what a skill is, cannot reconcile memories per
project, has no history, and cannot tell you what is about to travel.

---

## 4. A risk the roadmap does not name

**The repo grows without a ceiling.** Sessions are `.jsonl`, capped at 500 files
and 10 MB each — that is a 5 GB worst case in a git repository, and git is bad
at exactly that. `git gc` will not save it because the files are unique blobs.

Nobody has hit it yet, which is why it is not on the list. The moment somebody
runs `sto push` from a machine with two years of history it becomes the first
thing they notice.

Worth deciding **before** it happens, because after it happens the fix is a
history rewrite — which `vault/wiki/` already says must never be done alone,
since the two clones share history:

- a retention window (keep the last N months in full, keep the extracted summary
  forever), or
- sessions in a second repo, or
- `git lfs`, which is a dependency and a hosting cost.

The cheapest answer is probably the first: `dream_extract` already reduces a
session to what anybody ever looks at.

---

## 5. What I would do first

Ordered by evidence produced per hour spent:

1. **`sto why`** — smallest, and it is the one that changes how the product
   *reads*. Provenance is the answer to the question people actually have.
2. **The Syncthing paragraph in the README** — costs an afternoon, moves the
   project from "another memory tool" to "the thing you are already trying to do
   with the wrong tool".
3. **Memory read counts** — the input to curation, and it needs nothing new.
4. **`sto drift`** — the flagship, once item 2 has fed it a month of data.

`sto replay` and the agent-portability story are stronger as **README material
than as features**: they are both mostly true already, and saying so costs
nothing.

---

## The line under all of it

The roadmap's thesis is *"shared memory and setup, free, over a repo you own"*.
That describes what STO moves. Every idea above is a consequence of it that the
thesis does not claim yet:

> Because your agent's whole setup is in git, you can ask it questions no
> database can answer — where a belief came from, what changed before it started
> behaving differently, what it was working with three weeks ago.

The competitors chose a database and cannot get here from there. That is worth
saying out loud, in the README, above the table.
