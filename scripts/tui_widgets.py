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

from textual.containers import Container  # noqa: E402
from textual.content import Content  # noqa: E402
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

    def on_mount(self) -> None:
        for label, width in self.spec:
            self.add_column(label, width=width or 1)

    def on_resize(self) -> None:
        self.fit()

    def fit(self) -> None:
        cols = list(self.columns.values())
        if not cols or not self.size.width or self.spec[-1][1] is not None:
            return
        pad = self.cell_padding * 2
        fixed = sum(w for _, w in self.spec[:-1])
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
