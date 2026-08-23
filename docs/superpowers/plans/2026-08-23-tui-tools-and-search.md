# Tools Tab, Global Search and Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One search over every corpus, a Tools tab that reaches every config module, and markdown shown as markdown.

**Architecture:** The search is a function in `ui.py` — the engine layer both flavours already share — behind an mtime-keyed index, so the TUI only decides how hits look. Tools is a third `Levels` pane, reusing the drill-down built in sub-project B. Markdown is one extra argument on the existing `Reader`.

**Tech Stack:** Python 3.11+, Textual 8.2.8, no new dependencies. `difflib` and `pathlib` are stdlib.

**Spec:** `docs/superpowers/specs/2026-08-23-tui-tools-and-search-design.md`

## Global Constraints

- **Code, comments and docstrings in English.** Every user-facing string lives in `scripts/i18n.py`, in both `es` and `en` — never hardcode one in `ui.py`, `cli.py` or `tui_app.py`. (`CLAUDE.md`)
- **This repo is the public clone.** Code changes happen here and reach the private one through `sto update`.
- **Zero new dependencies.**
- **No emoji, and no pictographs either.** Only glyphs that draw or carry data: Block Elements, Box Drawing, Geometric Shapes (`▲ ▼ ● ◐ ○`) and arrows. Nothing from Miscellaneous Symbols or Dingbats — a gear, a check mark, a framed square are decoration, and `test_no_pictographs_in_the_source` fails on them.
- Suites: `uv run --no-project --with textual python scripts/test_tui_app.py`, and `cd scripts && python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui.py`.
- `test_ui.py` discovers every module-level `test_*` by itself — adding one needs no runner edit. `test_tui_app.py` has an explicit `__main__` list and does.
- Commits: Conventional Commits, subject in Spanish, no Claude/Anthropic trailers.

---

### Task 1: `ui.search_all` and the index

The engine half. Testable on its own with no terminal, and the piece `sto find` would use.

**Files:**
- Modify: `scripts/ui.py` (new section, after `module_items`)
- Test: `scripts/test_ui.py`

**Interfaces:**
- Consumes: `srv.search_sessions`, `srv.list_memory`, `srv.CONFIG_MODULES`, `cli.cached_sessions`, `ui.module_items`.
- Produces: `ui.search_all(q, limit=40) -> list[dict]`, `ui._score(terms, name, desc, body) -> float`, `ui._indexed(paths) -> dict[str, tuple[float, str]]`, `ui._tool_rows() -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

Add to `scripts/test_ui.py`:

```python
def test_every_term_has_to_hit_somewhere():
    """A search that returns the union of its terms returns everything. And
    where a term hits matters more than how often: a note called `textual` is
    about textual, a note that says it once in passing is not."""
    name = ui._score(["textual"], "sto-tui-textual", "", "")
    body = ui._score(["textual"], "other-note", "", "textual appears here")
    assert name > body, (name, body)
    assert ui._score(["textual", "grid"], "sto-tui-textual", "", "") == 0.0
    assert ui._score(["textual", "grid"], "sto-tui-textual", "", "a grid here") > 0

    # more mentions is worth something, but never as much as being the title
    many = ui._score(["grid"], "note", "", "grid " * 20)
    assert body < many < name


def test_the_index_only_re_reads_what_moved():
    """0.44 s of vault scanning per keystroke is not a search box. The index is
    derived from files that stay the source of truth, so it can be wrong only
    for as long as an mtime is."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "note.md"
        f.write_text("first body", encoding="utf-8")
        ui._INDEX.clear()
        first = ui._indexed([f])
        assert "first body" in first[str(f)][1]

        reads = []
        real = Path.read_text
        Path.read_text = lambda self, **kw: (reads.append(self), real(self, **kw))[1]
        try:
            ui._indexed([f])
            assert reads == [], "an unchanged file was read again"
            f.write_text("second body", encoding="utf-8")
            import os
            os.utime(f, (0, time.time() + 10))
            again = ui._indexed([f])
            assert reads, "a changed file was not re-read"
            assert "second body" in again[str(f)][1]
        finally:
            Path.read_text = real


def test_search_all_labels_every_hit_with_its_kind():
    """Four corpora into one list, and the row has to say which one it came
    from — that is the whole difference between a search and a pile."""
    hits = ui.search_all("sto")
    assert isinstance(hits, list)
    assert all({"kind", "label", "sub", "score", "mtime", "ref"} <= set(h)
               for h in hits), hits[:1]
    assert all(h["kind"] in ("session", "memory", "tool", "note") for h in hits)
    # ranked, best first
    assert hits == sorted(hits, key=lambda h: (-h["score"], -h["mtime"]))
    assert ui.search_all("") == []
    assert ui.search_all("   ") == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd scripts && python test_ui.py
```

Expected: `AttributeError: module 'ui' has no attribute '_score'`.

- [ ] **Step 3: Write the scorer and the index**

In `scripts/ui.py`, after `module_items`:

```python
# ── one search over everything ──
#
# Here and not in a TUI: nothing in a flavour recomputes a rule, so the two
# cannot disagree about an answer — and this is the function `sto find`
# (ROADMAP 8) would be, rather than a third copy of a ranking.
#
# Measured on a real repo, one uncached pass is 0.83 s: the vault alone is
# 0.44 s and walking the config modules another 0.26 s. Per keystroke that is
# a stutter, not a search box, so both are cached and the caller debounces.

_INDEX: dict[str, tuple[float, str]] = {}
_TOOLS: dict = {"stamp": None, "rows": []}


def _indexed(paths):
    """`{path: (mtime, lowercased text)}`, re-reading only what moved.

    Derived and disposable: the files stay the source of truth, so the worst a
    stale entry can be is as stale as an mtime. Entries for files that have
    since been deleted are left in the dict rather than swept — this is called
    with one corpus at a time, so "not in the argument" does not mean "gone",
    and a few dead strings cost less than being wrong about that.
    """
    out = {}
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        key = str(path)
        hit = _INDEX.get(key)
        if hit is None or hit[0] != mtime:
            try:
                hit = (mtime, path.read_text(encoding="utf-8",
                                             errors="replace").lower())
            except OSError:
                continue
            _INDEX[key] = hit
        out[key] = hit
    return out


def _score(terms, name, desc, body):
    """How well one item answers the query. `0.0` means it does not.

    Where a term hits weighs more than how often: a note *called* `textual` is
    about textual, one that mentions it in passing is not. The count still
    counts, capped, so it can break a tie between two bodies but never outrank
    a title.

    Every term has to land somewhere or the item is out. Searching two words
    and getting back the union of both is how a search returns everything.
    """
    total = 0.0
    for term in terms:
        best = 0.0
        for text, weight in ((name, 3.0), (desc, 2.0), (body, 1.0)):
            if text and term in text:
                best = max(best, weight + min(text.count(term), 10) * 0.1)
        if not best:
            return 0.0
        total += best
    return total


def _tool_rows():
    """Every config module's items, with the module on each row.

    Cached against the mtimes of the module entries: walking them is a quarter
    of a second, which is fine once and impossible per keystroke. `plugins` has
    no entry to stat — it is a manifest, not a directory — so it rides on the
    others' stamp and refreshes with them.
    """
    stamp = []
    for entries in srv.CONFIG_MODULES.values():
        for entry in entries:
            try:
                stamp.append((srv.CLAUDE_DIR / entry).stat().st_mtime)
            except OSError:
                stamp.append(0.0)
    stamp = tuple(stamp)
    if _TOOLS["stamp"] != stamp:
        _TOOLS["rows"] = [dict(row, module=mod)
                          for mod in srv.CONFIG_MODULES
                          for row in module_items(mod)]
        _TOOLS["stamp"] = stamp
    return _TOOLS["rows"]
```

- [ ] **Step 4: Write `search_all`**

```python
def search_all(q, limit=40):
    """Sessions, memories, tools and vault notes, ranked into one list.

    Each hit says which corpus it came from, because that is the whole
    difference between a search and a pile.
    """
    terms = [t for t in q.strip().lower().split() if t]
    if not terms:
        return []
    hits = []

    # sessions keep their own function: it is typo-tolerant and it searches
    # prompt bodies through an index it already maintains. Its score is not
    # comparable to a substring count, so what is borrowed is the order
    rows, _ = cli.cached_sessions()
    for i, r in enumerate(srv.search_sessions(q, rows=rows, limit=limit)):
        hits.append({"kind": "session", "label": r["title"], "sub": r["project"],
                     "score": 4.0 - i * 0.01, "mtime": r["mtime"], "ref": r})

    memories = {}
    for p in srv.list_memory():
        for m in p["memories"]:
            path = srv.KNOWLEDGE_MEMORY / p["project"] / m["machine"] / f"{m['slug']}.md"
            memories[path] = (p, m)
    text = _indexed(memories)
    for path, (p, m) in memories.items():
        body = text.get(str(path), (0.0, ""))[1]
        score = _score(terms, m["slug"].lower(),
                       (m["description"] or "").lower(), body)
        if score:
            hits.append({"kind": "memory", "label": m["slug"],
                         "sub": f"{srv._proj_label(p['project'])} · {m['machine']}",
                         "score": score, "mtime": m["mtime"],
                         "ref": {"project": p["project"], "slug": m["slug"],
                                 "machine": m["machine"]}})

    notes = sorted((srv.REPO_ROOT / "vault").rglob("*.md"))
    text = _indexed(notes)
    for path in notes:
        mtime, body = text.get(str(path), (0.0, ""))
        score = _score(terms, path.stem.lower(), "", body)
        if score:
            hits.append({"kind": "note", "label": path.stem,
                         "sub": path.parent.name, "score": score,
                         "mtime": mtime, "ref": {"path": str(path)}})

    for row in _tool_rows():
        # a tool has a name and a description and no body: it is found by what
        # it is called and by what it says it does
        score = _score(terms, row["label"].lower(), (row["desc"] or "").lower(), "")
        if score:
            hits.append({"kind": "tool", "label": row["label"],
                         "sub": row["module"], "score": score, "mtime": 0.0,
                         "ref": {"module": row["module"], "id": row["id"],
                                 "what": row["what"]}})

    hits.sort(key=lambda h: (-h["score"], -h["mtime"]))
    return hits[:limit]
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd scripts && python test_ui.py
```

Expected: `OK (162 tests)`.

- [ ] **Step 6: Measure the index doing its job**

```bash
cd scripts && python -c "
import time, ui
for label in ('cold', 'warm', 'warm'):
    t = time.time(); n = len(ui.search_all('textual')); print(f'{label:<6}{time.time()-t:6.3f}s  {n} hits')
"
```

Expected: the first is a few tenths of a second, the two after it an order of magnitude less. If warm is not much faster than cold, the index is not being hit — check that `_INDEX` is module level and not rebuilt inside `search_all`.

- [ ] **Step 7: Commit**

```bash
git add scripts/ui.py scripts/test_ui.py
git commit -m "feat(ui): search_all, una busqueda sobre los cuatro corpus

Sesiones, memorias, tools y notas del vault en una lista rankeada, cada
fila diciendo de donde salio. Va en ui.py y no en una TUI: ningun sabor
recalcula una regla, y esta es la funcion que usaria \`sto find\` en vez de
una tercera copia de un ranking.

Medido en un repo real, una pasada sin cache son 0,83 s -- el vault solo
0,44 y recorrer los modulos de config otros 0,26. Por tecleo eso es un
tartamudeo, no un buscador: el texto va a un indice por mtime y las filas
de tools a una cache por stamp. El indice es derivado y descartable, los
archivos siguen siendo la fuente de verdad.

Donde pega un termino pesa mas que cuantas veces, y todos los terminos
tienen que pegar en algo: buscar dos palabras y recibir la union de las
dos es como una busqueda devuelve todo."
```

---

### Task 2: Markdown in the reader

Smallest slice, and independent of the other three.

**Files:**
- Modify: `scripts/tui_app.py` (`Reader`, and the two call sites that pass a document)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Reader(title, body, links=(), markdown=False)`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_memory_renders_as_markdown_and_a_transcript_does_not():
    """A memory and a SKILL.md are documents; `**bold**` on screen as four
    asterisks is the reader failing at its one job.

    A transcript is not a document, it is a conversation, and its own renderer
    — who spoke, with their gutter, code on the panel, tools in amber — carries
    what markdown cannot. That one keeps its blocks.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.push_screen(tui_app.Reader("note", "# Title\\n\\n**bold** text",
                                           markdown=True))
            await pilot.pause()
            assert app.screen.query(Markdown), "the document is not markdown"
            painted = "\\n".join(screen_text(app))
            assert "**bold**" not in painted, painted
            await pilot.press("escape")
            await pilot.pause()

            app.push_screen(tui_app.Reader("plain", [("user", "hello")]))
            await pilot.pause()
            assert not app.screen.query(Markdown), "a transcript went to markdown"

    asyncio.run(go())
```

Add `from textual.widgets import Markdown` to the imports of `test_tui_app.py`, and register the test in the `__main__` block.

- [ ] **Step 2: Run to verify it fails**

Expected: `TypeError: Reader.__init__() got an unexpected keyword argument 'markdown'`.

- [ ] **Step 3: Teach `Reader` the flag**

In `scripts/tui_app.py`, add `Markdown` to the `textual.widgets` import, then:

```python
    def __init__(self, title, body, links=(), markdown=False):
        super().__init__()
        self._title = title
        # a string is one plain block; a list is `(css class, markup)` turns
        self._blocks = body if isinstance(body, list) else [("plain", body)]
        self._links = list(links)
        self._markdown = markdown and isinstance(body, str)
```

and in `compose`, replace the loop over blocks with:

```python
                with VerticalScroll(id="doc-scroll"):
                    if self._markdown:
                        # `Markdown.can_focus` is False, so the scroll around
                        # it stays the thing that takes the keys and the
                        # reader's ↑↓/PgUp/PgDn bindings are untouched
                        yield Markdown(self._blocks[0][1])
                    else:
                        for css, text in self._blocks:
                            yield Static(text if css == "plain"
                                         else Content.from_markup(text),
                                         markup=False, classes=f"blk {css}")
```

- [ ] **Step 4: Turn it on where the body is a document**

Two call sites. In `Skills.open` (which Task 3 renames, so do this one first and let Task 3 carry it):

```python
        self.app.push_screen(Reader(skill["name"], skill["content"], markdown=True))
```

In `StoApp.open_memory`:

```python
        self.push_screen(Reader(f"{project}/{slug}", body, links, markdown=True))
```

`Sessions.open_row` passes a list of blocks and is not touched.

- [ ] **Step 5: Run the test to verify it passes**

Expected: `OK`.

- [ ] **Step 6: Look at one by eye**

```bash
STO_TUI_TAB=2 uv run --no-project --with textual python scripts/tui_app.py
```

Open a memory. Headings must be headings and `**bold**` must be bold, not four asterisks. Check a memory with a code fence and one with a table.

- [ ] **Step 7: Commit**

```bash
git add scripts/tui_app.py scripts/test_tui_app.py
git commit -m "feat(tui): las memorias y las skills se leen como markdown

Son documentos, y \`**negrita**\` en pantalla como cuatro asteriscos es el
lector fallando en su unico trabajo. El widget de la libreria lo hace y
no cuesta una dependencia.

El transcript no cambia: no es un documento, es una conversacion, y su
render propio -- quien hablo con su canaleta, el codigo sobre el panel,
las tools en ambar -- lleva lo que markdown no. Los json de config
tampoco: json adentro de un render de markdown es peor json, no mejor."
```

---

### Task 3: The Tools tab

**Files:**
- Modify: `scripts/tui_app.py` (`Skills` becomes `Tools`, `TABS`)
- Modify: `scripts/i18n.py` (`tab_tools`, `sec_kinds`)
- Modify: `scripts/tui_app.tcss` (a three-column split)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: sub-project B's `Levels` mixin, Task 2's `Reader(markdown=)`.
- Produces: `Tools` pane with `LEVELS = ("kinds", "rows", "detail")` and `Tools.show(module, item_id)` for Task 4's opener.

- [ ] **Step 1: Write the failing test**

```python
def test_tools_reaches_every_config_module_and_reads_one():
    """The tab used to be skills only, so `settings.json` and `CLAUDE.md` —
    which sync carries and the parity table counts — could be seen as a number
    and never as a file.

    The kinds come from `CONFIG_MODULES` itself, so the tab cannot drift from
    what push actually moves.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("4")
            await pilot.pause()
            pane = app.query_one("#tools")
            kinds = app.query_one("#t-kinds", tui_app.Table)
            listed = {kinds.get_row_at(i)[0].plain
                      if hasattr(kinds.get_row_at(i)[0], "plain")
                      else str(kinds.get_row_at(i)[0])
                      for i in range(kinds.row_count)}
            for module in tui_app.srv.CONFIG_MODULES:
                assert any(module in row for row in listed), (module, listed)

            # walk to claude-md and read it
            for i in range(kinds.row_count):
                cell = str(kinds.get_row_at(i)[0])
                if "claude-md" in cell:
                    kinds.move_cursor(row=i)
                    break
            await pilot.pause()
            assert pane.rows, "claude-md listed nothing"
            assert pane.content(pane.rows[0]) is not None, "the file did not read"

            # a plugin is a manifest entry with no document behind it, and that
            # is an answer rather than a crash
            plugins = [r for r in ui.module_items("plugins")]
            if plugins:
                assert pane.content(plugins[0]) is None, plugins[0]

    asyncio.run(go())
```

`ui` is reachable as `tui_app.ui`; use that rather than importing it again.

- [ ] **Step 2: Run to verify it fails**

Expected: `NoMatches: No nodes match '#tools'`.

- [ ] **Step 3: Add the strings**

In `scripts/i18n.py`, beside `tab_skills` in both dictionaries:

```python
        "tab_tools": "Tools",           # es
        "sec_kinds": "Tipo",
```

```python
        "tab_tools": "Tools",           # en
        "sec_kinds": "Kind",
```

`Tools` is the same word in both on purpose: it is what the tab is called, the way `Home` already is.

- [ ] **Step 4: Rename the pane and give it a third level**

In `scripts/tui_app.py`:

```python
TABS = ["tab_home", "tab_sessions", "tab_memory", "tab_tools",
        "tab_config", "tab_help"]
HOME, SESSIONS, MEMORY, TOOLS, CONFIG, HELP = range(6)
```

`class Skills(Levels, Container)` becomes `class Tools(Levels, Container)` with:

```python
class Tools(Levels, Container):
    """Everything the agent runs with, on this machine and in the repo.

    It was the skills tab, which meant `settings.json` and `CLAUDE.md` — things
    push carries and the parity table counts — could be seen as a number and
    never as a file. The kinds are the keys of `CONFIG_MODULES` itself, so the
    tab cannot drift from what sync actually moves.
    """
    LEVELS = ("kinds", "rows", "detail")

    def compose(self) -> ComposeResult:
        yield Search(id="search")
        yield Card(t("sec_kinds"),
                   Table((t("sec_kinds"), 14, "text"), (t("col_total"), None, "num"),
                         id="t-kinds"), id="kinds")
        yield Card(t("tab_tools"),
                   Table((t("col_name"), 34, "text"), (t("col_desc"), None, "text"),
                         id="t-rows"), id="rows")
        yield Card(t("sec_detail"), VerticalScroll(Static(id="skill-detail")),
                   id="detail")
```

`on_mount` and the box handler in full — the old `Skills` versions filtered by
rebuilding everything, and now only the row list depends on the query:

```python
    def on_mount(self) -> None:
        self.q = ""
        self.rows = []
        self.level = 0
        self.refresh_data()
        self.set_level(0)
        self.query_one("#t-kinds", Table).focus()

    def on_input_changed(self, event) -> None:
        # only the rows: the kinds are the modules and no query changes those
        self.q = event.value
        self.fill()

    def on_input_submitted(self, event) -> None:
        self.query_one("#t-rows", Table).focus()
```

and `refresh_data` grows a kinds table:

```python
    def refresh_data(self) -> None:
        table = self.query_one("#t-kinds", Table)
        keep = table.cursor_row
        table.clear()
        self.modules = list(srv.CONFIG_MODULES)
        for mod in self.modules:
            table.add_row(mod, str(len(ui.module_items(mod))))
        table.fit()
        if 0 < keep < table.row_count:
            table.move_cursor(row=keep)
        self.fill()

    def fill(self) -> None:
        mod = self.modules[self.query_one("#t-kinds", Table).cursor_row]
        rows = ui.module_items(mod)
        if self.q:
            q = self.q.lower()
            rows = [r for r in rows if q in f"{r['label']} {r['desc']}".lower()]
        self.rows = rows
        table = self.query_one("#t-rows", Table)
        table.clear()
        for r in rows:
            mark, colour = {"local": (r"\[L]", "$warning"),
                            "repo": (r"\[R]", "$success"),
                            "gone": (r"\[x]", "$error")}.get(
                                r.get("where"), (r"\[=]", "$foreground 40%"))
            table.add_row(
                Content.from_markup(f"[{colour}]{mark}[/] {clip(r['label'], 30)}"),
                clip(r["desc"], 200))
        table.fit()
        if not rows:
            self.app.empty(table, t("cli_no_hits", q=self.q) if self.q else t("empty"))
        self.preview(0)
```

`on_data_table_row_highlighted` routes by table id:

```python
    def on_data_table_row_highlighted(self, event) -> None:
        if event.data_table.id == "t-kinds":
            self.fill()
        else:
            self.preview(event.cursor_row)
```

- [ ] **Step 5: Read the item**

```python
    def content(self, row):
        """What this row has to read, or `None` when it is not a document.

        A skill is its `SKILL.md`, a config module row is the file itself, and
        a plugin is a manifest entry with nothing behind it — which is a real
        answer and not a failure, so it is said rather than raised.
        """
        if row["what"] == "skill":
            skill = srv.get_skill(row["id"])
            return skill["content"] if skill else None
        if row["what"] == "file":
            try:
                return Path(row["id"]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        return None

    def open(self) -> None:
        if self.drill():
            return
        if not self.rows:
            return
        row = self.rows[self.query_one("#t-rows", Table).cursor_row]
        body = self.content(row)
        if body is None:
            return self.app.notify(t("empty"))
        # markdown only where the file is markdown: json in a markdown renderer
        # is worse json, not better
        self.app.push_screen(Reader(row["label"], body,
                                    markdown=row["label"].lower().endswith(".md")
                                    or row["what"] == "skill"))
```

`Path` is already imported at the top of `tui_app.py`; nothing to add.

- [ ] **Step 6: An opener for the search panel**

```python
    def show(self, module, item_id) -> None:
        """Land on one tool, from somewhere else. Used by the home's search."""
        if module in self.modules:
            self.query_one("#t-kinds", Table).move_cursor(
                row=self.modules.index(module))
            self.fill()
        table = self.query_one("#t-rows", Table)
        for i, row in enumerate(self.rows):
            if row["id"] == item_id:
                table.move_cursor(row=i)
                break
        self.set_level(1)
```

- [ ] **Step 7: Three columns wide, and the app wiring**

In `scripts/tui_app.py`, `compose` and `panes`:

```python
        yield Tools(id="tools", classes="split three-way")
```

and `panes` maps `"tools"` where it mapped `"skills"`.

In `scripts/tui_app.tcss`, replace the `.split.wide-left` rule:

```css
/* tools is three panels: the kinds stay put on the left and the two on the
 * right are what changes as you walk in */
.split.three-way { grid-size: 3 2; grid-columns: 16 2fr 2fr; }
.split.three-way > Search { column-span: 3; }
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
uv run --no-project --with textual python scripts/test_tui_app.py
```

Expected: `OK`. Three existing tests press `4` and now land on Tools:

- `test_the_last_column_takes_the_width_the_others_leave` asserts the first
  column is 34 wide. `#t-rows` keeps that spec, so it passes — but the pane is
  narrower now that the kinds column takes 16, so if the last column assertion
  (`> 20`) fails, widen the test's terminal rather than the layout.
- `test_the_search_box_is_on_screen_and_narrows_the_list` types `caveman` and
  expects the row count to drop. It now filters within one module, so it only
  holds while the cursor is on `skills`. **Move it to press `4` and then select
  the skills row before typing** — the assertion is still the right one.
- `test_nothing_that_writes_runs_before_the_manifest_is_on_screen` presses `d`
  on a row. `act()` is unchanged and still refuses non-skill rows, so land the
  cursor on `skills` first there too.

- [ ] **Step 9: Walk it at both widths**

```bash
uv run --no-project --with textual python scripts/tui_app.py
```

Press `4`. Every module in the list, `↵` into one, `↵` on a row shows the file. Narrow the terminal: three levels, one at a time, `Esc` back up.

- [ ] **Step 10: Commit**

```bash
git add scripts/tui_app.py scripts/tui_app.tcss scripts/i18n.py scripts/test_tui_app.py
git commit -m "feat(tui): la tab de skills es Tools y llega a cada modulo de config

Era solo skills, asi que settings.json y CLAUDE.md -- cosas que el push
lleva y que la tabla de paridad cuenta -- se podian ver como un numero y
nunca como un archivo. Ahora los tipos salen de las claves de
CONFIG_MODULES, asi que la tab no puede desviarse de lo que el sync
mueve de verdad.

Tres niveles con el mixin que ya existe: tipo, lista, contenido. En
ancho los tres paneles a la vez con el de tipos fijo a la izquierda; en
angosto uno a la vez. Un plugin no tiene nada que leer -- es una entrada
de manifiesto -- y eso es una respuesta, no una falla, asi que se dice.

Config no se toca: tools es para leer las herramientas del agente,
config es para cambiar que se sincroniza."
```

---

### Task 4: The results panel

**Files:**
- Modify: `scripts/tui_app.py` (`Home`)
- Modify: `scripts/i18n.py` (`sec_results`, `kind_session`, `kind_memory`, `kind_tool`, `kind_note`)
- Modify: `scripts/tui_app.tcss` (the panel over the grid)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: Task 1's `ui.search_all`, Task 3's `Tools.show`, Task 2's `Reader(markdown=)`.
- Produces: nothing later tasks need.

- [ ] **Step 1: Write the failing test**

```python
def test_the_home_search_finds_things_that_are_not_sessions():
    """The box on the home used to hand its text to the Sessions tab, which
    made it a worse version of the box already on that tab. It searches
    everything now, and every row says which corpus it came from."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            home = app.query_one("#home")
            assert not app.query_one("#results").display, "results before a query"

            box = home.query_one("#search", tui_app.Search)
            box.focus()
            for ch in "sto":
                await pilot.press(ch)
            await pilot.pause(0.4)          # past the debounce
            assert app.tab == tui_app.HOME, "the home handed the query away"
            assert app.query_one("#results").display, "no results panel"
            assert home.hits, "nothing found for a word this repo is full of"
            kinds = {h["kind"] for h in home.hits}
            assert kinds <= {"session", "memory", "tool", "note"}, kinds

            await pilot.press("escape")
            await pilot.pause()
            assert not app.query_one("#results").display, "escape left it open"

    asyncio.run(go())
```

- [ ] **Step 2: Run to verify it fails**

Expected: `NoMatches: No nodes match '#results'`.

- [ ] **Step 3: Add the strings**

In `scripts/i18n.py`, both dictionaries:

```python
        # es
        "sec_results": "Resultados", "kind_session": "sesión",
        "kind_memory": "memoria", "kind_tool": "tool", "kind_note": "nota",
```

```python
        # en
        "sec_results": "Results", "kind_session": "session",
        "kind_memory": "memory", "kind_tool": "tool", "kind_note": "note",
```

- [ ] **Step 4: The panel**

In `Home.compose`, after the `Search` and before the grid:

```python
        yield Card(t("sec_results"),
                   Table((t("sec_kinds"), 9, "text"), (t("col_name"), 44, "text"),
                         (t("col_project"), None, "text"), id="t-results"),
                   id="results")
```

In `Home.on_mount`:

```python
        self.hits = []
        self._timer = None
        self.query_one("#results").display = False
```

- [ ] **Step 5: Debounce, search, paint**

```python
    # the box fires per keystroke and a search is a tenth of a second even with
    # the index warm — `difflib` is doing real work. It runs when you stop
    # typing, which is also when you meant it to
    DEBOUNCE = 0.2

    def on_input_changed(self, event) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(self.DEBOUNCE, self.run_search)

    def run_search(self) -> None:
        self._timer = None
        q = self.query_one("#search", Search).value
        self.hits = ui.search_all(q) if q.strip() else []
        panel = self.query_one("#results")
        panel.display = bool(q.strip())
        table = self.query_one("#t-results", Table)
        table.clear()
        for h in self.hits:
            table.add_row(
                Content.from_markup(f"[$accent]{t('kind_' + h['kind'])}[/]"),
                clip(h["label"], 200), clip(h["sub"], 40))
        table.fit()
        if not self.hits and q.strip():
            self.app.empty(table, t("cli_no_hits", q=q))

    def on_input_submitted(self, event) -> None:
        """`↵` in the box goes to the results, not to another screen."""
        if self.hits:
            self.query_one("#t-results", Table).focus()
```

`Home.on_input_submitted` currently calls `self.app.search_sessions(event.value)`; that method and its binding go away with it — grep for `search_sessions` in `tui_app.py` and remove the one on `StoApp`.

- [ ] **Step 6: Open a hit**

```python
    def open(self) -> None:
        """`↵` on a result opens it where it belongs."""
        table = self.query_one("#t-results", Table)
        if not self.hits or not table.has_focus:
            return
        h = self.hits[table.cursor_row]
        ref = h["ref"]
        if h["kind"] == "session":
            self.app.push_screen(Reader(clip(ref["title"], 60), transcript(ref)))
        elif h["kind"] == "memory":
            self.app.open_memory(ref["project"], ref["slug"], ref["machine"])
        elif h["kind"] == "note":
            body = Path(ref["path"]).read_text(encoding="utf-8", errors="replace")
            self.app.push_screen(Reader(h["label"], body, markdown=True))
        else:
            self.app.show_tab(TOOLS)
            self.app.panes[TOOLS].show(ref["module"], ref["id"])

    def close_search(self) -> bool:
        """`Esc` puts the dashboard back. True if there was something to close."""
        if not self.query_one("#results").display:
            return False
        self.query_one("#search", Search).value = ""
        self.run_search()
        return True
```

In `StoApp.action_back`, try the home's closer before the level walk:

```python
    def action_back(self) -> None:
        """`Esc` closes the search, then climbs one level, then does nothing."""
        pane = self.panes[self.tab]
        if hasattr(pane, "close_search") and pane.close_search():
            return
        if hasattr(pane, "back"):
            pane.back()
```

- [ ] **Step 7: The panel covers the grid**

In `scripts/tui_app.tcss`:

```css
/* it takes the dashboard's room rather than squeezing beside it: while you are
 * searching, the four cards are not what you are looking at */
#results { height: 1fr; }
.home #results { margin-bottom: 1; }
```

and in `Home.run_search`, hide the grid while the panel is up:

```python
        self.query_one("#home-grid").display = not panel.display
```

- [ ] **Step 8: Run the tests to verify they pass**

Expected: `OK`, including the pre-existing `test_the_search_box_is_on_screen_and_narrows_the_list`, which uses the Tools tab and is unaffected.

- [ ] **Step 9: Try it by hand**

```bash
uv run --no-project --with textual python scripts/tui_app.py
```

Type a word the repo is full of. Results must appear once you stop typing, mixed across kinds, best first. `↵` on each kind opens the right thing. `Esc` brings the dashboard back.

- [ ] **Step 10: Run all five suites**

```bash
uv run --no-project --with textual python scripts/test_tui_app.py
cd scripts && python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui.py
```

- [ ] **Step 11: Commit**

```bash
git add scripts/tui_app.py scripts/tui_app.tcss scripts/i18n.py scripts/test_tui_app.py
git commit -m "feat(tui): el buscador del home busca en todo y muestra de donde salio

Le pasaba el texto a la tab de sesiones, o sea era una version peor de la
caja que esa tab ya tiene. Ahora consulta los cuatro corpus por
ui.search_all y despliega un panel sobre el dashboard con los resultados
rankeados; cada fila dice si es sesion, memoria, tool o nota, y enter
abre cada una donde corresponde. Esc devuelve el dashboard.

El tipo es una columna y no un glifo adelante: es lo que se escanea, y
una columna alinea y ordena donde un glifo no hace ninguna de las dos.

Busca 200 ms despues de la ultima tecla. Con el indice caliente una
busqueda sigue siendo una decima -- difflib hace trabajo de verdad -- y
una decima de teclado congelado por letra es la diferencia entre un
buscador y un tartamudeo."
```

---

## Closing the sub-project

- [ ] **Extend the wiki** in the **private** clone: `vault/wiki/sto-tui-textual.md` gains the search design (why it lives in `ui.py`, the measured cost, the index), and `vault/wiki/index.md` its line. Knowledge is committed there; code here.
- [ ] **Update `ROADMAP.md`** item 8 (`sto find`): the ranking function now exists as `ui.search_all`, so what is left of that item is the CLI command and the FTS5 index, not the design.
- [ ] **Do not push** unless asked.
