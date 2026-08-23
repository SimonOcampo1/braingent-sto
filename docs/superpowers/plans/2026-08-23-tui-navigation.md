# TUI Navigation and Responsive Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every panel of the Textual TUI reachable and operable at any terminal size, with the keyboard alone.

**Architecture:** Panes keep one widget tree at every width. A `narrow` class picks between two behaviours — hierarchical panes (Sessions, Memory, Skills) show one level at a time and walk with `↵`/`Esc`; dashboard panes (Home, Config, Help) stack and scroll. The tab bar becomes a focusable place, so `Tab` is free to walk panels. Sorting and the marquee are behaviours of the table widget, which moves to its own module along with the rest of the generic widgets.

**Tech Stack:** Python 3.11+, Textual 8.2.8, no new dependencies. Tests are plain functions with `assert`, run headless through `App.run_test`.

**Spec:** `docs/superpowers/specs/2026-08-23-tui-navigation-design.md`

## Global Constraints

- **Code, comments and docstrings are written in English.** Every user-facing string lives in `scripts/i18n.py` — never hardcode one in `tui_app.py`. (`CLAUDE.md`)
- **This repo is the public clone.** All code changes happen here; they reach the private clone through `sto update`. Never edit the same file in both.
- **Zero new dependencies.** Textual is the one optional library and nothing is added beside it.
- **No emoji** anywhere — in code, comments, commits or notes. Glyphs that carry data (`▲ ▼ ● ◐ ⚙ ✕`) are not emoji and stay.
- Run the full suite with:
  `uv run --no-project --with textual python scripts/test_tui_app.py`
  and the four stdlib suites with:
  `cd scripts && python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui.py`
- Commit messages: Conventional Commits, subject in Spanish, no Claude/Anthropic trailers.

---

### Task 1: Extract `tui_widgets.py`

Pure move, no behaviour change. It exists so Tasks 6 and 7 have somewhere to put the sort cycle and the marquee that is not the middle of a 1600-line file. The existing suite is the test: it passes before and after, unchanged.

**Files:**
- Create: `scripts/tui_widgets.py`
- Modify: `scripts/tui_app.py` (remove the moved definitions, add the import)
- Test: `scripts/test_tui_app.py` (unchanged — that is the point)

**Interfaces:**
- Consumes: nothing.
- Produces: module `tui_widgets` exporting `ACCENT_CSS`, `GROUNDS`, `BOX_ON`, `BOX_OFF`, `WORDMARK`, `WORDMARK_W`, `theme_for(ground, accent_code) -> Theme`, `bar(pct, width=24, warn=80) -> str`, `spark(values, width=24) -> str`, `ago(ts) -> str`, `clip(text, n) -> str`, `esc(text) -> str`, `Table(*spec, **kw)`, `Card(title, *children, upper=True, classes="", **kw)`, `Search(**kw)`, `Wordmark()`.

- [ ] **Step 1: Run the suite to record the green baseline**

```bash
cd "D:/Descargas/Web App Projects/sto-agentic-os"
uv run --no-project --with textual python scripts/test_tui_app.py
```

Expected: `OK`. If it is not green before the move, stop — this task cannot tell a move from a break.

- [ ] **Step 2: Create `scripts/tui_widgets.py`**

Move — do not retype — these definitions out of `tui_app.py`, in this order, keeping every docstring and comment exactly as it is: `ACCENT_CSS`, `GROUNDS`, `BOX_ON`/`BOX_OFF`, `theme_for`, `bar`, `spark`, `ago`, `clip`, `esc`, `Table`, `Card`, `Search`, `WORDMARK`, `WORDMARK_W`, `Wordmark`.

The file header:

```python
"""The widgets the screens are built from, and nothing that knows a screen.

`tui_app.py` is the six panes and the app. This is what they are made of: a
table that states its own column widths, a titled card, the search box, the
wordmark, and the four renderers that turn a number into something you can
look at.

Split out when the table grew a sort cycle and a marquee. A table's behaviour
interleaved with six screens is a file nobody can hold in their head, and the
table is the part that is going to keep growing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # scripts/ is not a package

import i18n  # noqa: E402
import ui  # noqa: E402

from textual.binding import Binding  # noqa: E402
from textual.containers import Container  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.coordinate import Coordinate  # noqa: E402
from textual.theme import Theme  # noqa: E402
from textual.widgets import DataTable, Input, Static  # noqa: E402

t = i18n.t
```

`Content` is used by `Wordmark`; `Binding` and `Coordinate` are for Tasks 5 and 7 and can be added when those tasks need them. The `re` module stays in `tui_app.py` — the two regexes that use it belong to the transcript renderer, which is a screen concern and does not move.

- [ ] **Step 3: Import them back into `tui_app.py`**

Replace the removed block with one explicit import, placed with the other local imports:

```python
from tui_widgets import (  # noqa: E402
    ACCENT_CSS, BOX_OFF, BOX_ON, GROUNDS, WORDMARK, WORDMARK_W, Card, Search,
    Table, Wordmark, ago, bar, clip, esc, spark, theme_for)
```

Explicit and not `import *`: the test suite reaches these through `tui_app.WORDMARK`, `tui_app.theme_for`, `tui_app.esc`, `tui_app.Table` and `tui_app.Search`, and a named import keeps every one of those working with no change to the tests.

- [ ] **Step 4: Run the suite**

```bash
uv run --no-project --with textual python scripts/test_tui_app.py
```

Expected: `OK`, with the same tests as Step 1. A failure here is a missed import or a definition left behind in both files.

- [ ] **Step 5: Check nothing else imported the moved names**

```bash
cd scripts && grep -n "tui_app\." *.py | grep -v "^test_tui_app.py"
```

Expected: no hits outside the test file. `ui.py` and `cli.py` do not import `tui_app`.

- [ ] **Step 6: Commit**

```bash
git add scripts/tui_widgets.py scripts/tui_app.py
git commit -m "refactor(tui): los widgets genericos a tui_widgets.py

Mudanza pura, sin cambio de comportamiento: la suite pasa igual antes y
despues. Sale del medio de tui_app.py lo que las pantallas consumen -- la
tabla, la card, el buscador, el wordmark y los cuatro renderers -- porque
la tabla esta por crecerle un ciclo de orden y un marquee, y ese codigo
interleaved con seis pantallas es un archivo que no entra en la cabeza."
```

---

### Task 2: Breakpoints, and the wordmark stops hiding

The smallest independent slice, and it fixes item 10 on its own.

**Files:**
- Modify: `scripts/tui_app.py` (`StoApp.on_resize`)
- Modify: `scripts/tui_app.tcss` (the narrow section)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: Task 1's `tui_widgets.WORDMARK_W` (51).
- Produces: three CSS classes on the app — `narrow` (width < 100), `tiny` (width < 56), `short` (height < 24). Later tasks style against `narrow`.

- [ ] **Step 1: Write the failing test**

Add to `scripts/test_tui_app.py`:

```python
def test_the_wordmark_goes_when_it_does_not_fit_and_not_before():
    """It is 51 columns and two rows, and it was hidden below 100 columns —
    at 70 it fits with nineteen to spare.

    What was actually broken at 70 was everything under it being pushed off
    the screen, which is a different bug with a different fix. Width and
    height get their own breakpoints so the banner answers for its own size.
    """
    async def go():
        for size, want in (((70, 30), True), ((50, 30), False), ((120, 20), False)):
            app = tui_app.StoApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                mark = app.query_one("#wordmark")
                assert mark.display is want, (size, mark.display, want)

    asyncio.run(go())
```

Register it in the `__main__` block.

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run --no-project --with textual python scripts/test_tui_app.py
```

Expected: `AssertionError: ((70, 30), False, True)` — the wordmark is hidden at 70 columns today.

- [ ] **Step 3: Three classes instead of one**

In `scripts/tui_app.py`, replace `StoApp.on_resize`:

```python
    def on_resize(self) -> None:
        # Textual CSS has no media query, so the breakpoints are classes the
        # app puts on itself and the stylesheet answers. Nothing else happens
        # here: a resize that re-ran the screens made dragging a window feel
        # like mud.
        #
        # Three and not one, because they answer three different questions.
        # `narrow` is "do two columns fit"; `tiny` and `short` are "does the
        # wordmark fit", which is a smaller box and its own pair of numbers.
        self.set_class(self.size.width < 100, "narrow")
        self.set_class(self.size.width < WORDMARK_W + 5, "tiny")
        self.set_class(self.size.height < 24, "short")
```

`WORDMARK_W + 5` and not a bare `56`: the margin is the padding the banner sits in, and if the art is ever redrawn the breakpoint follows it instead of going stale.

- [ ] **Step 4: Teach the stylesheet the two new classes**

In `scripts/tui_app.tcss`, in the narrow section, delete this line:

```css
.narrow #wordmark { display: none; }
```

and add, at the end of the file:

```css
/* ── the wordmark answers for its own size ──
 *
 * It is 51 columns by two rows. It was hidden with everything else that did
 * not fit in one column, which is why it disappeared at 70 columns with
 * nineteen to spare. `short` is the other half: on a wide, low terminal the
 * banner costs three of maybe fifteen usable rows to say what the screen
 * already says. */

.tiny #wordmark, .short #wordmark { display: none; }
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run --no-project --with textual python scripts/test_tui_app.py
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add scripts/tui_app.py scripts/tui_app.tcss scripts/test_tui_app.py
git commit -m "fix(tui): el wordmark se va cuando no entra, no cuando hay una columna

Mide 51 columnas y se ocultaba por debajo de 100: a 70 entra con
diecinueve de sobra. Lo que estaba roto a 70 era todo lo de abajo
empujado fuera de la pantalla, que es otro bug. Ahora hay tres
breakpoints -- narrow por dos columnas, tiny y short por el tamano del
banner -- y el umbral sale de WORDMARK_W, asi que sigue al arte si se
redibuja."
```

---

### Task 3: The dashboard panes stack and scroll

Fixes the measured bug: at 70x30 the Home does not render `USAGE` or `OVERALL` at all, and there is no scroll to reach them.

**Files:**
- Modify: `scripts/tui_app.tcss` (the narrow section)
- Modify: `scripts/tui_app.py` (`StoApp.compose`, plus the `#more` indicator and its watcher)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: Task 2's `narrow` class.
- Produces: `StoApp._more_check() -> None`, which shows or hides `#more`. Task 4 calls it after changing a level.

- [ ] **Step 1: Write the failing test**

```python
def test_every_card_of_the_home_is_reachable_in_one_column():
    """At 70x30 the home rendered SYNC and half of CONFIG PARITY, and USAGE
    and OVERALL were not on the screen at all.

    Not clipped — absent, with no scroll in the pane, so no key and no mouse
    could reach them. A `1fr` card inside an `auto` grid row resolves to the
    card's full natural height, and the first one took the screen.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(70, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            home = app.query_one("#home")
            assert home.max_scroll_y > 0, "the home does not scroll"
            assert app.query_one("#more").display, "nothing says there is more"
            home.scroll_end(animate=False)
            await pilot.pause()
            titles = [c.border_title for c in home.query(tui_app.Card)]
            assert "OVERALL" in titles, titles
            assert not app.query_one("#more").display, "the arrow stayed at the bottom"

    asyncio.run(go())
```

- [ ] **Step 2: Run it to verify it fails**

Expected: `AssertionError: the home does not scroll`.

- [ ] **Step 3: Let the narrow panes scroll**

In `scripts/tui_app.tcss`, replace the whole narrow section with:

```css
/* ── narrow: one column ──
 *
 * The cards stop being `1fr` here, and that is the whole fix. In the wide
 * grid every card sits in a `1fr` row and they share the height; the narrow
 * grid has `auto` rows, and a `1fr` card inside an `auto` row resolves to its
 * full natural height — for a table of forty-three sessions, several screens.
 * The first card took everything and the rest were laid out past the bottom
 * edge of a pane that could not scroll.
 */

.narrow #home-grid { grid-size: 1 4; grid-columns: 1fr; grid-rows: auto auto auto auto; }
.narrow .split { grid-size: 1 3; grid-columns: 1fr; grid-rows: 3 auto auto; }
.narrow .split > Search { column-span: 1; }
.narrow .three { grid-size: 1 3; grid-columns: 1fr; grid-rows: auto auto auto; }
.narrow #prefs, .narrow #remote { column-span: 1; }
.narrow .two { grid-size: 1 2; grid-columns: 1fr; grid-rows: auto auto; }

.narrow .card { height: auto; min-height: 6; }
/* without a ceiling one card is taller than three screens and the stack stops
 * being something you can scan. Both numbers are tuned against a rendered
 * screen, not derived: six is a heading and three rows, fourteen is about a
 * screenful. */
.narrow .card DataTable { height: auto; max-height: 14; }
.narrow .card VerticalScroll { height: auto; max-height: 14; }

/* the pane itself is what scrolls: no extra container, so the widget tree is
 * the same at every width and a resize moves nothing */
.narrow .home, .narrow .three, .narrow .two { overflow-y: auto; scrollbar-size-vertical: 1; }
```

Note `grid-rows` for `.split` becomes `3 auto auto` — the trailing `1fr` was the other half of why `#groups` swallowed the screen.

- [ ] **Step 4: Add the indicator**

In `scripts/tui_app.py`, in `StoApp.compose`, add `#more` immediately before `#status`:

```python
        yield Static("", id="more")
        yield Static("", id="status")
```

Add to `scripts/tui_app.tcss`:

```css
/* one row that says the pane goes on below, and stops saying it at the
 * bottom. Only down: the scrollbar already shows there is something above,
 * and a second indicator for a fact already on screen is noise. */
#more {
    dock: bottom;
    height: 1;
    text-align: center;
    color: $accent;
    background: $panel;
    display: none;
}
#more:hover { background: $surface; }
```

- [ ] **Step 5: Show and hide it**

Add to `StoApp`:

```python
    # ── the "there is more below" arrow ──

    def _scrollable(self):
        """The pane on screen, if it is one of the ones that scrolls."""
        pane = self.panes[self.tab]
        return pane if pane.max_scroll_y > 0 else None

    def _more_check(self) -> None:
        pane = self._scrollable()
        more = self.query_one("#more", Static)
        more.display = bool(pane and pane.scroll_y < pane.max_scroll_y - 0.5)
        if more.display:
            more.update(Content.from_markup("[$accent]▼[/]"))

    def on_click(self, event) -> None:
        """A tab chip is a button, and so is the arrow. Nothing on the bar
        looked like it could be clicked and everything on it can be."""
        node = event.widget
        if node is None or not node.id:
            return
        if node.id.startswith("tab-"):
            self.show_tab(int(node.id.removeprefix("tab-")))
        elif node.id == "more":
            pane = self._scrollable()
            if pane is not None:
                pane.scroll_page_down(animate=False)
```

The `- 0.5` is not superstition: `scroll_y` is a float and lands a hair short of `max_scroll_y` at the bottom, which left the arrow on screen pointing at nothing.

Replace the existing `on_click` with the version above — it keeps the tab-chip branch and adds the arrow.

- [ ] **Step 6: Watch the scroll**

In `StoApp.on_mount`, after `self.show_tab(self.tab)`:

```python
        # the arrow follows the scroll of whichever pane is on screen. `watch`
        # on the reactive rather than a timer: this has to be right the frame
        # the scroll lands, and it costs nothing when nothing scrolls.
        for pane in self.panes:
            self.watch(pane, "scroll_y", self._more_check, init=False)
```

and call `self._more_check()` at the end of `show_tab` and at the end of `on_resize`.

- [ ] **Step 7: Run the test to verify it passes**

Expected: `OK`. If `OVERALL` is still missing, check that `.narrow .card` really lost `height: 1fr` — the `.card` rule earlier in the file sets it and the narrow rule has to come after.

- [ ] **Step 8: Verify by eye at three sizes**

```bash
cd scripts && PYTHONIOENCODING=utf-8 uv run --no-project --with textual python - <<'EOF'
import asyncio, sys
sys.path.insert(0, ".")
import tui_app

async def go():
    for size in ((70, 30), (70, 20), (46, 24)):
        app = tui_app.StoApp()
        async with app.run_test(size=size) as pilot:
            await app.workers.wait_for_complete()
            for tab in "156":
                await pilot.press(tab)
                await pilot.pause()
                print(f"===== {size} tab={tab} =====")
                print("\n".join(s.text.rstrip()
                                for s in app.screen._compositor.render_strips()))
asyncio.run(go())
EOF
```

Every card must have a bottom border, and `▼` must be on the last row while there is more below. Tune `min-height` and `max-height` here if a card looks starved.

- [ ] **Step 9: Commit**

```bash
git add scripts/tui_app.py scripts/tui_app.tcss scripts/test_tui_app.py
git commit -m "fix(tui): en una columna el home scrollea y dice que sigue abajo

A 70x30 el home no renderizaba USAGE ni OVERALL. No estaban recortados:
no estaban, y sin scroll en el pane no habia tecla ni mouse que los
alcanzara. Una card \`height: 1fr\` adentro de una fila de grid \`auto\`
resuelve a su altura natural entera, y la primera se quedaba con la
pantalla.

En angosto las cards pasan a \`height: auto\` con techo, y el pane mismo
scrollea -- sin contenedor extra, asi que el arbol de widgets es el mismo
a cualquier ancho y un resize no mueve nada. Un renglon abajo marca que
sigue, es clickeable, y deja de marcarlo al llegar al fondo."
```

---

### Task 4: Hierarchical panes drill down

**Files:**
- Modify: `scripts/tui_app.py` (`Split`, `Sessions`, `Memory`, `Skills`, `StoApp.on_resize`)
- Modify: `scripts/tui_app.tcss` (remove `.narrow #detail { display: none; }`)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: Task 2's `narrow` class, Task 3's `StoApp._more_check`.
- Produces on every hierarchical pane: `LEVELS: tuple[str, ...]` (widget ids, outermost first), `self.level: int`, `set_level(n: int) -> None`, `back() -> bool` (returns `True` if it moved). Task 5 calls `back()` from the `Esc` binding.

- [ ] **Step 1: Write the failing test**

```python
def test_a_narrow_split_shows_one_level_and_walks_between_them():
    """Picking a project and reading what it holds is a hierarchy, and in one
    column a hierarchy is one panel at a time.

    The level is state on the pane, not a screen stack: the widgets stay
    mounted, so widening the terminal mid-drill-down shows all the panels with
    the cursor and the search text where they were.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(70, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            pane = app.query_one("#sessions")
            assert pane.level == 0, pane.level
            assert app.query_one("#groups").display
            assert not app.query_one("#rows").display

            groups = app.query_one("#t-groups", tui_app.Table)
            groups.move_cursor(row=2)
            await pilot.pause()
            picked = groups.cursor_row

            await pilot.press("enter")            # into the project
            await pilot.pause()
            assert pane.level == 1, pane.level
            rows = app.query_one("#rows")
            assert rows.display, "the session list is still not on screen"
            assert not app.query_one("#groups").display

            await pilot.press("escape")           # back out
            await pilot.pause()
            assert pane.level == 0, pane.level
            assert app.query_one("#groups").display
            # the widgets stayed mounted, so coming back is coming back to
            # where you were and not to the top of the list
            assert app.query_one("#t-groups", tui_app.Table).cursor_row == picked

    asyncio.run(go())


def test_a_wide_split_shows_every_level_at_once():
    """The wide behaviour does not change: `level` only says who holds the
    focus. Widening is not supposed to unwind anything."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#groups").display
            assert app.query_one("#rows").display
            assert app.query_one("#rows").query_one(tui_app.Table).has_focus

    asyncio.run(go())
```

- [ ] **Step 2: Run to verify both fail**

Expected: `AttributeError: 'Sessions' object has no attribute 'level'`.

- [ ] **Step 3: Write the `Levels` mixin**

In `scripts/tui_app.py`, immediately above `class Split`:

```python
class Levels:
    """Panels that are a hierarchy: in one column, one of them at a time.

    Sessions, memories and skills ask the same shape of question — pick the
    group, then the item, then read it — and the only thing that differs is
    how deep it goes. `LEVELS` says that, and the rest is the same for all
    three, so it is written once here rather than three times below.
    """

    # the panels, outermost first, by widget id
    LEVELS = ()

    def set_level(self, n) -> None:
        """Which panel is on screen when only one fits.

        A number on the pane and not a `push_screen` per level: the widgets
        stay mounted either way, so the cursor, the search text and the loaded
        rows survive a resize. Widen the terminal in the middle of a
        drill-down and every panel appears with everything where you left it —
        a screen stack would have had to unwind, and a resize that unwinds a
        stack is a resize that loses your place.
        """
        self.level = max(0, min(n, len(self.LEVELS) - 1))
        narrow = self.app.has_class("narrow")
        for i, name in enumerate(self.LEVELS):
            self.query_one(f"#{name}").display = not narrow or i == self.level
        # the search box belongs to the outermost level: it filters the list
        # you are about to pick from, and under a document it is a box that
        # does nothing
        self.query_one("#search", Search).display = not narrow or self.level == 0
        if narrow:
            table = self.query_one(f"#{self.LEVELS[self.level]}").query(Table)
            if table:
                table.first().focus()
        self.app._more_check()

    def back(self) -> bool:
        """`Esc`. True if it moved, so the app knows whether to swallow the key."""
        if self.app.has_class("narrow") and self.level > 0:
            self.set_level(self.level - 1)
            return True
        return False

    def drill(self) -> bool:
        """`↵` going one panel deeper. True if it moved.

        Only in one column: in a wide window every panel is already on screen,
        and `↵` there means what it has always meant.
        """
        if self.app.has_class("narrow") and self.level < len(self.LEVELS) - 1:
            self.set_level(self.level + 1)
            return True
        return False
```

Then change the two class statements:

```python
class Split(Levels, Container):
    LEVELS = ("groups", "rows")

class Skills(Levels, Container):
    LEVELS = ("rows", "detail")
```

`Split` is two panels because the third thing you look at is a whole document with its own screen; `Skills` is three, with the detail as a real panel.

- [ ] **Step 4: Initialise it and route `↵`**

In `Split.on_mount`, before `self.refresh_data()`:

```python
        self.level = 0
```

and at the end of `on_mount`, replace the focus line with:

```python
        # focus starts on the left: you pick the project first, and the
        # right-hand list is what you move to once you have
        self.set_level(0)
        self.query_one("#t-groups", Table).focus()
```

Replace `Split.open`:

```python
    def open(self) -> None:
        """`↵` on whichever panel has the focus.

        The app binds `enter` with priority — it has to, or the tables eat it
        and the other screens lose their opener — so the routing has to happen
        here rather than in a per-table handler.
        """
        # in one column a project is a folder, and a folder opens into the
        # panel that holds its contents
        if self.drill():
            return
        if self.query_one("#t-groups", Table).has_focus:
            return self.query_one("#t-rows", Table).focus()
        self.open_row()
```

- [ ] **Step 5: `Skills` drills the same way**

`Skills` already has `LEVELS` and the mixin from Step 3. Its `open` keeps its own body — it reads a `SKILL.md` and pushes a `Reader` — with the same two lines in front:

```python
    def open(self) -> None:
        if self.drill():
            return
        table = self.query_one("#t-rows", Table)
        if not self.rows:
            return
        r = self.rows[table.cursor_row]
        skill = srv.get_skill(r["id"]) if r["what"] == "skill" else None
        if skill is None:
            # a plugin has no SKILL.md to read, and neither does a skill the
            # repo has but this machine never installed
            return self.app.notify(t("empty"))
        self.app.push_screen(Reader(skill["name"], skill["content"]))
```

Add `self.level = 0` to the start of `Skills.on_mount` and `self.set_level(0)` at its end, the same two lines Step 4 adds to `Split.on_mount`.

- [ ] **Step 6: Let the detail panel exist in one column**

In `scripts/tui_app.tcss`, delete:

```css
.narrow #detail { display: none; }
```

That panel stops being something hidden in a narrow window and becomes the pane's last level, which is the only way its content was ever reachable there.

- [ ] **Step 7: Re-apply the level when the width changes**

At the end of `StoApp.on_resize`:

```python
        # re-apply, because which panels are displayed depends on `narrow` and
        # this is the moment it changed. Toggling `display` on three widgets,
        # not recomposing a screen: that was tried and it made dragging a
        # window feel like mud.
        for pane in self.panes:
            if hasattr(pane, "set_level"):
                pane.set_level(pane.level)
```

- [ ] **Step 8: Run the tests to verify they pass**

Expected: `OK`, both new tests and the existing `test_focus_starts_on_the_left_and_a_project_hands_it_to_the_right` (which runs at 140 columns and must be unaffected).

- [ ] **Step 9: Commit**

```bash
git add scripts/tui_app.py scripts/tui_app.tcss scripts/test_tui_app.py
git commit -m "feat(tui): en una columna las tabs jerarquicas bajan de nivel

Sesiones, memorias y skills son la misma pregunta -- elegi el grupo,
despues el item, despues leelo -- y en una columna eso es un panel a la
vez. El nivel es estado del pane, no una pila de pantallas: los widgets
quedan montados, asi que ensanchar la terminal a mitad de camino muestra
todos los paneles con el cursor y el texto de busqueda donde estaban.

De paso el panel de detalle deja de estar oculto en angosto: pasa a ser
el ultimo nivel, que es la unica forma en que su contenido se alcanzaba
ahi."
```

---

### Task 5: `Tab` walks panels and the tab bar is a place

**Files:**
- Modify: `scripts/tui_app.py` (`StoApp.BINDINGS`, new `TabBar`, `StoApp.compose`, actions)
- Modify: `scripts/tui_widgets.py` (`Table.action_cursor_up`, `Search` bindings)
- Modify: `scripts/tui_app.tcss` (the focused tab bar)
- Test: `scripts/test_tui_app.py` (rewrite one, add two)

**Interfaces:**
- Consumes: Task 4's `back()`.
- Produces: `StoApp.focus_tabs() -> None`, `StoApp.action_panel_next()`, `StoApp.action_panel_prev()`, `TabBar` (a focusable `Container` with id `tabs`).

- [ ] **Step 1: Rewrite the test that fixes the old model**

`test_tab_walks_the_tab_bar_and_a_document_has_its_own_keys` asserts that `Tab` cycles tabs, which is the opposite of the new model. The reader half of it is still true and stays.

Rename it to `test_a_document_has_its_own_keys` (in the definition and in the `__main__` block), rewrite its docstring to drop the sentence about `tab`, and delete exactly this block from its body:

```python
            for expected in (1, 2, 3):
                await pilot.press("tab")
                await pilot.pause()
                assert app.tab == expected, (app.tab, expected)
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.tab == 2, app.tab
```

Everything from `await pilot.press("2")` onward — opening a session, the footer without `PUSH`, `pagedown` scrolling the document, `escape` coming back — is unchanged. Then add:

```python
def test_tab_walks_panels_and_the_tab_bar_is_somewhere_you_can_stand():
    """`Tab` used to cycle the six tabs, which left nothing for the panels
    inside one — so half the interface could only be reached with a mouse.

    Now `Tab` walks the panels of the pane you are on and wraps through the
    tab bar, which is focusable: standing on it, the arrows change tab and
    `↓` drops back into the content. `1`-`6` still jump directly, from
    anywhere.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            seen = set()
            for _ in range(6):
                await pilot.press("tab")
                await pilot.pause()
                assert app.tab == 2, "tab changed the pestana, not the panel"
                if app.focused is not None:
                    seen.add(app.focused.id)
            assert {"t-groups", "t-rows"} <= seen, seen
            assert "tabs" in seen, seen

            app.query_one("#tabs").focus()
            await pilot.press("right")
            await pilot.pause()
            assert app.tab == 3, app.tab
            await pilot.press("left")
            await pilot.pause()
            assert app.tab == 2, app.tab
            await pilot.press("down")
            await pilot.pause()
            assert app.focused is not None and app.focused.id != "tabs"

            await pilot.press("5")
            await pilot.pause()
            assert app.tab == 4, app.tab

    asyncio.run(go())


def test_up_leaves_a_list_only_from_its_first_row():
    """The escape hatch upward cannot eat ordinary navigation: holding `↑` to
    reach the top of a list has to reach the top of the list."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            table = app.query_one("#t-groups", tui_app.Table)
            table.focus()
            table.move_cursor(row=3)
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            assert app.focused is table, "up left the list from row 3"
            assert table.cursor_row == 2, table.cursor_row
            for _ in range(3):
                await pilot.press("up")
                await pilot.pause()
            assert table.cursor_row == 0, table.cursor_row
            await pilot.press("up")
            await pilot.pause()
            assert app.focused is app.query_one("#tabs"), app.focused

    asyncio.run(go())
```

- [ ] **Step 2: Run to verify they fail**

Expected: the first fails on `assert app.tab == 2` (Tab still changes the pestaña); the second on the last assertion.

- [ ] **Step 3: A focusable tab bar**

In `scripts/tui_app.py`, above `class StoApp`:

```python
class TabBar(Container):
    """The row of tabs, and a place the keyboard can stand.

    `Tab` is the natural key for walking the panels inside a screen, and it
    was spent on walking the screens themselves — which left the panels
    reachable only with a mouse. Moving it means the tab bar needs its own way
    in, so it takes focus like anything else: from `Tab` wrapping round the
    end of the pane, or from `↑` at the top of the first list.
    """
    can_focus = True

    BINDINGS = [
        Binding("left", "app.prev_tab", "", show=False),
        Binding("right", "app.next_tab", "", show=False),
        Binding("down,enter,escape", "leave", "", show=False),
    ]

    def action_leave(self) -> None:
        self.screen.focus_next()
```

In `StoApp.compose`, replace the tabs container:

```python
            with TabBar(id="tabs"):
                for i, key in enumerate(TABS):
                    yield Static(f" {t(key)} ", classes="tab", id=f"tab-{i}")
```

- [ ] **Step 4: Rebind `Tab`**

In `StoApp.BINDINGS`, replace the two tab bindings:

```python
        # priority: Tab is the library's focus-next by default, and ours has to
        # wrap through the tab bar rather than wander the whole DOM
        Binding("tab", "panel_next", "panel", priority=True),
        Binding("shift+tab", "panel_prev", "", show=False, priority=True),
        Binding("escape", "back", "", show=False),
```

and replace `action_prev_tab` / `action_next_tab`'s neighbours with:

```python
    def action_panel_next(self) -> None:
        """The next panel of the pane you are on.

        `focus_next` walks the DOM and skips anything hidden, so a pane that is
        not on screen is not in the way and a narrow pane offers only the level
        you are looking at. The tab bar is the first node, so wrapping past the
        last panel lands on it, which is what makes it reachable at all.
        """
        self.screen.focus_next()

    def action_panel_prev(self) -> None:
        self.screen.focus_previous()

    def focus_tabs(self) -> None:
        self.query_one("#tabs", TabBar).focus()

    def action_back(self) -> None:
        """`Esc` climbs one level, and does nothing at the top."""
        pane = self.panes[self.tab]
        if hasattr(pane, "back"):
            pane.back()
```

Keep `action_prev_tab` and `action_next_tab` — `TabBar` calls them by name and `1`-`6` still route through `action_tab`.

- [ ] **Step 5: `↑` at the top of a list**

In `scripts/tui_widgets.py`, add to `class Table(DataTable)`:

```python
    def action_cursor_up(self) -> None:
        """At the top of the list, `↑` leaves it for the tab bar.

        Only at the top: holding `↑` to reach the first row has to reach the
        first row, and a hatch that opens one press early is a hatch you fall
        through every time you use the list normally.
        """
        if self.cursor_row <= 0:
            return self.app.focus_tabs()
        super().action_cursor_up()
```

and to `class Search(Input)`:

```python
    BINDINGS = [Binding("up", "to_tabs", "", show=False)]

    def action_to_tabs(self) -> None:
        # a one-line box has no vertical cursor for `↑` to consume, so there is
        # no top to reach first
        self.app.focus_tabs()
```

Add `from textual.binding import Binding` to the imports of `tui_widgets.py`.

- [ ] **Step 6: Show the focused bar**

In `scripts/tui_app.tcss`, after the `.tab` rules:

```css
/* a bar that is taking your arrow keys and a bar that is not have to look
 * different, the same rule the cards already follow */
TabBar:focus { background: $surface; }
TabBar:focus .tab { color: $foreground 80%; }
TabBar:focus .tab.on { background: $accent; color: $background; }
```

- [ ] **Step 7: Run the tests to verify they pass**

Expected: `OK`. If `Tab` still changes the pestaña, the old `Binding("tab", "next_tab", ...)` is still in `BINDINGS` — both entries have `priority=True` and the first one wins.

- [ ] **Step 8: Walk the whole interface with the keyboard, by hand**

```bash
uv run --no-project --with textual python scripts/tui_app.py
```

Without touching the mouse: reach every panel of every tab, drill into a project and back out with `Esc`, get to the tab bar with `↑` and with `Tab`, change tab from there, and come back down. Anything unreachable is a bug in this task.

- [ ] **Step 9: Commit**

```bash
git add scripts/tui_app.py scripts/tui_widgets.py scripts/tui_app.tcss scripts/test_tui_app.py
git commit -m "feat(tui): Tab recorre paneles y la barra de tabs es un lugar

Tab era la tecla natural para moverse adentro de una pantalla y estaba
gastada en moverse entre pantallas, asi que la mitad de la interfaz solo
se alcanzaba con mouse. Ahora Tab recorre los paneles del pane y da la
vuelta por la barra, que toma foco: parado ahi las flechas cambian de
pestana y bajas con flecha abajo. Los numeros 1-6 siguen saltando
directo.

No se escribio un anillo de foco propio: focus_next de la libreria ya
recorre el DOM y saltea lo oculto. La flecha arriba sale de una lista
solo desde la primera fila -- una salida que se abre una tecla antes es
una por la que te caes cada vez que usas la lista."
```

---

### Task 6: Sorting by column

**Files:**
- Modify: `scripts/tui_widgets.py` (`Table`)
- Modify: `scripts/tui_app.py` (the `s` binding, the column specs)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: Task 1's `Table`.
- Produces: `Table.spec` entries of `(label, width)` or `(label, width, kind)` where `kind` is `"num"` or `"text"`; `Table.cycle_sort(column: int | None = None) -> None`; `Table.sort_by: tuple[int, bool] | None`.

- [ ] **Step 1: Write the failing test**

```python
def test_s_cycles_the_sort_and_comes_back_to_the_natural_order():
    """One key with the semantics of a header click: next sortable column
    ascending, or reverse it if you are already on it.

    `unsorted` is a real state in the cycle and it is the pane's own order —
    these lists are newest-first, which is what you want almost always — so
    `s` can never strand you in an order you cannot leave.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            table = app.query_one("#t-rows", tui_app.Table)
            table.focus()
            if table.row_count < 2:
                return                      # a machine with one session
            natural = [table.get_row_at(i)[5] for i in range(table.row_count)]

            await pilot.press("s")
            await pilot.pause()
            assert table.sort_by is not None, "s did not sort"
            col, reverse = table.sort_by
            assert reverse is False, table.sort_by
            up = [table.get_row_at(i)[col] for i in range(table.row_count)]
            assert up == sorted(up, key=str.lower), up

            await pilot.press("s")
            await pilot.pause()
            assert table.sort_by == (col, True), table.sort_by

            seen = {table.sort_by}
            for _ in range(20):
                await pilot.press("s")
                await pilot.pause()
                if table.sort_by is None:
                    break
                seen.add(table.sort_by)
            assert table.sort_by is None, "the cycle never returned to unsorted"
            after = [table.get_row_at(i)[5] for i in range(table.row_count)]
            assert after == natural, "unsorted is not the pane's own order"

    asyncio.run(go())


def test_a_column_whose_only_correct_order_is_the_default_is_not_in_the_cycle():
    """`when` renders `2 h`, `5 d`, `3 w`. Sorted as text that interleaves
    hours with weeks; sorted correctly it is `mtime`, which is already the
    order the pane arrives in."""
    table = tui_app.Table((tui_app.t("col_when"), 10),
                          (tui_app.t("col_project"), 18, "text"),
                          (tui_app.t("col_prompts"), 7, "num"))
    assert table.sortable == [1, 2], table.sortable
```

- [ ] **Step 2: Run to verify it fails**

Expected: `AttributeError: 'Table' object has no attribute 'sortable'`.

- [ ] **Step 3: Teach `Table` the spec's third field**

In `scripts/tui_widgets.py`, in `Table.__init__`, after `self.spec = spec`:

```python
        # a third field says how a column sorts, and its absence says it does
        # not. Declared and not guessed: `when` renders `2 h` and `5 d`, and a
        # heuristic that sorts that as text interleaves hours with weeks
        self.sortable = [i for i, col in enumerate(spec) if len(col) > 2]
        self.sort_by = None
        self._labels = [col[0] for col in spec]
```

and in `on_mount`, unpack only the first two fields:

```python
    def on_mount(self) -> None:
        for col in self.spec:
            self.add_column(col[0], width=col[1] or 1)
```

`fit()` reads `self.spec[-1][1]`, which is still the width — no change needed there.

- [ ] **Step 4: The cycle**

Add to `Table`:

```python
    SORT_KEYS = {"num": lambda v: float(str(v).strip() or 0),
                 "text": lambda v: str(v).lower()}

    def _key(self, kind):
        """A sort key that survives the cells it is given.

        A numeric column can hold `·` for "none" and a text one can hold a
        `Content`; either raises inside `sorted` and takes the whole table
        with it. Anything unparseable sorts as if it were empty, which puts it
        at one end instead of crashing.
        """
        base = self.SORT_KEYS[kind]

        def key(value):
            try:
                return base(value)
            except (TypeError, ValueError):
                return 0 if kind == "num" else ""
        return key

    def cycle_sort(self, column=None) -> None:
        """One step of `s`, or a click straight onto a header.

        The semantics of a header click, which is the thing everybody already
        knows: the next sortable column ascending, or the same column reversed
        if you are already on it. Past the last sortable column the cycle ends
        at `None`, which is the order the pane wrote — so `s` can never strand
        you in a sort you cannot leave.
        """
        if not self.sortable:
            return
        if column is not None:
            # a click names its column, so the only question is the direction
            if column not in self.sortable:
                return
            same = self.sort_by is not None and self.sort_by[0] == column
            self.sort_by = (column, bool(same and not self.sort_by[1]))
        elif self.sort_by is None:
            self.sort_by = (self.sortable[0], False)
        elif not self.sort_by[1]:
            self.sort_by = (self.sort_by[0], True)          # same column, reversed
        else:
            nxt = self.sortable.index(self.sort_by[0]) + 1
            self.sort_by = ((self.sortable[nxt], False)
                            if nxt < len(self.sortable) else None)
        self.apply_sort()

    def apply_sort(self) -> None:
        """Sort the rows, and put the arrow on the header that did it."""
        for i, col in enumerate(self.columns.values()):
            arrow = ""
            if self.sort_by and self.sort_by[0] == i:
                arrow = " ▼" if self.sort_by[1] else " ▲"
            # rebuilt from the kept label, never appended to the live one, or
            # the arrow compounds one per press
            col.label = Content(self._labels[i] + arrow)
        self.refresh()
        if self.sort_by is None:
            return self.refill()
        index, reverse = self.sort_by
        self.sort(list(self.columns.keys())[index],
                  key=self._key(self.spec[index][2]), reverse=reverse)

    def refill(self) -> None:
        """Back to the order the pane wrote the rows in.

        There is no key that means "the order they arrived": `DataTable.sort`
        only ever sees cell values, never the row key, so the arrival order is
        not reachable from inside a sort. The pane does know it — it is the
        order `refresh_data` writes — so unsorting is asking it to write them
        again. That is cheap: the session list is behind an mtime-keyed cache
        and the memory list is a directory walk.
        """
        for node in self.ancestors_with_self:
            if node is not self and hasattr(node, "refresh_data"):
                return node.refresh_data()
```

`self.refresh()` after rewriting the labels is not optional: `Column.label` is a plain dataclass field, so assigning it changes nothing on screen by itself.

- [ ] **Step 5: Bind `s` and the header click**

In `Table`:

```python
    def on_data_table_header_selected(self, event) -> None:
        event.stop()
        self.cycle_sort(event.column_index)
```

In `StoApp.BINDINGS`:

```python
        Binding("s", "sort", "sort"),
```

In `StoApp`:

```python
    def action_sort(self) -> None:
        """`s` sorts the table the keys are pointed at, and nothing else."""
        if isinstance(self.focused, Input):
            return
        if isinstance(self.focused, Table):
            self.focused.cycle_sort()
```

- [ ] **Step 6: Declare which columns sort**

In `scripts/tui_app.py`, update the column specs:

```python
# Sessions.make_table
        return Table((t("col_when"), 10), (t("col_project"), 18, "text"),
                     (t("col_prompts"), 7, "num"), (t("col_tools"), 6, "num"),
                     (t("col_errors"), 7), (t("col_title"), None, "text"),
                     id="t-rows")

# Memory.make_table
        return Table((t("col_slug"), 28, "text"), (t("col_when"), 9),
                     (t("col_machine"), 14, "text"), (t("col_desc"), None, "text"),
                     id="t-rows")

# Skills.compose
                   Table((t("col_name"), 34, "text"), (t("col_desc"), None, "text"),
                         id="t-rows"),

# Split.compose
                   Table((t("col_project"), self.GROUP_W - 14, "text"),
                         (t("col_total"), None, "num"), id="t-groups"),
```

`col_errors` is left out on purpose: its cells are `Content` with markup, so they cannot be compared as text or parsed as numbers. `col_when` is left out for the reason in the test.

- [ ] **Step 7: Run the tests to verify they pass**

Expected: `OK`.

- [ ] **Step 8: Commit**

```bash
git add scripts/tui_widgets.py scripts/tui_app.py scripts/test_tui_app.py
git commit -m "feat(tui): s ordena la tabla con la semantica del click de header

Una sola tecla: la siguiente columna ordenable ascendente, o la misma
invertida si ya estas en ella. El ultimo paso es sin orden -- el orden en
que el pane lleno la tabla, que en estas listas es lo mas nuevo primero
-- asi que el ciclo siempre lleva de vuelta afuera. Click en el header
hace lo mismo saltando a esa columna.

Que columna ordena lo declara la tabla, no una heuristica: when muestra
2 h y 5 d, y ordenarlo como texto intercala horas con semanas. Su orden
correcto es mtime, que ya es el que trae."
```

---

### Task 7: The marquee on the selected row

**Files:**
- Modify: `scripts/tui_widgets.py` (`Table`)
- Test: `scripts/test_tui_app.py`

**Interfaces:**
- Consumes: Task 1's `Table`, Task 6's `_labels`/`spec` handling.
- Produces: `Table.raw: dict[tuple[int, int], str]`, `Table.marquee_start() -> None`, `Table.marquee_reset() -> None`, `Table._marquee_tick() -> None`, and `Table._marquee: tuple | None` (the running timer, or `None` when nothing is moving).

- [ ] **Step 1: Write the failing test**

```python
def test_the_marquee_runs_only_where_text_is_cut_and_only_with_focus():
    """The selected row scrolls what its column cut off — the selected row and
    no other, and only while the table has the keys.

    Both halves matter. A timer for a row that fits is a screen that moves for
    nothing, and a table animating in a pane nobody is looking at is a screen
    that never sits still.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(70, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            table = app.query_one("#t-rows", tui_app.Table)
            if table.row_count == 0:
                return
            table.focus()
            await pilot.pause()
            assert table.raw, "no raw cell text was kept"

            table.move_cursor(row=0)
            await pilot.pause()
            cut = any(len(v) > list(table.columns.values())[c].get_render_width(table)
                      for (r, c), v in table.raw.items() if r == 0)
            assert (table._marquee is not None) is cut, (cut, table._marquee)

            app.query_one("#t-groups", tui_app.Table).focus()
            await pilot.pause()
            assert table._marquee is None, "the marquee outlived the focus"

    asyncio.run(go())
```

- [ ] **Step 2: Run to verify it fails**

Expected: `AssertionError: no raw cell text was kept`.

- [ ] **Step 3: Keep the raw text**

In `scripts/tui_widgets.py`, in `Table.__init__`:

```python
        # what `add_row` was given, before the column cut it. Only the plain
        # strings: a `Content` carries markup and slicing it cuts a tag in half
        self.raw = {}
        self._marquee = None
```

and:

```python
    def add_row(self, *cells, **kw):
        row = super().add_row(*cells, **kw)
        index = self.row_count - 1
        for col, value in enumerate(cells):
            if isinstance(value, str):
                self.raw[(index, col)] = value
        return row

    def clear(self, *args, **kw):
        self.raw.clear()
        self.marquee_reset()
        return super().clear(*args, **kw)
```

- [ ] **Step 4: The marquee itself**

```python
    MARQUEE_TICK = 0.2      # seconds per column of travel
    MARQUEE_HOLD = 5        # ticks of stillness at each end

    def marquee_reset(self) -> None:
        if self._marquee is not None:
            self._marquee[0].stop()
            self._marquee = None

    def marquee_start(self) -> None:
        """Scroll whatever this row's columns cut off, and nothing else.

        Tied to the focus on purpose: at most one row, in one table, is ever
        moving, and it is the one the keys are pointed at. A table that is not
        being looked at holds no timer at all.
        """
        self.marquee_reset()
        if not self.has_focus:
            return
        row = self.cursor_row
        widths = [c.get_render_width(self) for c in self.columns.values()]
        over = {col: text for (r, col), text in self.raw.items()
                if r == row and col < len(widths) and len(text) > widths[col]}
        if not over:
            return                        # the common case costs nothing
        self._marquee = (self.set_interval(self.MARQUEE_TICK, self._marquee_tick),
                         row, over, widths, [-self.MARQUEE_HOLD])

    def _marquee_tick(self) -> None:
        _, row, over, widths, state = self._marquee
        state[0] += 1
        longest = max(len(v) - widths[c] for c, v in over.items())
        if state[0] > longest + self.MARQUEE_HOLD:
            state[0] = -self.MARQUEE_HOLD
        offset = max(0, min(state[0], longest))
        for col, text in over.items():
            self.update_cell_at(Coordinate(row, col), text[offset:])

    def on_data_table_row_highlighted(self, event) -> None:
        self.marquee_start()

    def on_focus(self) -> None:
        self.marquee_start()

    def on_blur(self) -> None:
        self.marquee_reset()

    def on_hide(self) -> None:
        self.marquee_reset()
```

Add `from textual.coordinate import Coordinate` to the imports of `tui_widgets.py`.

The negative start (`-MARQUEE_HOLD`) is the pause before it moves: a row that starts sliding the instant the cursor lands on it is unreadable while you are still finding it.

- [ ] **Step 5: Do not let the panes lose their own handler**

`Split` and `Skills` already define `on_data_table_row_highlighted`. A handler on `Table` and a handler on the pane both run — Textual bubbles the message — so the pane's `preview()` and the marquee coexist with no change. Verify by running the existing suite, which covers `preview`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run --no-project --with textual python scripts/test_tui_app.py
```

Expected: `OK`, all tests including the pre-existing ones.

- [ ] **Step 7: Watch it by hand at 70 columns**

```bash
uv run --no-project --with textual python scripts/tui_app.py
```

Narrow the terminal to about 70 columns, go to Sessions, drill into a project and walk the rows. A row with a long title must start sliding after about a second; moving the cursor must reset it; `Tab` away must stop it dead.

- [ ] **Step 8: Run the four stdlib suites**

```bash
cd scripts && python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui.py
```

Expected: `OK` from each. Nothing in this sub-project touches them, and that is what this confirms.

- [ ] **Step 9: Commit**

```bash
git add scripts/tui_widgets.py scripts/test_tui_app.py
git commit -m "feat(tui): la fila seleccionada desplaza lo que la columna corta

La fila donde estas parado y ninguna otra, y solo mientras la tabla tiene
las teclas. Las dos mitades importan: un timer para una fila que entera
es una pantalla que se mueve al pedo, y una tabla animando en un pane que
nadie mira es una pantalla que no se queda quieta nunca.

Solo las celdas que son str: un Content lleva markup y cortarlo parte una
etiqueta al medio. Si nada esta cortado no se arranca ningun timer, que
es el caso comun."
```

---

## Closing the sub-project

- [ ] **Write the wiki note.** In the **private** clone (`../my-agentic-os`), extend `vault/wiki/sto-tui-textual.md` with what this pass found: the `1fr`-card-inside-an-`auto`-row mechanism, why the level is state and not a screen stack, and the `Tab`/tab-bar model. Update `vault/wiki/index.md`. Knowledge is committed in the private clone; code is committed here.
- [ ] **Do not push.** Leave both clones committed and unpushed unless asked.
