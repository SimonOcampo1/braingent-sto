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


# `[x]` is a tag to Textual's markup parser and disappears; escaped, it is a
# checkbox again. Named here so no f-string has to carry a backslash.
BOX_ON, BOX_OFF = r"\[x]", r"\[ ]"

# The accent is a preference of the whole OS, stored as an SGR code; Textual
# wants a colour it can put in a stylesheet.
ACCENT_CSS = {"36": "#22d3ee", "32": "#4ade80", "35": "#c084fc",
              "34": "#60a5fa", "33": "#fbbf24", "31": "#f87171"}

# Three grounds, ours and not the library's. Textual ships a dozen themes and
# every one of them brings its own accent, which then fights the accent the OS
# already has a setting for — two places deciding one colour. These take the
# accent from `sto ui` and only decide how dark the room is.
GROUNDS = {
    "dark":  ("#12141a", "#171a21", "#1d212a", "#e6e8ee"),
    "light": ("#f4f5f7", "#ffffff", "#e9ebef", "#1b1e26"),
    "black": ("#000000", "#0a0a0a", "#141414", "#e6e8ee"),
}

def theme_for(ground, accent_code):
    """One theme per (ground, accent) pair, named after both.

    Named after both on purpose: Textual repaints when the *name* of the theme
    changes, so re-registering `sto-dark` with a new accent left the old
    colours on screen. A new name is a new theme, and the screen follows.
    """
    background, surface, panel, foreground = GROUNDS[ground]
    accent = ACCENT_CSS.get(accent_code, "#22d3ee")
    return Theme(name=f"sto-{ground}-{accent_code}", primary=accent,
                 secondary=accent, accent=accent, background=background,
                 surface=surface, panel=panel, foreground=foreground,
                 dark=ground != "light", success="#4ade80",
                 warning="#fbbf24", error="#f87171")


# ── small renderers ──

def bar(pct, width=24, warn=80):
    """A gauge with eighth-of-a-cell resolution.

    Rounded to whole cells, 4 % and 11 % drew the same picture — the opposite
    of what a gauge is for. The track is a dim block rather than `░`: a field
    of dots lets the terminal show through and reads as grain next to a border
    that is one clean line.
    """
    eighths = " ▏▎▍▌▋▊▉"
    exact = max(0.0, min(1.0, (pct or 0) / 100)) * width
    full = int(exact)
    tip = eighths[int((exact - full) * 8)].strip()
    colour = "$error" if (pct or 0) >= warn else "$accent"
    rest = max(0, width - full - len(tip))
    return f"[{colour}]{'█' * full}{tip}[/][$foreground 20%]{'█' * rest}[/]"


def spark(values, width=24):
    """A sparkline of the last `width` values, one column each.

    Eight heights of block, scaled to the biggest value in the window — an
    absolute scale would flatten an ordinary week against one heavy day.
    """
    if not values:
        return ""
    tail = values[-width:]
    top = max(tail) or 1
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(blocks[min(7, int(v / top * 7.99))] for v in tail)


def ago(ts):
    return ui.ago(ts)


def _plain(cell):
    """The characters of a cell, whether it is a string or a `Content`."""
    return cell if isinstance(cell, str) else cell.plain


def clip(text, n):
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def esc(text):
    """Textual markup uses square brackets, and a transcript is full of them.

    Only `[` is escaped. Doubling backslashes as well — the Rich habit — put
    every Windows path in a transcript on screen as `C:\\Users\\...`.
    """
    return str(text).replace("[", "\\[")


class Table(DataTable):
    """A `DataTable` that states its own column widths and keeps the last one
    filling whatever is left.

    Left to itself a `DataTable` sizes a column from its header label and never
    shrinks it, so a description column pushes the table wider than the card it
    sits in until the left-hand columns walk off the edge — and the width is
    not known at mount, only once the layout has run. Both problems belong to
    the table, not to six screens repeating the fix.
    """

    def __init__(self, *spec, **kw):
        kw.setdefault("cursor_type", "row")
        super().__init__(**kw)
        self.spec = spec
        # a third field says how a column sorts, and its absence says it does
        # not. Declared and not guessed -- and `data` is the important one:
        # `when` renders `2 h` and `5 d`, which sorted as text interleaves
        # hours with weeks, and `errors` renders markup that is neither a
        # number nor comparable text. Those columns sort the row behind the
        # cell, which the pane holds and the table never sees.
        self.sortable = [i for i, col in enumerate(spec) if len(col) > 2]
        self.sort_by = None
        self._labels = [col[0] for col in spec]
        # what `add_row` was given, before the column cut it. A `Content` is
        # kept as a `Content`: it slices and carries its spans across, so a
        # coloured cell scrolls with its colours instead of being left out
        self.raw = {}
        self._marquee = None

    def on_mount(self) -> None:
        for col in self.spec:
            self.add_column(col[0], width=col[1] or 1)

    def on_resize(self) -> None:
        self.fit()
        # a wider column can un-cut the row that was scrolling, and a narrower
        # one can cut the row that was not
        self.marquee_later()

    def add_row(self, *cells, **kw):
        row = super().add_row(*cells, **kw)
        for col, value in enumerate(cells):
            if isinstance(value, (str, Content)):
                self.raw[(self.row_count - 1, col)] = value
        return row

    def clear(self, *args, **kw):
        self.raw.clear()
        self.marquee_reset()
        return super().clear(*args, **kw)

    # ── the marquee: the selected row shows what its column cut off ──

    MARQUEE_TICK = 0.2      # seconds per column of travel
    MARQUEE_HOLD = 5        # ticks of stillness at each end

    def marquee_reset(self) -> None:
        if self._marquee is not None:
            self._marquee[0].stop()
            self._marquee = None

    def marquee_start(self) -> None:
        """Scroll whatever this row's columns cut off, and nothing else.

        Tied to the focus on purpose: at most one row, in one table, is ever
        moving, and it is the one the keys are pointed at. A table nobody is
        looking at holds no timer at all.
        """
        self.marquee_reset()
        if not self.has_focus or not self.is_mounted:
            return
        row = self.cursor_row
        widths = [c.get_render_width(self) for c in self.columns.values()]
        over = {col: text for (r, col), text in self.raw.items()
                if r == row and col < len(widths)
                and len(_plain(text)) > widths[col]}
        if not over:
            return                        # the common case costs nothing
        # the negative start is the pause before it moves: a row that slides
        # the instant the cursor lands is unreadable while you are still
        # finding it
        self._marquee = (self.set_interval(self.MARQUEE_TICK, self._marquee_tick),
                         row, over, widths, [-self.MARQUEE_HOLD])

    def _marquee_tick(self) -> None:
        if self._marquee is None:
            return
        _, row, over, widths, state = self._marquee
        state[0] += 1
        longest = max(len(_plain(v)) - widths[c] for c, v in over.items())
        if state[0] > longest + self.MARQUEE_HOLD:
            state[0] = -self.MARQUEE_HOLD
        offset = max(0, min(state[0], longest))
        for col, text in over.items():
            self.update_cell_at(Coordinate(row, col), text[offset:])

    def marquee_later(self) -> None:
        """Measure after the layout, not before it.

        `get_render_width` is nothing but a guess until the columns have been
        fitted, and taking the focus is one of the moments that happens on the
        same frame — measured then, every column looks zero wide and nothing is
        ever found to be cut off.
        """
        self.marquee_reset()
        self.call_after_refresh(self.marquee_start)

    def on_data_table_row_highlighted(self, event) -> None:
        self.marquee_start()

    def on_focus(self) -> None:
        self.marquee_later()

    def on_show(self) -> None:
        self.marquee_later()

    def on_blur(self) -> None:
        self.marquee_reset()

    def on_hide(self) -> None:
        self.marquee_reset()

    # ── the sort cycle ──

    SORT_KEYS = {"num": lambda v: float(str(v).strip() or 0),
                 "text": lambda v: str(v).lower()}

    def _key(self, kind):
        """A sort key that survives the cells it is given.

        A numeric column can hold `·` for "none" and a text one can hold a
        `Content`; either raises inside `sorted` and takes the whole table with
        it. Anything unparseable sorts as if it were empty, which puts it at
        one end instead of crashing.
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
            self.sort_by = (self.sort_by[0], True)      # same column, reversed
        else:
            nxt = self.sortable.index(self.sort_by[0]) + 1
            self.sort_by = ((self.sortable[nxt], False)
                            if nxt < len(self.sortable) else None)
        self.apply_sort()

    def apply_sort(self) -> None:
        """Sort the rows, and put the arrow on the header that did it."""
        for i, col in enumerate(self.columns.values()):
            # rebuilt from the kept label, never appended to the live one, or
            # the arrow compounds one per press
            label = self._labels[i]
            if self.sort_by and self.sort_by[0] == i:
                arrow = " ▼" if self.sort_by[1] else " ▲"
                # the label gives up room for it rather than the column growing
                # or the arrow being cut: a header that fills its width exactly
                # ("prompts" in seven) swallowed the one mark that says this is
                # the column doing the sorting
                room = (self.spec[i][1] or col.width) - len(arrow)
                label = label[:max(1, room)].rstrip() + arrow
            col.label = Content(label)
        # `Column.label` is a plain dataclass field: assigning it changes
        # nothing on screen by itself
        self.refresh()
        owner = self._owner()
        if owner is not None and hasattr(owner, "sort_rows"):
            # the pane holds the rows the cells were rendered from, so it can
            # sort by a timestamp while the cell says "5 d". A table that has
            # no pane behind it -- the kinds rail, the preferences -- falls
            # through and sorts what it can see.
            return owner.sort_rows(self.sort_by)
        if self.sort_by is None:
            return self.refill()
        index, reverse = self.sort_by
        self.sort(list(self.columns.keys())[index],
                  key=self._key(self.spec[index][2]), reverse=reverse)

    def _owner(self):
        """The pane this table belongs to, if it sorts its own rows."""
        for node in self.ancestors_with_self:
            if node is not self and hasattr(node, "sort_rows"):
                return node
        return None

    def refill(self) -> None:
        """Back to the order the pane wrote the rows in.

        There is no key that means "the order they arrived": `DataTable.sort`
        only ever sees cell values, never the row key, so arrival order is not
        reachable from inside a sort. The pane does know it — it is the order
        `refresh_data` writes — so unsorting is asking it to write them again.
        That is cheap: the session list is behind an mtime-keyed cache.
        """
        for node in self.ancestors_with_self:
            if node is not self and hasattr(node, "refresh_data"):
                return node.refresh_data()

    def on_data_table_header_selected(self, event) -> None:
        event.stop()
        self.cycle_sort(event.column_index)

    def action_cursor_up(self) -> None:
        """At the top of the list, `↑` leaves it for the tab bar.

        Only at the top: holding `↑` to reach the first row has to reach the
        first row, and a hatch that opens one press early is a hatch you fall
        through every time you use the list normally.
        """
        if self.cursor_row <= 0:
            return self.app.focus_tabs()
        super().action_cursor_up()

    def fit(self) -> None:
        cols = list(self.columns.values())
        if not cols or not self.size.width or self.spec[-1][1] is not None:
            return
        pad = self.cell_padding * 2
        fixed = sum(col[1] for col in self.spec[:-1])
        want = max(8, self.size.width - fixed - pad * len(cols) - 1)
        if cols[-1].width != want:
            cols[-1].width = want
            self.refresh(layout=True)


class Card(Container):
    """A titled panel. Every one of them is this widget, so they cannot drift
    apart in border, padding or title style."""

    def __init__(self, title, *children, upper=True, classes="", **kw):
        # merged, not overwritten: a caller asking for one more class was
        # handing Textual two `classes=` and getting a TypeError
        super().__init__(*children, classes=f"card {classes}".strip(), **kw)
        # section headings are shouted the way the prototype shouts them; a
        # document's own title is not a heading and keeps its capitals
        self.border_title = str(title).upper() if upper else str(title)


class Search(Input):
    """The search box, on screen all the time and not summoned by a key.

    `/` used to open it at the foot. A box you cannot see is a feature nobody
    finds, and one docked under the rows it filters is one you cannot watch
    them narrow into. It sits on top of its own list, with its own label.
    """

    # a one-line box has no vertical cursor for `↑` to consume, so unlike a
    # table there is no top to reach first
    BINDINGS = [Binding("up", "to_tabs", "", show=False)]

    def action_to_tabs(self) -> None:
        self.app.focus_tabs()

    def __init__(self, **kw):
        # the label is the border title, not a placeholder: with both, the word
        # "search" sat on the box twice
        super().__init__(**kw)
        self.border_title = t("k_search")


# ── the wordmark ──
#
# figlet's `double_blocky`: solid `█▀▄` at two rows a line, so the whole name
# fits on one line, in two rows and fifty-one columns. The face of the
# prototype is `ansi_shadow`, and the same name in it is 103 columns and six
# rows — most of the screen spent saying what the screen already is.
#
# Pasted rather than generated: it is two strings, and a dependency to produce
# two strings is a dependency to keep working forever. To change the face:
#     uv run --no-project --with pyfiglet python -c
#       "import pyfiglet; print(pyfiglet.Figlet(font='double_blocky').renderText('BRAINGENT STO'))"
WORDMARK = [
    "██▄ █▀█ ▄▀█ ▀█▀ █▄░█ █▀▀ █▀▀ █▄░█ ▀█▀  ▄▀▀ ▀█▀ █▀█",
    "█▄█ █▀▄ █▀█ ▄█▄ █░▀█ █▄█ ██▄ █░▀█ ░█░  ▄██ ░█░ █▄█",
]
WORDMARK_W = max(len(line) for line in WORDMARK)


class Wordmark(Static):
    def on_mount(self) -> None:
        self.repaint()

    def repaint(self) -> None:
        self.update(Content.from_markup(
            "\n".join(f"[$accent]{line}[/]" for line in WORDMARK)))
