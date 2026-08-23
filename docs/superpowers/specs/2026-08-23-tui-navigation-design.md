# TUI navigation and responsive layout

Sub-project **B** of the Textual TUI pass. It covers five of the twelve items on
the list: reachable panels in a narrow terminal (2), the selected row showing
text a column cut off (4), sorting by column (6), keyboard-only navigation
across the whole interface (7), and the wordmark surviving a narrow window (10).

Everything here is `scripts/tui_app.py`, `scripts/tui_app.tcss` and a new
`scripts/tui_widgets.py`. Nothing touches the engine.

---

## The bug, measured

Rendered headless at 70x30 — a perfectly ordinary half-screen terminal — with
the app in its current state:

| tab | what is on screen | what is missing |
|---|---|---|
| Home | `SYNC`, and `CONFIG PARITY` cut off without its bottom border | `USAGE` and `OVERALL` are **not rendered at all** |
| Sessions | `PROJECTS` only, padded with empty rows to the bottom | the session table **does not exist on screen** |
| Config | `PREFERENCES` only, padded to the bottom | `MODULES` and `REMOTE` |

At 70x20 the home shows `SYNC` and nothing else.

This is not clipping. There is no scroll anywhere in a pane, so the content
below the fold is unreachable by any means — no key, no mouse. The Sessions tab
cannot show a single session in a narrow window.

**The mechanism.** `.card` is `height: 1fr`. In the wide grid every card sits in
a row that is also `1fr`, so they share the height. The narrow rules change the
grid to one column with `grid-rows: 3 auto 1fr`, and a `1fr` card inside an
`auto` row resolves to the card's full natural height — which for a `DataTable`
of 43 sessions is far taller than the screen. The first card takes everything
and the rest are laid out past the bottom edge.

The wordmark is a separate, smaller bug: `.narrow #wordmark { display: none }`
hides it below 100 columns although it is 51 columns wide.

---

## What the layout becomes

Two behaviours, chosen by what the pane *is*, not by its width alone.

### Splits drill down

Sessions, Memory and (after sub-project C) Tools are a hierarchy: pick the
project, then read what it holds. In a narrow window they show **one panel at a
time** and `↵` walks forward, `Esc` walks back.

The level is state on the pane, not a screen stack:

Each pane declares its own chain, because they are not the same length:
Sessions and Memory are `("groups", "rows")` and open a `Reader` from the last
one; Skills — and the Tools tab that replaces it in sub-project C — is
`("groups", "rows", "detail")`, with the detail as a real third panel.

```python
class Split(Container):
    LEVELS = ("groups", "rows")             # ids of the panels, in order

    def set_level(self, n):
        """Which panel is on screen when only one fits.

        A number on the pane and not a `push_screen` per level: the widgets
        stay mounted either way, so the cursor, the search text and the loaded
        rows survive a resize. Widen the terminal mid-drill-down and all three
        panels appear with everything where you left it — the screen stack
        would have had to unwind, and a resize that unwinds a stack is a resize
        that loses your place.
        """
```

In a wide window every panel is displayed and `level` only decides which one
holds the focus, so the wide behaviour is exactly what it is today.

`↵` past the last level is unchanged at both widths: it opens the `Reader`, the
full-screen document that already exists. Drilling down is about which of the
pane's own panels you can see; a transcript was never one of them.

`.narrow #detail { display: none }` goes away. That panel stops being something
hidden in a narrow window and becomes the pane's last level, which is the only
way its content was ever reachable there.

Rejected alternatives, and why:

- **`push_screen` per level.** `Esc` and the back stack come free, but the
  widget tree then differs by width. A resize part-way down leaves screens
  orphaned, and `Reader` already uses the stack — a memory opened from a
  drilled-down list would be three screens deep.
- **Recomposing the pane in `on_resize`.** Already tried and already removed:
  *"arrastrar la ventana se sentía como barro"* (`vault/wiki/sto-tui-textual.md`).
  `on_resize` sets a class and nothing else, and that stays true.

### Everything else stacks and scrolls

Home, Config and Help are independent cards. In a narrow window they stack
vertically inside a `VerticalScroll`, and the cards stop being `1fr`:

```css
.narrow .card { height: auto; min-height: 6; }
.narrow .card DataTable { height: auto; max-height: 14; }
```

`height: auto` is what makes the stack have a real height to scroll through;
without the `max-height` a table of 43 rows makes one card taller than three
screens and the stack stops being scannable.

The two numbers are a starting point to be tuned against a rendered screen, not
a result: `6` is about the smallest card that still shows a heading and three
rows, and `14` is about a screenful. They are in the stylesheet, which is where
a number like that is allowed to live.

### The ▼

A `Static` docked to the bottom of the scroll container, shown only while
`scroll_y < max_scroll_y`, clickable (scrolls one page down). It disappears at
the bottom, which is the whole point: it is the answer to "is this all there
is".

Only ▼, no ▲. The scrollbar already says there is something above; a second
indicator for a fact already on screen is noise.

---

## Focus and keyboard

The rule: **`Tab` walks panels, the tab bar is a place you can stand.**

No custom focus ring is written. `screen.focus_next()` already walks the DOM in
order and skips anything hidden, which is most of the behaviour. The work is
making the tab bar part of that walk and giving it an escape hatch upward.

| key | where | what |
|---|---|---|
| `Tab` / `Shift+Tab` | anywhere | next / previous panel of the current pane; wraps through the tab bar |
| `↑` | topmost panel, cursor already on row 0 | focus the tab bar |
| `↑` | the search box | focus the tab bar (it has no vertical cursor to consume) |
| `←` `→` `Tab` | tab bar focused | change tab |
| `↓` `↵` `Esc` | tab bar focused | back down into the pane |
| `1`–`6` | anywhere | that tab, directly |
| `↵` | a group row, narrow | drill in one level |
| `Esc` | a drilled-in level, narrow | back one level |

`#tabs` becomes focusable and is already the first node in the DOM, so `Tab`
from the last panel returns to it without any special case. Focused, it draws
differently — a bar that is taking your arrow keys and a bar that is not have
to look different, the same rule the cards already follow.

The `↑` escape hatch is conditional on the cursor being at row 0 so that
holding `↑` to get to the top of a list does not overshoot into the tab bar on
the same keypress. It costs one more press, and the alternative is a list you
cannot walk to the top of without leaving it.

---

## Sorting

One key, `s`, with the semantics of a header click: advance to the next
sortable column ascending; if that column is already the sort, reverse it.

```
s → title ▲ → s → title ▼ → s → prompts ▲ → … → s → unsorted
```

"Unsorted" is a real state in the cycle and it is the pane's own order — most
of these lists are newest-first, which is the order you want almost always.
Ending the cycle back where it started means `s` can never strand you.

Clicking a header does the same thing but jumps straight to that column
(`DataTable.HeaderSelected`).

**Which columns sort is declared, not guessed.** `Table.__init__` already takes
a spec of `(label, width)` pairs; it grows an optional third field:

```python
Table((t("col_when"),    10),           # no third field: not sortable
      (t("col_project"), 18, "text"),
      (t("col_prompts"),  7, "num"),
      ...)
```

`when` is deliberately left out. It renders `2 h`, `5 d`, `3 w` — sorting that
as text interleaves hours with weeks, and sorting it correctly means sorting by
`mtime`, which the pane already does by default. A column whose only correct
order is the default order does not need to be in the cycle.

The active column's header carries `▲`/`▼`, so the state is on screen and not
in the user's memory. The base label is kept alongside the spec; rewriting the
label in place would compound the arrow on every press.

---

## The marquee

The selected row scrolls its own cut-off text horizontally. Only the selected
row, and only while its table has the focus.

```python
class Table(DataTable):
    MARQUEE_TICK = 0.2      # seconds per column of travel
    MARQUEE_HOLD = 5        # ticks of stillness at each end
```

Mechanics:

1. `add_row` keeps the raw value of every cell that is a `str`. Cells built
   with `Content.from_markup` carry markup and cannot be sliced without
   breaking a tag, so they never animate — a real limit, stated rather than
   worked around.
2. On `RowHighlighted`, measure which of that row's kept strings are longer
   than their column's render width. **None over-long → no timer is started.**
   The common case costs nothing.
3. Otherwise: hold `MARQUEE_HOLD` ticks, then advance one column per tick with
   `update_cell_at`, hold again at the end, return to offset 0, repeat.
4. The timer is stopped on `RowHighlighted` (reset), on `Blur`, and on the pane
   being hidden. A table that is not being looked at never animates.

Tying it to focus is what keeps this from being a screen that is always moving:
at most one row, in one table, is ever in motion, and only the one the keys are
pointed at.

---

## Breakpoints

Three classes on the app, set in `on_resize`, which continues to do nothing
else:

| class | threshold | effect |
|---|---|---|
| `narrow` | width < 100 | one column; splits drill down |
| `tiny` | width < 56 | hide the wordmark (it is 51 wide) |
| `short` | height < 24 | hide the wordmark |

`.narrow #wordmark { display: none }` is removed. At 70 columns the wordmark
fits with 19 to spare, and the reason it was hidden was that everything below
it was being pushed off the screen — which is the bug this document is about,
not a property of the wordmark.

`short` exists because on a wide, short terminal the banner costs three of
maybe fifteen usable rows to say what the screen already says.

---

## `tui_widgets.py`

`tui_app.py` is 1336 lines and this adds sorting, a marquee, level state and a
scroll indicator. Roughly 250 lines of it are generic infrastructure that the
screens only consume:

- `Table` (widths, fitting, sorting, marquee), `Card`, `Search`, `Wordmark`
- `bar`, `spark`, `clip`, `esc`, `ago`
- `GROUNDS`, `theme_for`, `ACCENT_CSS`

Those move to `scripts/tui_widgets.py`. `tui_app.py` goes back to being the
screens and the app. This is not a refactor for its own sake: the marquee and
the sort cycle belong to the table, and a 1600-line file where the table's
behaviour is interleaved with six screens is where they would otherwise land.

The stylesheet stays one file. The layout living in exactly one place is the
reason the Textual flavour exists.

---

## Tests

`scripts/test_tui_app.py`, headless, at the sizes that break today.

**Rewritten.** `test_tab_walks_the_tab_bar_and_a_document_has_its_own_keys`
asserts the opposite of the new model (that `Tab` cycles tabs). It is rewritten,
not deleted: the reader's shadowed keys — the half of it that is still true —
stay, and the tab-walking half becomes the new model. The old assertion was
right for its design and the design changed; deleting it would lose the reader
half with it.

**New:**

| test | what fails without it |
|---|---|
| every card of the home is reachable at 70x30 | the measured bug: `USAGE` and `OVERALL` off-screen with no scroll |
| the session table exists at 70x30 and `↵` on a project reaches it | the Sessions tab being unusable narrow |
| `Esc` walks back up the levels and the cursor is where it was | drill-down that loses your place |
| `Tab` reaches every panel and the tab bar, and `1`–`6` still work | keyboard-only navigation, the point of item 7 |
| `↑` from row 0 focuses the tab bar; `↑` from row 3 does not | the escape hatch not eating ordinary list navigation |
| `s` sorts, reverses, and returns to the pane's own order | the cycle stranding you in a sort you cannot leave |
| `when` is not in the sort cycle | a column sorted into nonsense |
| no marquee timer when nothing is cut off, and none after `Blur` | a screen that animates forever in the background |
| the wordmark is present at 70x30, absent at 50x30 and at 120x20 | item 10, both directions |

The rendered-size tests read the compositor strips, the way the existing suite
already does.

---

## Out of scope

Named so they are not smuggled in: the Tools tab, global search and markdown
rendering are sub-project C. Export/import is D. The `R` binding for *forget*
stays uppercase — changing it is a keymap decision of its own and would need
its own test.
