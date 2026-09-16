"""braingent STO — the optional Textual flavour of the TUI.

`sto ui` is the one that always runs: Python stdlib, no dependencies, on any
machine. This is the flavour you pick, and it is allowed to want a library.

It imports `cli` and `sessions_server` **directly**, with no HTTP in between.
There is no HTTP in between and no second copy of any rule: what "to push"
counts, which side of a parity a skill falls on and how a reset time is worded
are decided once, in Python, and this file only decides how they look.

Every user-facing string comes from `i18n`. Nothing here is written in Spanish
or in English.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # scripts/ is not a package

import cli  # noqa: E402
import i18n  # noqa: E402
import sessions_server as srv  # noqa: E402
import ui_data as ui  # noqa: E402

from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Container, VerticalScroll  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.screen import ModalScreen, Screen  # noqa: E402
from textual.widgets import Footer, Input, Markdown, Static  # noqa: E402

from tui_widgets import (  # noqa: E402
    GROUNDS, WORDMARK_BIG_W, WORDMARK_W, Card, Search, Table, Wordmark,
    ago, chip, clip, esc, gauge, pill, spark, theme_for)

t = i18n.t

TABS = ["tab_home", "tab_sessions", "tab_memory", "tab_tools",
        "tab_config", "tab_help"]
HOME, SESSIONS, MEMORY, TOOLS, CONFIG, HELP = range(6)


# ── a transcript, as a conversation ──

CODE = re.compile(r"`([^`]+)`")
PATHY = re.compile(r"(?<![\w/\\.])((?:[A-Za-z]:)?[\w./\\-]+\.[A-Za-z]{1,5}"
                   r"(?::\d+)?)(?![\w.])")


def _inline(text):
    """Backticks and file paths, coloured. Not a syntax highlighter.

    A transcript is prose with code in it, and the two things worth telling
    apart at a glance are "this is a literal" and "this is a file". Anything
    more would be guessing at a language per line.
    """
    out = esc(text)
    out = CODE.sub(lambda m: f"[$accent on $panel]{m.group(1)}[/]", out)
    return PATHY.sub(lambda m: f"[$secondary]{m.group(1)}[/]", out)


def transcript(row):
    """One session as the conversation it was: a list of `(css class, markup)`.

    Blocks and not one long string because a wrapped line has to keep the
    indent of the turn it belongs to — a paragraph that starts under `USER` and
    continues out at the margin stops reading as one person talking. Textual
    wraps inside a widget, so a turn has to *be* a widget.

    `cli.timeline_lines` paints the same thing in ANSI for the terminal TUI;
    this reads the structured timeline instead, because the shape — who spoke,
    what they ran, what broke — is exactly what a string flattens away.
    """
    detail = srv.session_timeline(Path(row["path"]))
    out = [("meta", f"{esc(row['project'])} \u00b7 {esc(row['id'])}")]
    for item in detail["timeline"]:
        kind = item["role"]
        if kind in ("user", "assistant"):
            who, css = ("USER", "user") if kind == "user" else ("CLAUDE", "claude")
            out.append((f"who {css}", who))
            fenced, buf = False, []
            for line in item["text"].splitlines():
                if line.lstrip().startswith("```"):
                    if fenced and buf:
                        out.append(("code", "\n".join(esc(x) for x in buf)))
                        buf = []
                    fenced = not fenced
                elif fenced:
                    buf.append(line)
                else:
                    out.append((css, _inline(line)))
            if buf:
                out.append(("code", "\n".join(esc(x) for x in buf)))
        elif kind == "tool":
            # `\u203a` and not a gear: the amber, the indent and the class
            # already say this is a tool call, and a pictograph says it a
            # second time in a font the terminal may not even have
            out.append(("tool", f"[$warning]\u203a {esc(item['tool'])}[/]"
                                f"  {esc(clip(item.get('detail', ''), 120))}"))
        elif kind == "image":
            # the string already reads "image"; a glyph in front of a word that
            # says the same thing is decoration
            out.append(("tool", esc(t("cli_image"))))
        elif kind == "error":
            out.append(("bad", f"\u00d7 {esc(clip(item['text'], 400))}"))
    return out


# ── the confirmation, used by everything that writes ──

class Confirm(ModalScreen[bool]):
    """Nothing that writes runs before this screen says what it will write.

    One modal for every verb — push, pull, update, and bringing or dropping a
    skill — because they are the same question, and five differently worded
    boxes for it is five chances to phrase the dangerous one gently.
    """
    BINDINGS = [
        Binding("y,enter", "yes", ""),
        Binding("escape,n,q", "no", ""),
    ]

    def __init__(self, title, lines, danger=False):
        super().__init__()
        self._title, self._lines, self._danger = title, lines, danger

    def compose(self) -> ComposeResult:
        with Container(id="confirm-wrap"):
            with Card(self._title, upper=False,
                      classes="danger" if self._danger else ""):
                with VerticalScroll():
                    yield Static(Content.from_markup(
                        "\n".join(self._lines) or t("nothing")), id="confirm-body")
                yield Static(Content.from_markup(
                    f"[$accent b] y [/] {t('confirm_go')}"
                    f"[$foreground 50%]     esc {t('confirm_no')}[/]"), id="confirm-keys")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class PathPrompt(ModalScreen[str]):
    """Where a project lives on this machine. One line of text, per machine.

    A modal and not a cell you type into: the answer is an absolute path, it is
    the same shape on every row of the table, and the other machines' answers
    have to be on screen while you write yours — that is how you recognise the
    project you are naming.
    """
    BINDINGS = [
        Binding("escape", "cancel", ""),
        Binding("enter", "submit", ""),
    ]

    def __init__(self, project, current, others):
        super().__init__()
        self._project, self._current = project, current or ""
        self._others = {m: p for m, p in (others or {}).items()
                        if m != srv.LOCAL_MACHINE}
        self._answered = False

    def compose(self) -> ComposeResult:
        lines = [f"[$foreground 60%]"
                 f"{esc(t('path_what', project=self._project))}[/]"]
        if self._others:
            lines += ["", f"[$foreground 50%]{t('path_others')}[/]"]
            lines += [f"[$accent]{esc(m):<18}[/][$foreground 70%]{esc(path)}[/]"
                      for m, path in sorted(self._others.items())]
        with Container(id="confirm-wrap"):
            with Card(f"{t('path_title')} \u00b7 {self._project}", upper=False):
                yield Static(Content.from_markup("\n".join(lines)), id="confirm-body")
                yield Input(value=self._current, placeholder=t("path_placeholder"),
                            id="path-input")
                yield Static(Content.from_markup(
                    f"[$accent b] \u21b5 [/] {t('confirm_go')}"
                    f"[$foreground 50%]     esc {t('confirm_no')}[/]"), id="confirm-keys")

    def on_mount(self) -> None:
        self.query_one("#path-input", Input).focus()

    def _answer(self, value) -> None:
        # the key reaches the Input and the screen binding both, depending on
        # which of the two Textual hands it to first; either way it is answered
        # once
        if self._answered:
            return
        self._answered = True
        self.dismiss(value)

    def on_input_submitted(self, event) -> None:
        self._answer(event.value.strip())

    def action_submit(self) -> None:
        self._answer(self.query_one("#path-input", Input).value.strip())

    def action_cancel(self) -> None:
        self._answer(None)


def manifest(data):
    """What a push or a pull would move, by kind, in the order it matters.

    The same numbers the home shows, spelled out: the count on the key cap
    answers "how much" and this answers "of what", which is the question you
    actually have with a finger over the key.
    """
    out = []
    if data["skills"]:
        shown = ", ".join(data["skills"][:8])
        rest = len(data["skills"]) - min(8, len(data["skills"]))
        out.append(f"[$accent]{'skills':<12}[/]{len(data['skills']):>4}   "
                   f"[$foreground 60%]{shown}{f'  …+{rest}' if rest else ''}[/]")
    memories = max(sum(data["memories"].values()), data.get("pending_memories", 0))
    if memories:
        detail = " · ".join(f"{p} ({n})" for p, n in sorted(data["memories"].items()))
        out.append(f"[$accent]{'memories':<12}[/]{memories:>4}   "
                   f"[$foreground 60%]{clip(detail, 90)}[/]")
    if data["config"]:
        out.append(f"[$accent]{'config':<12}[/]{len(data['config']):>4}   "
                   f"[$foreground 60%]{', '.join(data['config'])}[/]")
    if data["sessions"]:
        out.append(f"[$accent]{'sessions':<12}[/]{data['sessions']:>4}")
    if data["vault"]:
        out.append(f"[$accent]{'vault':<12}[/]{data['vault']:>4}")
    if data.get("activate"):
        out.append(f"[$accent]{t('n_activate'):<12}[/]{data['activate']:>4}   "
                   f"[$foreground 60%]{t('activate_hint')}[/]")
    return out or [f"[$foreground 60%]{t('nothing_to_sync')}[/]"]


# ── a document ──

class Reader(Screen):
    """One document, scrolled. `Esc` goes back.

    A screen and not a panel: a transcript is hundreds of lines and squeezing
    it beside the list it came from gives two things too narrow to read. It
    carries the same top bar and the same footer as everything else — a screen
    you can reach and then cannot tell where you are is worse than no screen.
    """
    BINDINGS = [
        Binding("escape", "app.pop_screen", "back"),
        Binding("up", "scroll(-1)", "", show=False),
        Binding("down", "scroll(1)", "", show=False),
        Binding("pageup", "scroll(-20)", "↑↓ PgUp PgDn"),
        Binding("pagedown", "scroll(20)", "", show=False),
        Binding("home", "top", "", show=False),
        Binding("end", "bottom", "", show=False),
        Binding("q", "app.quit", "quit"),
        # a screen binding shadows the app's. Reading a transcript with PUSH
        # one keystroke away is an accident waiting to happen, and hidden they
        # also stop being offered in the footer of a screen that cannot use them
        *[Binding(k, "nothing", "", show=False) for k in "plfgrusew"],
        # Tab belongs to this screen's own two panels -- the document and the
        # neighbours -- not to the panes of the screen underneath it
        Binding("tab", "next_panel", "", show=False, priority=True),
        Binding("shift+tab", "prev_panel", "", show=False, priority=True),
    ]

    def action_next_panel(self) -> None:
        self.focus_next()

    def action_prev_panel(self) -> None:
        self.focus_previous()

    def __init__(self, title, body, links=(), markdown=False):
        super().__init__()
        self._title = title
        # a string is one plain block; a list is `(css class, markup)` turns
        self._blocks = body if isinstance(body, list) else [("plain", body)]
        self._links = list(links)
        # a memory and a SKILL.md are documents and `**bold**` on screen as
        # four asterisks is this screen failing at its one job. A transcript is
        # not a document -- it is a conversation, and its own renderer carries
        # more than markdown can -- so the flag is per caller, not per screen
        self._markdown = markdown and isinstance(body, str)

    def compose(self) -> ComposeResult:
        with Container(id="chrome"):
            yield Static(self.app.topbar_content(), id="topbar")
        with Container(id="reader"):
            with Card(self._title, upper=False):
                with VerticalScroll(id="doc-scroll"):
                    if self._markdown:
                        # `Markdown.can_focus` is False, so the scroll around
                        # it stays what takes the keys and the reader's
                        # ↑↓/PgUp/PgDn bindings are untouched
                        yield Markdown(self._blocks[0][1])
                    else:
                        for css, text in self._blocks:
                            yield Static(text if css == "plain"
                                         else Content.from_markup(text),
                                         markup=False, classes=f"blk {css}")
            if self._links:
                yield Card(t("mem_links"),
                           Table((t("col_slug"), None), id="t-links"), id="links")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        # the scroll container has to hold focus or the arrows go nowhere: the
        # keys are bound to the screen, and the screen is not what scrolls
        self.query_one("#doc-scroll", VerticalScroll).focus()
        if self._links:
            table = self.query_one("#t-links", Table)
            for arrow, mid in self._links:
                table.add_row(Content.from_markup(f"[$accent]{arrow}[/] {mid}"))

    def action_nothing(self) -> None:
        pass

    @property
    def doc(self):
        return self.query_one("#doc-scroll", VerticalScroll)

    def action_scroll(self, lines: int) -> None:
        self.doc.scroll_relative(y=lines, animate=False)

    def action_top(self) -> None:
        self.doc.scroll_home(animate=False)

    def action_bottom(self) -> None:
        self.doc.scroll_end(animate=False)

    def on_data_table_row_selected(self, event) -> None:
        """A neighbour opens the memory it names, in place of this one."""
        _, mid = self._links[event.cursor_row]
        project, _, slug = mid.rpartition("/")
        self.app.pop_screen()
        self.app.open_memory(project, slug)


# ── the panes ──

class Levels:
    """Panels that are a hierarchy: in one column, one of them at a time.

    Sessions, memories and skills ask the same shape of question — pick the
    group, then the item, then read it — and the only thing that differs is how
    deep it goes. `LEVELS` says that, and the rest is the same for all three,
    so it is written once here instead of three times below.
    """

    # the panels, outermost first, by widget id
    LEVELS = ()

    def ask(self, title, lines, danger, run) -> None:
        def answered(yes):
            if yes:
                run()
                self.app.action_reload()
        self.app.push_screen(Confirm(title, lines, danger), answered)

    # which key of a row each column of the row table is rendered from. `None`
    # means the column is not sortable and never enters the cycle.
    SORT_FIELDS = ()

    def sort_rows(self, sort_by) -> None:
        """`s` on the row table. The pane sorts the rows, not the cells.

        A cell is a rendering -- `5 d`, a coloured count, a clipped title --
        and sorting renderings gives the wrong answer for exactly the columns
        somebody wants sorted. `None` is the pane's own order, which `fill()`
        restores by rebuilding from the source.
        """
        self.order = sort_by
        self.fill()

    def ordered(self, pool):
        """`pool`, in whatever order `s` last asked for."""
        order = getattr(self, "order", None)
        if not order or not self.SORT_FIELDS:
            return pool
        column, reverse = order
        field = self.SORT_FIELDS[column] if column < len(self.SORT_FIELDS) else None
        if not field:
            return pool

        def key(row):
            value = row.get(field)
            # one list, mixed types: a missing count and a missing title have
            # to sort somewhere rather than raise
            if isinstance(value, (int, float)):
                return (0, value, "")
            return (1, 0, str(value or "").lower())

        return sorted(pool, key=key, reverse=reverse)

    # A hierarchy shows one level at a time at every width. Sessions and
    # memories are folders: you pick the project, *then* you look at what is
    # inside it. Showing both columns at once meant the project list was a
    # 14-column rail nobody could read a name in, and the row list was showing
    # 500 sessions from every project before you had chosen one.
    ALWAYS_DRILL = False

    @property
    def stacked(self) -> bool:
        return self.ALWAYS_DRILL or self.app.has_class("narrow")

    def set_level(self, n) -> None:
        """Which panel is on screen when only one fits.

        A number on the pane and not a `push_screen` per level: the widgets
        stay mounted either way, so the cursor, the search text and the loaded
        rows survive both a drill-down and a resize. Widen the terminal in the
        middle of one and every panel appears with everything where you left
        it — a screen stack would have had to unwind, and a resize that unwinds
        a stack is a resize that loses your place.
        """
        self.level = max(0, min(n, len(self.LEVELS) - 1))
        narrow = self.stacked
        for i, name in enumerate(self.LEVELS):
            self.query_one(f"#{name}").display = not narrow or i == self.level
        # the search box belongs to the outermost level: it filters the list
        # you are about to pick from, and over a document it is a box that does
        # nothing
        self.query_one("#search", Search).display = not narrow or self.level == 0
        if narrow:
            # the first thing in the panel that can take keys, whatever it is:
            # a list is a table and a document is a scroll, and a level nobody
            # can focus is a level where no key does anything
            panel = self.query_one(f"#{self.LEVELS[self.level]}")
            target = next((w for w in panel.walk_children() if w.focusable), None)
            if target is not None:
                # after the refresh, not now: the panel was hidden a line ago
                # and the focus chain is built from what the layout says is on
                # screen, so focusing it in the same breath is asking for a
                # widget that does not exist yet and getting silence
                self.app.call_after_refresh(target.focus)
        self.app._more_check()

    def back(self) -> bool:
        """`Esc`. True if it moved, so the app knows the key was used."""
        if self.stacked and self.level > 0:
            self.set_level(self.level - 1)
            return True
        return False

    def drill(self) -> bool:
        """`↵` going one panel deeper. True if it moved.

        Only in one column: in a wide window every panel is already on screen
        and `↵` means what it has always meant.
        """
        if self.stacked and self.level < len(self.LEVELS) - 1:
            self.set_level(self.level + 1)
            return True
        return False


class Split(Levels, Container):
    """A screen made of a search box, a list of groups and a list of rows.

    Sessions and memories are the same shape because they answer the same kind
    of question: pick the project, then read what it holds. Both lists are
    `Table`s and not a `ListView` on one side — two widgets meant the two sides
    highlighted, hovered and took focus differently, on one screen.
    """
    GROUP_W = 30
    # two panels: the third thing you look at is a whole document and it has
    # its own screen
    LEVELS = ("groups", "rows")
    ALWAYS_DRILL = True
    # the two primary verbs, drawn on the row itself. Off by default: a button
    # that does nothing is worse than no button
    ROW_BUTTONS = False

    def compose(self) -> ComposeResult:
        yield Search(id="search")
        cols = [(t("col_project"), 30, "text"), (t("col_total"), 6, "num"),
                (t("col_machine"), None, "text")]
        if self.ROW_BUTTONS:
            # wide enough for the word inside the chip: a button with no label
            # is a glyph, and a glyph is not something anybody tries to click
            cols = [("", 11), ("", 8)] + cols
        yield Card(t("sec_projects"), Table(*cols, id="t-groups"), id="groups")
        yield Card(self.TITLE, self.make_table(), id="rows")

    def on_mount(self) -> None:
        self.q = ""          # the search text; `self.query` is the DOM query
        self.index = 0
        self.rows = []
        self.level = 0
        self._wire_buttons()
        self.refresh_data()
        # focus starts on the left: you pick the project first, and the
        # right-hand list is what you move to once you have
        self.set_level(0)
        self.query_one("#t-groups", Table).focus()

    def set_groups(self, pairs, total) -> None:
        """The projects, how much each holds, and which machines wrote it.

        The third column is the answer to "who has been working on this" --
        one machine today, and more than one the moment a second machine syncs
        into the same repo. Reading it off the rows rather than off a config
        means it is true by construction.
        """
        table = self.query_one("#t-groups", Table)
        keep = table.cursor_row
        table.clear()
        self.group_names = [p[0] for p in pairs]
        every = sorted({m for p in pairs for m in p[2]})
        pad = [Content("")] * 2 if self.ROW_BUTTONS else []
        table.add_row(*pad, Content.from_markup(f"[$accent b]{t('show_all')}[/]"),
                      str(total), Content(" ".join(every)))
        known = srv.project_paths() if self.ROW_BUTTONS else {}
        for entry in pairs:
            name, n, machines = entry[:3]
            todo = entry[3] if len(entry) > 3 else 0
            buttons = [Content.from_markup(
                           chip(f"\u25b2 {t('btn_keep')}") if todo
                           else chip(f"\u25cf {t('btn_done')}", "off")),
                       Content.from_markup(
                           chip(f"\u2302 {t('btn_path')}", "quiet"
                                if known.get(name, {}).get(srv.LOCAL_MACHINE)
                                else "on"))] if self.ROW_BUTTONS else []
            table.add_row(*buttons, clip(name, 30), str(n),
                          Content.from_markup(
                              " ".join(f"[$accent]{m}[/]" if m == srv.LOCAL_MACHINE
                                       else f"[$foreground 60%]{m}[/]"
                                       for m in sorted(machines))))
        table.fit()
        if 0 < keep < table.row_count:
            table.move_cursor(row=keep)
        self.retitle()

    def retitle(self) -> None:
        """The second panel is named after the project you walked into.

        One panel at a time means the heading is the only thing left saying
        which project you are inside -- without it, drilling into a project and
        drilling into `all` look identical.
        """
        names = getattr(self, "group_names", [])
        name = names[self.index - 1] if 0 < self.index <= len(names) else None
        self.query_one("#rows", Card).border_title = (
            f" {self.TITLE} · {name} " if name else f" {self.TITLE} ").upper()

    def on_data_table_row_highlighted(self, event) -> None:
        if event.data_table.id == "t-groups":
            self.index = event.cursor_row
            self.fill()
            self.retitle()
        else:
            self.preview(event.cursor_row)

    def on_data_table_row_selected(self, event) -> None:
        self.open()

    def open(self) -> None:
        """`↵` on whichever of the two lists has focus.

        The app binds `enter` with priority — it has to, or the tables eat it
        and the other screens lose their opener — so the routing has to happen
        here rather than in a per-table handler.
        """
        # a project is a folder, and in one column a folder opens into the
        # panel that holds its contents
        if self.drill():
            return
        if self.query_one("#t-groups", Table).has_focus:
            return self.query_one("#t-rows", Table).focus()
        self.open_row()

    def on_input_changed(self, event) -> None:
        self.q = event.value
        self.fill()

    def on_input_submitted(self, event) -> None:
        self.query_one("#t-rows", Table).focus()

    def preview(self, index) -> None:
        pass

    def _wire_buttons(self) -> None:
        """Both lists carry the same two buttons in the same two columns.

        The cursor moves to the row under the pointer before the verb runs: a
        button read through `cursor_row` would act on the row you clicked last
        time.
        """
        if not self.ROW_BUTTONS:
            return
        for name in ("t-groups", "t-rows"):
            table = self.query_one(f"#{name}", Table)
            table.buttons = 2
            table.button_handler = self._button_click

    def _button_click(self, table, row, column) -> None:
        # `move_cursor` sets the coordinate now and posts the highlight for
        # later, so `cursor_row` is already right and `self.index` -- which the
        # highlight handler writes -- still points at the project you were on.
        # The click says which row it was; nothing has to wait for a message.
        if table.id == "t-groups":
            self.index = row
            self.fill()
        self.act("row_sync" if column == 0 else "row_path")


class Sessions(Split):
    TITLE = t("tab_sessions")
    # the two primary verbs and nothing else on the footer. `k` and `a` still
    # work -- `act` answers to both names -- they are just not four key caps
    # for two things
    VERBS = ("row_sync", "row_path")
    ROW_BUTTONS = True
    # the two button columns never sort: they are the same glyph for every row
    # in the same state, so ordering by them orders by nothing
    SORT_FIELDS = (None, None, "mtime", "project", "n_prompts", "errors",
                   "machine", "title")

    def make_table(self):
        # every column sorts, including the two whose cell is not the datum:
        # `when` renders `5 d` and sorts by `mtime`, `errors` renders markup
        # and sorts by the count behind it.
        #
        # `tools` and `kept` are gone. The tool count never decided anything --
        # it is a number you read and forget -- and `kept` is what the first
        # button column already says, in the place where you can act on it.
        # the buttons are two-tuples: a column with a third element is one `s`
        # will stop on, and the same glyph for every row in a state sorts by
        # nothing
        return Table(("", 11), ("", 8),
                     (t("col_when"), 10, "data"), (t("col_project"), 18, "data"),
                     (t("col_prompts"), 7, "data"),
                     (t("col_errors"), 7, "data"), (t("col_machine"), 12, "data"),
                     (t("col_title"), None, "data"), id="t-rows")

    def refresh_data(self) -> None:
        rows, _ = cli.cached_sessions()
        # one directory walk for the whole table: asking per row would stat the
        # knowledge tree 500 times to paint one screen
        archived = {a["id"] for a in srv.archived_sessions()}
        for r in rows:
            r["kept"] = r["id"] in archived
        self.all_rows = rows
        groups = {}
        for r in rows:
            groups.setdefault(r["project"], []).append(r)
        self.groups = sorted(groups.items(), key=lambda kv: -kv[1][0]["mtime"])
        self.set_groups([(name, len(items),
                          {i.get("machine") or srv.LOCAL_MACHINE for i in items},
                          sum(1 for i in items if self._todo(i)))
                         for name, items in self.groups], len(rows))
        self.fill()

    @staticmethod
    def _todo(row):
        """Whether this conversation has somewhere to travel.

        Recorded here and never archived → it can be kept, so the other
        machines can resume it. Recorded elsewhere and archived → it can be
        brought down. Anything else is already where it belongs.
        """
        if not row.get("machine"):
            return None if row.get("kept") else "keep"
        return "bring" if row.get("kept") else None

    @staticmethod
    def _button(row):
        """The first column: what `e` would do to this row, spelled out.

        Three states and three labels, because a row whose button does nothing
        has to look different from one whose button writes to the repo. A word
        and not a triangle: a glyph is not something anybody tries to click.
        """
        todo = Sessions._todo(row)
        if todo == "keep":
            return chip(f"▲ {t('btn_keep')}")
        if todo == "bring":
            return chip(f"▼ {t('btn_bring')}")
        return chip(f"● {t('btn_done')}", "off")

    def _home(self, project):
        """The path button. Filled while this machine has not said where the
        project is, quiet once it has -- the same chip either way, because it
        opens the same prompt either way.

        Off `self._paths`, refreshed once per `fill()`: reading the registry
        per row is five hundred file reads to paint one screen.
        """
        known = (getattr(self, "_paths", None) or {}).get(
            project, {}).get(srv.LOCAL_MACHINE)
        return chip(f"⌂ {t('btn_path')}", "quiet" if known else "on")

    def fill(self) -> None:
        pool = (self.all_rows if self.index == 0 or self.index > len(self.groups)
                else self.groups[self.index - 1][1])
        if self.q:
            # the machine is searchable too: "which of my machines had this
            # session" is the question the column was added for
            q = self.q.lower()
            pool = [r for r in pool
                    if q in f"{r['project']} {r['title']} {r.get('machine') or ''}".lower()]
        pool = self.ordered(pool)
        self.rows = pool
        self._paths = srv.project_paths()
        table = self.query_one("#t-rows", Table)
        table.clear()
        for r in pool:
            table.add_row(Content.from_markup(self._button(r)),
                          Content.from_markup(self._home(r["project"])),
                          ago(r["mtime"]), clip(r["project"], 18), str(r["n_prompts"]),
                          Content.from_markup(f"[$error]{r['errors']}[/]"
                                              if r["errors"] else "0"),
                          # not clipped to the column width: the marquee needs
                          # something longer than the column to scroll
                          clip(r.get("machine") or srv.LOCAL_MACHINE, 60),
                          clip(r["title"], 200), key=r["id"])
        table.fit()
        if not pool:
            self.app.empty(table, t("cli_no_sessions") if not self.all_rows
                           else t("cli_no_hits", q=self.q))

    def open_row(self) -> None:
        table = self.query_one("#t-rows", Table)
        if not self.rows:
            return
        r = self.rows[table.cursor_row]
        self.app.push_screen(Reader(clip(r["title"], 60), transcript(r)))

    # ── the project the two buttons are pointed at ──

    def current_project(self):
        """Whichever list has the keys: the project you are standing on."""
        if self.query_one("#t-groups", Table).has_focus:
            if 0 < self.index <= len(self.groups):
                return self.groups[self.index - 1][0]
            return None               # "all" is not a project
        if self.rows:
            return self.rows[self.query_one("#t-rows", Table).cursor_row]["project"]
        return None

    def act(self, verb: str) -> None:
        """The two buttons on the row, and the two old key names behind them.

        `e` syncs what the row is asking for and `w` says where the project
        lives here. Which way `e` goes is never a guess: the machine column
        says where the conversation was recorded and the archive says whether
        it has travelled.
        """
        if verb == "row_path":
            return self.ask_path()
        if verb == "row_sync":
            if self.query_one("#t-groups", Table).has_focus:
                return self.sync_project()
            if not self.rows:
                return
            todo = self._todo(self.rows[self.query_one("#t-rows", Table).cursor_row])
            if todo is None:
                return self.app.notify(t("all_synced"))
            verb = todo
        table = self.query_one("#t-rows", Table)
        if not self.rows:
            return
        r = self.rows[table.cursor_row]
        sid, short = r["id"], r["id"][:8]
        if verb == "keep":
            if (r.get("machine") or srv.LOCAL_MACHINE) != srv.LOCAL_MACHINE:
                return self.app.notify(t("keep_only_local", id=short),
                                       severity="warning")
            if r.get("kept"):
                return self.app.notify(t("keep_already", id=short))
            self.ask(t("keep_title"),
                     [f"[$accent]{esc(clip(r['title'], 90))}[/]",
                      f"[$foreground 60%]{esc(t('keep_what'))}[/]",
                      f"[$foreground 60%]{esc(t('keep_how'))}[/]"],
                     False, lambda: self._keep(sid, short))
        elif verb == "bring":
            if not r.get("kept"):
                return self.app.notify(t("resume_needs_keep", id=short),
                                       severity="warning")
            out = (srv.CLAUDE_DIR / "projects" /
                   srv.project_slug(Path.cwd()) / f"{sid}.jsonl")
            self.ask(t("resume_title"),
                     [f"[$accent]{esc(clip(r['title'], 90))}[/]",
                      f"[$foreground 60%]{esc(t('resume_what', path=out))}[/]",
                      f"[$foreground 60%]{esc(t('resume_how', id=sid))}[/]"],
                     False, lambda: self._resume(sid, short))

    def _keep(self, sid, short) -> None:
        res = srv.keep_session(sid)
        self.app.done(res.get("error") or
                      t("kept_ok", id=short, kb=max(1, res["bytes"] // 1024)),
                      "error" in res)

    def _resume(self, sid, short) -> None:
        """Filed against the path this machine has for the project, and only
        against the current directory when nobody has said what that path is.

        `project_slug` is the absolute path with every non-alphanumeric
        character turned into a dash, so a transcript only resumes under the
        directory it was filed against. That is the whole reason the registry
        exists: the same repo is `/home/me/x` here and `D:\\Projects\\x` there,
        and a conversation brought down against the wrong one is a file
        `claude --resume` will never look at.
        """
        res = srv.resume_session(sid)
        self.app.done(res.get("error") or t("resumed_ok", short=short, id=sid),
                      "error" in res)

    # ── the two buttons ──

    def sync_project(self) -> None:
        """`e` on a project keeps every conversation of it that is not kept yet.

        Only the local ones: keeping reads a raw transcript out of
        `~/.claude/projects`, and a session another machine recorded is not
        there to read.
        """
        project = self.current_project()
        pool = (self.all_rows if project is None
                else [r for r in self.all_rows if r["project"] == project])
        todo = [r for r in pool if self._todo(r) == "keep"]
        name = project or t("show_all")
        if not todo:
            return self.app.notify(t("sync_project_none", project=name))
        lines = [f"[$foreground 60%]{esc(t('sync_project_what', n=len(todo), project=name))}[/]", ""]
        lines += [f"[$accent]{esc(clip(r['title'], 86))}[/]" for r in todo[:12]]
        if len(todo) > 12:
            lines.append(f"[$foreground 60%]\u2026+{len(todo) - 12}[/]")
        self.ask(t("sync_project_title"), lines, False,
                 lambda: self._keep_many([r["id"] for r in todo]))

    def _keep_many(self, ids) -> None:
        ok = sum(1 for sid in ids if "error" not in srv.keep_session(sid))
        self.app.done(t("sync_project_done", ok=ok, fail=len(ids) - ok),
                      ok < len(ids))

    def ask_path(self) -> None:
        """`w` — where this project lives on this machine.

        Per machine and stored in `knowledge/`, so it travels: every machine
        ends up knowing every path of a project, its own included, which is
        what lets a transcript recorded somewhere else land in the right
        checkout here.
        """
        project = self.current_project()
        if not project:
            return self.app.notify(t("path_none"))
        paths = srv.project_paths().get(project, {})

        def answered(value):
            if value is None:
                return
            srv.set_project_path(project, value)
            self.app.done(t("path_saved", project=project, path=value) if value
                          else t("path_cleared", project=project))
            self.refresh_data()

        self.app.push_screen(
            PathPrompt(project, paths.get(srv.LOCAL_MACHINE, ""), paths), answered)


class Memory(Split):
    TITLE = t("tab_memory")
    SORT_FIELDS = ("slug", "mtime", "machine", "description")

    def make_table(self):
        return Table((t("col_slug"), 28, "data"), (t("col_when"), 9, "data"),
                     (t("col_machine"), 14, "data"), (t("col_desc"), None, "data"),
                     id="t-rows")

    def refresh_data(self) -> None:
        self.projects = srv.list_memory()
        self.all_rows = [dict(m, project=p["project"])
                         for p in self.projects for m in p["memories"]]
        self.all_rows.sort(key=lambda m: -m["mtime"])
        self.set_groups([(p["project"], p["count"], set(p["machines"]))
                         for p in self.projects], len(self.all_rows))
        self.fill()

    def fill(self) -> None:
        pool = (self.all_rows if self.index == 0 or self.index > len(self.projects)
                else [dict(m, project=self.projects[self.index - 1]["project"])
                      for m in self.projects[self.index - 1]["memories"]])
        if self.q:
            q = self.q.lower()
            pool = [m for m in pool
                    if q in f"{m['project']} {m['slug']} {m['description']} "
                            f"{m['machine']}".lower()]
        pool = self.ordered(pool)
        self.rows = pool
        table = self.query_one("#t-rows", Table)
        table.clear()
        for m in pool:
            table.add_row(clip(m["slug"], 28), ago(m["mtime"]),
                          clip(m["machine"], 14), clip(m["description"], 200))
        table.fit()
        if not pool:
            self.app.empty(table, t("cli_no_memories") if not self.all_rows
                           else t("cli_no_hits", q=self.q))

    def open_row(self) -> None:
        table = self.query_one("#t-rows", Table)
        if not self.rows:
            return
        m = self.rows[table.cursor_row]
        self.app.open_memory(m["project"], m["slug"], m["machine"])


class Tools(Levels, Container):
    VERBS = ("bring", "delete", "forget")

    """Everything the agent runs with, on this machine and in the repo.

    It was the skills tab, which meant `settings.json` and `CLAUDE.md` — things
    push carries and the parity table counts — could be seen as a number and
    never as a file. The kinds are the keys of `CONFIG_MODULES` itself, so the
    tab cannot drift from what sync actually moves.

    Every row still carries the same four states, which is the point of the
    screen: the ones that are only on one side.
    """

    LEVELS = ("kinds", "rows", "detail")

    def compose(self) -> ComposeResult:
        yield Search(id="search")
        # one column, with the count in the text: two columns in a rail this
        # narrow leaves the number nowhere to go, and a header that repeats the
        # card's own title is a row pretending to be a heading
        yield Card(t("sec_kinds"),
                   Table(("", None), id="t-kinds", show_header=False),
                   id="kinds")
        yield Card(t("tab_tools"),
                   Table((t("col_name"), 34, "text"), (t("col_desc"), None, "text"),
                         id="t-rows"),
                   id="rows")
        # inside a `VerticalScroll` because a six-hundred-character description
        # in seventy columns is a document, and because a level you drill into
        # has to be able to take the focus -- a `Static` cannot
        yield Card(t("sec_detail"), VerticalScroll(Static(id="skill-detail")),
                   id="detail")

    def on_mount(self) -> None:
        self.q = ""
        self.rows = []
        self.level = 0
        self.refresh_data()
        self.set_level(0)
        self.query_one("#t-kinds", Table).focus()

    def refresh_data(self) -> None:
        """The kinds, which are the modules, and then the list of the one you
        are on. No query changes the kinds -- they are what sync carries."""
        table = self.query_one("#t-kinds", Table)
        keep = table.cursor_row
        table.clear()
        self.modules = list(srv.CONFIG_MODULES)
        for mod in self.modules:
            n = len(ui.module_items(mod))
            table.add_row(Content.from_markup(
                f"{mod}  [$foreground 50%]{n}[/]" if n else
                f"[$foreground 50%]{mod}  0[/]"))
        table.fit()
        if 0 < keep < table.row_count:
            table.move_cursor(row=keep)
        self.fill()

    def fill(self) -> None:
        index = self.query_one("#t-kinds", Table).cursor_row
        rows = ui.module_items(self.modules[max(0, min(index, len(self.modules) - 1))])
        if self.q:
            q = self.q.lower()
            rows = [r for r in rows if q in f"{r['label']} {r['desc']}".lower()]
        self.rows = rows
        table = self.query_one("#t-rows", Table)
        keep = table.cursor_row
        table.clear()
        for r in rows:
            mark, colour = {"local": (r"\[L]", "$warning"), "repo": (r"\[R]", "$success"),
                            "gone": (r"\[x]", "$error")}.get(r.get("where"),
                                                             (r"\[=]", "$foreground 40%"))
            table.add_row(Content.from_markup(f"[{colour}]{mark}[/] {clip(r['label'], 30)}"),
                          clip(r["desc"], 200))
        table.fit()
        if 0 <= keep < len(rows):
            table.move_cursor(row=keep)
        if not rows:
            self.app.empty(table, t("cli_no_hits", q=self.q) if self.q
                           else t("empty"))
        self.preview(min(keep, max(0, len(rows) - 1)))

    def on_input_changed(self, event) -> None:
        # only the rows: the kinds are the modules and no query changes those
        self.q = event.value
        self.fill()

    def on_input_submitted(self, event) -> None:
        self.query_one("#t-rows", Table).focus()

    def preview(self, index) -> None:
        detail = self.query_one("#skill-detail", Static)
        if not self.rows:
            return detail.update(Content.from_markup(f"[$foreground 60%]{t('empty')}[/]"))
        r = self.rows[max(0, min(index, len(self.rows) - 1))]
        state = {"local": "st_local", "repo": "st_repo",
                 "gone": "st_gone"}.get(r.get("where"), "st_both")
        detail.update(Content.from_markup(
            f"[$accent b]{esc(r['label'])}[/]\n"
            f"[$foreground 60%]{r['what']} · {t(state)}[/]\n\n"
            f"{esc(clip(r['desc'], 600))}"))

    def on_data_table_row_highlighted(self, event) -> None:
        if event.data_table.id == "t-kinds":
            self.fill()
        else:
            self.preview(event.cursor_row)

    def on_data_table_row_selected(self, event) -> None:
        self.open()

    def content(self, row):
        """What this row has to read, or `None` when it is not a document.

        A skill is its `SKILL.md`, a config row is the file itself, and a
        plugin is a manifest entry with nothing behind it — a real answer and
        not a failure, so it is said rather than raised. A skill the repo
        carries and this machine never installed has nothing here either.
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

    def open(self) -> None:
        if self.drill():
            return
        if not self.rows:
            return
        row = self.rows[self.query_one("#t-rows", Table).cursor_row]
        body = self.content(row)
        if body is None:
            return self.app.notify(t("empty"))
        # markdown only where the file is markdown: json inside a markdown
        # renderer is worse json, not better
        self.app.push_screen(Reader(
            row["label"], body,
            markdown=row["what"] == "skill" or row["label"].lower().endswith(".md")))

    # ── the three verbs of the module screen of the stdlib TUI ──
    #
    # `a` brings what the repo has, `d` removes it from this machine, `R` drops
    # it from the repo. There is no fourth for "push this one": `export_config`
    # carries everything local on the next push anyway.

    def act(self, verb) -> None:
        table = self.query_one("#t-rows", Table)
        if not self.rows:
            return
        row = self.rows[table.cursor_row]
        if row["what"] not in ("skill", "plugin"):
            return self.app.notify(t("not_deletable", id=row["what"]),
                                   severity="warning")
        name = row["label"] if row["what"] == "skill" else row["id"]
        target = f"{row['what']}:{name}"

        if verb == "delete":
            lines = [f"[$error b]{t('delete_title', what=row['what'])}[/]  {row['label']}",
                     f"[$foreground 60%]{t('delete_warning')}[/]"]
            return self.ask(t("k_delete"), lines, True, lambda: self._delete(row))

        # bring and forget both dry-run first: the manifest is the file list the
        # engine itself is about to touch, not a summary written here
        paths, err = (srv.bring(target) if verb == "bring" else srv.forget(target))
        if err:
            return self.app.notify(err, severity="error")
        lines = [f"[$accent]{esc(p)}[/]" for p in list(paths)[:14]]
        if len(paths) > 14:
            lines.append(f"[$foreground 60%]…+{len(paths) - 14}[/]")
        self.ask(t("k_bring") if verb == "bring" else t("k_forget"), lines,
                 verb == "forget", lambda: self._apply(verb, target, row["label"]))

    def _apply(self, verb, target, label) -> None:
        fn = srv.bring if verb == "bring" else srv.forget
        _, err = fn(target, apply=True)
        self.app.done(err or t("brought" if verb == "bring" else "forgotten", id=label),
                      bool(err))

    def _delete(self, row) -> None:
        if row["what"] == "skill":
            err = srv.delete_skill(row["id"])
        else:
            err = srv.plugin_cmd("uninstall", row["id"]).get("error")
        self.app.done(err or t("deleted", id=row["label"]), bool(err))


class Home(Container):
    """The dashboard, and one box to search everything from."""

    def compose(self) -> ComposeResult:
        yield Wordmark(id="wordmark")
        # a wrapper whose only job is to centre one child. Textual's `align`
        # places the *group* of children, so a screen holding one narrow widget
        # and one full-width one centres nothing: the group is already as wide
        # as the screen. One box per thing to centre is what actually centres.
        with Container(id="search-wrap"):
            # the box says what it searches, inside itself: on this screen it
            # is the thing you reach for, not a labelled field in a form
            yield Search(placeholder=t("search_all"), id="search")
        # the kind is a column and not a glyph in front: it is the thing you
        # scan for, and a column aligns and sorts where a glyph does neither
        yield Card(t("sec_results"),
                   Table((t("sec_kinds"), 9, "text"), (t("col_name"), 46, "text"),
                         (t("col_project"), None, "text"), id="t-results"),
                   id="results")
        # two cards, stacked, and no grid of four. The dashboard used to answer
        # four questions at once -- what would travel, how far the two sides
        # are apart, what the plan has left, how much of everything there is --
        # in four boxes of different densities, and the one number anybody
        # opens the screen for (is there anything to sync?) was a cell in a
        # table. Now the counts are the headline and the parity detail lives on
        # the Config tab, which is the screen that can actually change it.
        # no cards. Four boxes became two and two became none: a border is for
        # telling panels apart, and there is one thing here -- the state of
        # your OS, read top to bottom. Framing each half of it drew two
        # rectangles whose only job was to separate numbers from gauges, which
        # a blank line already does.
        with Container(id="home-grid"):
            yield Static(id="stats-body")
            with Container(id="usage-wrap"):
                yield Static(id="usage-body")

    # the box fires per keystroke and a search is a tenth of a second even with
    # the index warm -- `difflib` is doing real work. It runs when you stop
    # typing, which is also when you meant it to
    DEBOUNCE = 0.2

    def on_mount(self) -> None:
        self.hits = []
        self._timer = None
        self.query_one("#results").display = False
        self.refresh_data()

    def on_input_changed(self, event) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(self.DEBOUNCE, self.run_search)

    def run_search(self) -> None:
        """Every corpus, ranked, with the kind of each hit beside it.

        The box used to hand its text to the Sessions tab, which made it a
        worse copy of the box already on that screen.
        """
        self._timer = None
        q = self.query_one("#search", Search).value
        self.hits = ui.search_all(q) if q.strip() else []
        panel = self.query_one("#results")
        panel.display = bool(q.strip())
        # the dashboard steps aside: while you are searching, the four cards
        # are not what you are looking at
        self.query_one("#home-grid").display = not panel.display
        table = self.query_one("#t-results", Table)
        table.clear()
        for h in self.hits:
            table.add_row(
                Content.from_markup(f"[$accent]{t('kind_' + h['kind'])}[/]"),
                clip(h["label"], 200), clip(h["sub"], 40))
        table.fit()
        if not self.hits and q.strip():
            self.app.empty(table, t("cli_no_hits", q=q))
        self.app._more_check()

    def on_input_submitted(self, event) -> None:
        """`↵` in the box goes to the results, not to another screen."""
        if self.hits:
            self.query_one("#t-results", Table).focus()

    def on_data_table_row_selected(self, event) -> None:
        self.open()

    def open(self) -> None:
        """`↵` on a result opens it where it belongs."""
        table = self.query_one("#t-results", Table)
        if not self.hits or not table.has_focus:
            return
        hit = self.hits[table.cursor_row]
        ref = hit["ref"]
        if hit["kind"] == "session":
            self.app.push_screen(Reader(clip(ref["title"], 60), transcript(ref)))
        elif hit["kind"] == "memory":
            self.app.open_memory(ref["project"], ref["slug"], ref["machine"])
        elif hit["kind"] == "note":
            body = Path(ref["path"]).read_text(encoding="utf-8", errors="replace")
            self.app.push_screen(Reader(hit["label"], body, markdown=True))
        else:
            # after the refresh: `enter` reaches here twice -- once as the
            # table's RowSelected and once as the app's priority binding -- and
            # switching tab inside the first made the second land on the Tools
            # pane and open its row as a document. Deferred, both calls are the
            # same idempotent jump
            self.app.call_after_refresh(self._go_tool, ref)

    def _go_tool(self, ref) -> None:
        self.app.show_tab(TOOLS)
        self.app.panes[TOOLS].show(ref["module"], ref["id"])

    def close_search(self) -> bool:
        """`Esc` puts the dashboard back. True if there was something to close."""
        if not self.query_one("#results").display:
            return False
        self.query_one("#search", Search).value = ""
        self.run_search()
        return True

    # the tiles of the headline row, in the order the questions come
    TILE_W = 14

    def _tiles(self, pairs):
        """Numbers on one line, their names under them, one column each.

        A count is read by looking at it, not by parsing `43 sessions · 12
        projects · …` -- the old strip put five numbers and five words on one
        line and made you find the boundaries yourself.
        """
        w = self.TILE_W
        nums = "".join(f"[$accent b]{str(n):^{w}}[/]" for _, n in pairs)
        names = "".join(f"[$foreground 45%]{clip(t(k), w - 2).upper():^{w}}[/]"
                        for k, _ in pairs)
        return f"{nums}\n{names}"

    def refresh_data(self) -> None:
        app = self.app
        sy = app.sync
        up, down = app.preview

        counts = dict(ui.counters())
        tiles = self._tiles([(k, counts.get(k, 0)) for k in
                             ("n_sessions", "n_projects", "n_memories",
                              "n_skills", "n_machines")])

        # the two arrows are the headline, not a row in a table: "is there
        # anything to do" is the question the screen exists to answer, and a
        # bare `▲ 12` next to a bare `▼ 0` made you work out which was which
        if not sy.get("remote"):
            arrows = (f"[$warning]{t('no_remote')}[/]"
                      f"   [$foreground 55%]{t('guide_hint')}[/]")
        elif not app.counted:
            # the counts land a phase after the git status, and `0` there reads
            # as "nothing to sync" -- the opposite of "not known yet"
            arrows = "   ".join(chip(f"{a} \u00b7\u00b7\u00b7 {t(k)}", "off")
                                for a, k in (("\u25b2", "to_push"),
                                             ("\u25bc", "to_pull")))
        else:
            arrows = "   ".join(
                chip(f"{a} {n}  {t(k)}", "on" if n else "off")
                for a, n, k in (("\u25b2", app.to_push, "to_push"),
                                ("\u25bc", app.to_pull, "to_pull")))
            parts = " \u00b7 ".join(ui.preview_parts(up) + ui.preview_parts(down))
            if parts:
                arrows += f"\n\n[$foreground 55%]{clip(parts, 72)}[/]"
            elif not (sy["ahead"] or sy["behind"]):
                arrows += f"\n\n[$success]{t('all_synced')}[/]"

        lines = [tiles, "", arrows, "",
                 f"[$foreground 45%]{t('last_sync')} [/][$foreground 70%]{ui.last_sync()}[/]"
                 f"[$foreground 25%]   \u00b7   [/]"
                 f"[$foreground 45%]git [/][$accent]\u2191{sy['ahead']} \u2193{sy['behind']}[/]"
                 f"[$foreground 25%]   \u00b7   [/]"
                 + (f"[$warning]{t('dirty')}[/]" if sy["dirty"]
                    else f"[$success]{t('clean')}[/]")
                 + f"[$foreground 25%]   \u00b7   [/]"
                   f"[$foreground 45%]{t('checked', ago=ui.checked_ago())}[/]"]
        if app.update.get("available"):
            lines.append("")
            lines.append(chip(f"\u25b2 {t('update_available')}: "
                              f"{app.update['available']}   u", "quiet"))
        self.query_one("#stats-body", Static).update(
            Content.from_markup("\n".join(lines)))

        usage = []
        for lim in (app.usage.get("limits") or []):
            usage.append(gauge((lim.get("label") or lim.get("kind") or "?").replace("_", " "),
                               lim.get("percent") or 0,
                               ui._reset_at(lim.get("resetsAt"))))
        costs = [d.get("totalCost") or 0 for d in (app.usage.get("daily") or [])]
        if costs:
            usage.append("")
            usage.append(f"[$foreground 65%]{t('usage_daily'):<15}[/]"
                         f"[$accent]{spark(costs, 36)}[/]"
                         f"[$foreground 45%]   {costs[-1]:.0f}[/]")
        self.query_one("#usage-body", Static).update(Content.from_markup(
            "\n".join(usage) or f"[$foreground 60%]{t('no_usage')}[/]"))


class Config(Container):
    """Three cards, because these are three unrelated things.

    One long list ran the preferences, the counts and the modules together with
    nothing but a heading between them, and a heading inside a table is a row
    pretending to be a title.
    """

    def compose(self) -> ComposeResult:
        yield Card(t("sec_prefs"),
                   Table(("", 22), ("", None), id="t-prefs", show_header=False),
                   id="prefs")
        yield Card(t("sec_modules"),
                   Table(("", 14), ("", 6), ("", None), id="t-modules",
                         show_header=False), id="modules")
        yield Card(t("sec_remote"), Static(id="remote-body"), id="remote")

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        prefs = self.query_one("#t-prefs", Table)
        keep = prefs.cursor_row
        prefs.clear()
        # the value shows what is on, not the whole menu: three words with one
        # of them bright is a legend to decode, and the row changes on ↵ anyway
        prefs.add_row(t("accent_color"),
                      Content.from_markup(f"[$accent b]{ui.accent_name()}[/]"))
        prefs.add_row(t("tui_ground"),
                      Content.from_markup(f"[$accent b]{t('ground_' + self.app.ground)}[/]"))
        prefs.add_row(t("language"), Content.from_markup(f"[$accent b]{i18n.LANG}[/]"))
        on = srv.badge_status()["on"]
        prefs.add_row(t("badge_row"), Content.from_markup(pill(on)))
        prefs.fit()
        if 0 <= keep < prefs.row_count:
            prefs.move_cursor(row=keep)

        mods = self.query_one("#t-modules", Table)
        keep = mods.cursor_row
        mods.clear()
        for key, n in ui.knowledge_counts().items():
            mods.add_row(t("n_" + key), Content.from_markup(pill(True)),
                         Content.from_markup(
                             f"[$foreground 60%]{n} · {t('always_syncing')}[/]"))
        self.modules = srv.config_status()
        for m in self.modules:
            # the drift the home used to keep in a table of its own: two file
            # counts and how far apart they are, on the row that can turn the
            # module off
            dl, dr = self.app.deltas(m)
            drift = (f"[$warning]ΔL{dl}[/] " if dl else "") + \
                    (f"[$primary]ΔR{dr}[/]" if dr else "")
            mods.add_row(
                m["id"],
                Content.from_markup(pill(m["enabled"])),
                Content.from_markup(
                    f"[$foreground 60%]{m['localFiles']} {t('local')} · "
                    f"{m['repoFiles']} {t('in_repo')}[/]   {drift}"))
        mods.fit()
        if 0 <= keep < mods.row_count:
            mods.move_cursor(row=keep)

        lines = []
        for name, url, note in (("origin", ui._origin(), t("r_origin")),
                                ("upstream", ui._upstream(), t("r_upstream"))):
            lines.append(f"[$accent b]{name}[/]  [$foreground 60%]{note}[/]")
            lines.append(f"  {esc(url)}" if url
                         else f"  [$warning]{t('no_remote')}[/]")
            lines.append("")
        lines.append(f"[$foreground 60%]{t('guide_hint')}[/]")
        lines.append(f"[$accent b]{len(TABS)}[/] [$foreground 60%]{t('tab_help')}[/]")
        self.query_one("#remote-body", Static).update(
            Content.from_markup("\n".join(lines)))

    def open(self) -> None:
        """`↵` on the selected row of whichever of the two tables has focus."""
        prefs = self.query_one("#t-prefs", Table)
        mods = self.query_one("#t-modules", Table)
        if prefs.has_focus:
            row = prefs.cursor_row
            if row == 0:
                codes = [c for _, c in ui.ACCENTS]
                ui.set_accent(codes[(codes.index(ui.ACCENT) + 1) % len(codes)])
                self.app.apply_theme()
                return
            if row == 1:
                names = list(GROUNDS)
                self.app.ground = names[(names.index(self.app.ground) + 1) % len(names)]
                i18n.set_pref("tui_ground", self.app.ground)
                self.app.apply_theme()
                return
            if row == 2:
                ui.set_lang(i18n.LANGS[(i18n.LANGS.index(i18n.LANG) + 1) % len(i18n.LANGS)])
            else:
                srv.set_badge(not srv.badge_status()["on"])
        elif mods.has_focus:
            fixed = len(ui.knowledge_counts())
            index = mods.cursor_row - fixed
            if index < 0:
                return                     # the always-synced rows are not a toggle
            mod = self.modules[index]["id"]
            enabled = set(srv.get_sync_prefs())
            enabled.discard(mod) if mod in enabled else enabled.add(mod)
            srv.set_sync_prefs(sorted(enabled))
        self.refresh_data()

    def on_data_table_row_selected(self, event) -> None:
        self.open()


class Help(Container):
    """The `sto` commands, read off the CLI registry, plus the setup guide.

    Keyboard shortcuts are not here: the footer already shows the ones for the
    screen you are on, and a second list of them goes stale on its own every
    time a key moves.
    """

    def compose(self) -> ComposeResult:
        yield Card(t("sec_commands"),
                   Table((t("sec_commands"), 34), ("", None), id="t-help",
                         show_header=False), id="commands")
        yield Card(t("guide_open"), VerticalScroll(Static(id="guide-body")), id="guide")

    def on_mount(self) -> None:
        table = self.query_one("#t-help", Table)
        for usage, what in ui.commands():
            table.add_row(Content.from_markup(f"[$accent]{esc(usage)}[/]"),
                          Content.from_markup(f"[$foreground 60%]{esc(what)}[/]"))
        table.fit()

        lines = []
        # step5 is the only line that changes with the OS: the installer does.
        fills = {"step5": {"installer": i18n.installer_cmd()}}
        for sub, where, steps in (
                (t("sub_first_time"), "where_steps",
                 ("step1", "step2", "step3", "step3b", "step3c")),
                (t("sub_each_machine"), "where_more",
                 ("step4", "step5", "step6", "step6b", "step6c")),
                (t("sub_updates"), None, ("step7", "step8", "step9"))):
            lines.append(f"[$accent b]{sub}[/]")
            # the "where do I run this" line first: that was the whole
            # confusion, the steps never said which folder they belonged to
            for key in ([where] if where else []) + list(steps):
                lines.append(f"[$foreground 70%]{esc(t(key, **fills.get(key, {})))}[/]")
            lines.append("")
        self.query_one("#guide-body", Static).update(Content.from_markup("\n".join(lines)))


# ── the app ──

class TabBar(Container):
    """The row of tabs, and a place the keyboard can stand.

    `Tab` is the natural key for walking the panels inside a screen and it was
    spent on walking the screens themselves, which left the panels reachable
    only with a mouse. Moving it means the bar needs its own way in, so it
    takes focus like anything else: from `Tab` wrapping round the end of the
    pane, or from `↑` at the top of the first list.
    """
    can_focus = True

    BINDINGS = [
        Binding("left", "app.prev_tab", "", show=False),
        Binding("right", "app.next_tab", "", show=False),
        Binding("down,enter,escape", "leave", "", show=False),
    ]

    def action_leave(self) -> None:
        self.app.action_panel_next()


class StoApp(App):
    CSS_PATH = "tui_app.tcss"
    TITLE = "braingent STO"
    # the palette is the library's own screen, in the library's own idiom, and
    # it puts a button in our footer that leads out of the product
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        *[Binding(str(i + 1), f"tab({i})", "", show=False) for i in range(len(TABS))],
        # priority: Tab is the library's focus-next by default, and ours has to
        # wrap through the tab bar rather than wander the whole DOM
        Binding("tab", "panel_next", "panel", priority=True),
        Binding("shift+tab", "panel_prev", "", show=False, priority=True),
        Binding("enter", "open", "", show=False, priority=True),
        Binding("escape", "back", "", show=False),
        Binding("p", "sync('push')", "PUSH"),
        Binding("l", "sync('pull')", "PULL"),
        Binding("f", "fetch", "FETCH"),
        Binding("u", "update", "UPDATE"),
        Binding("g", "graph", "GRAPH"),
        Binding("s", "sort", "sort"),
        Binding("r", "reload", "reload"),
        Binding("q", "quit", "quit"),
        # shown, not hidden: `check_action` below offers each one only on the
        # tab that can do it, so the footer names the verbs instead of leaving
        # them to be discovered by accident
        Binding("e", "verb('row_sync')", t("k_row_sync")),
        Binding("w", "verb('row_path')", t("k_row_path")),
        Binding("k", "verb('keep')", t("k_keep")),
        Binding("a", "verb('bring')", t("k_bring")),
        Binding("d", "verb('delete')", t("k_delete")),
        Binding("R", "verb('forget')", t("k_forget")),
    ]

    def __init__(self):
        super().__init__()
        # STO_TUI_TAB is how a screen other than the home gets captured: piped
        # into a file there is no keyboard to press `2` with.
        self.tab = int(os.environ.get("STO_TUI_TAB") or 0)
        self.ground = i18n.get_prefs().get("tui_ground", "dark")
        if self.ground not in GROUNDS:
            self.ground = "dark"
        self._blank()

    # ── data ──

    def _blank(self) -> None:
        """Enough of a shape for the screen to paint before git has answered."""
        empty = {"skills": [], "config": [], "memories": {}, "sessions": 0, "vault": 0}
        self.sync = {"remote": None, "branch": None, "ahead": 0, "behind": 0,
                     "dirty": False}
        self.preview = (empty, dict(empty))
        self.parity = {"modules": [], "local_only": [], "repo_only": []}
        self.usage = {"limits": [], "daily": []}
        self.update = {"available": 0}
        self.to_push = self.to_pull = 0
        # `0 to push` and `not counted yet` are different answers, and the
        # first one is a lie the home used to tell for a second and a half
        self.counted = False
        # which panes hold a paint older than the data behind them
        self._stale = set()

    # Everything the chrome and the home read, in three phases and not one
    # call. The same functions `cli.py` calls — nothing here recomputes a rule,
    # so the two flavours cannot disagree about a number — but they do not cost
    # the same, and paying for the slowest before drawing any of them is how
    # the screen stayed empty for twenty seconds. `load_all` runs them in turn
    # and repaints between.

    def load_fast(self) -> None:
        """What git already knows, and the plan percentages. ~0.4 s."""
        self.sync = srv.sync_status(fetch=False)
        # `detail=True` spawns `npx ccusage` twice — fifteen seconds for a spend
        # breakdown only the sparkline reads, and `load_slow` is where it goes.
        # The percentages are one https call and they come back here.
        self.usage = srv.usage_snapshot(detail=False)

    def load_counts(self) -> None:
        """What would travel, and how far apart the two sides are. ~1.3 s:
        `sync_preview` dry-runs four exports and shells out to git."""
        self.parity = ui.parity()
        self.preview = ui.sync_preview(self.sync)
        self.to_push = ui.count_items(self.preview[0])
        self.to_pull = ui.count_items(self.preview[1])
        self.counted = True

    def load_slow(self) -> None:
        """The two that leave the machine: the upstream ref and ccusage."""
        self.update = ui.update_state()
        self.usage = srv.usage_snapshot(detail=True)

    PHASES = (("ld_git", "load_fast"), ("ld_counts", "load_counts"),
              ("ld_usage", "load_slow"))

    def reload_data(self) -> None:
        """All three, in order. For the callers that end in a repaint of their
        own and have nothing to show in between."""
        for _, name in self.PHASES:
            getattr(self, name)()

    def deltas(self, m):
        """How many items only one side has.

        `skills` is the only module where the engine knows this by name, so it
        is the only one with an exact answer; for the rest the difference
        between the two file counts is the honest approximation, and it is what
        the terminal TUI already shows as `148 local · 149 in repo`.
        """
        if m["id"] == "skills":
            return len(self.parity["local_only"]), len(self.parity["repo_only"])
        return (max(0, m["localFiles"] - m["repoFiles"]),
                max(0, m["repoFiles"] - m["localFiles"]))

    def empty(self, table, message) -> None:
        """A table with nothing in it says why, instead of being a blank box."""
        table.add_row(Content.from_markup(f"[$foreground 60%]{esc(message)}[/]"))

    # ── chrome ──

    def topbar_content(self) -> Content:
        remote = (self.sync.get("remote") or "").replace("https://", "").removesuffix(".git")
        sep = "[$foreground 30%]  │  [/]"
        return Content.from_markup(
            f"[$accent b]braingent STO[/]{sep}"
            f"[$foreground 60%]repo [/]{esc(remote) or t('no_remote')}{sep}"
            f"[$foreground 60%]agent [/]{srv.agents.label()}{sep}"
            f"[$foreground 60%]{t('col_machine')} [/]{srv.LOCAL_MACHINE}")

    def compose(self) -> ComposeResult:
        # one container docked to the top and not two widgets each docked to it:
        # docking is to an edge, so two of them land on the same row and the
        # second draws over the first
        with Container(id="chrome"):
            yield Static(self.topbar_content(), id="topbar")
            with TabBar(id="tabs"):
                for i, key in enumerate(TABS):
                    yield Static(f" {t(key)} ", classes="tab", id=f"tab-{i}")
        yield Home(id="home", classes="home")
        yield Sessions(id="sessions", classes="split")
        yield Memory(id="memory", classes="split")
        yield Tools(id="tools", classes="split three-way")
        yield Config(id="config", classes="three")
        yield Help(id="help", classes="two")
        # One container docked to the bottom, with the footer inside it. The
        # same lesson the chrome learned at the top edge, and it has to include
        # the footer: docking is to an *edge*, not a stack, so a second docked
        # widget lands on the footer's own row and the footer draws over it.
        # That is why the status strip never appeared -- not while pushing, not
        # while fetching, not once. It was rendering, underneath.
        with Container(id="bottom"):
            yield Static("", id="more")
            yield Static("", id="status")
            yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.apply_theme()
        self.show_tab(self.tab)
        # the arrow follows the scroll of whichever pane is on screen. `watch`
        # on the reactive rather than a timer: it has to be right the frame the
        # scroll lands, and it costs nothing while nothing scrolls.
        for pane in self.panes:
            self.watch(pane, "scroll_y", self._more_check, init=False)
        # the strip carries it, not a toast: opening the app is not an event,
        # and a notification for it is one more thing to dismiss
        self.busy(t("ld_git"))
        self.load_all()

    def on_resize(self) -> None:
        # Textual CSS has no media query, so the breakpoints are classes the
        # app puts on itself and the stylesheet answers. Nothing else happens
        # here: a resize that re-ran the screens made dragging a window feel
        # like mud.
        #
        # Three and not one, because they answer three different questions.
        # `narrow` is "do two columns fit"; `tiny` and `short` are "does the
        # wordmark fit", which is a smaller box with its own pair of numbers.
        self.set_class(self.size.width < 100, "narrow")
        self.set_class(self.size.width < WORDMARK_W + 5, "tiny")
        self.set_class(self.size.height < 24, "short")
        # the tall face needs both a wide window and the rows to spend on it;
        # under either, the flat one still says the name
        grand = (self.size.width >= WORDMARK_BIG_W + 6
                 and self.size.height >= 30)
        if grand != self.has_class("grand"):
            self.set_class(grand, "grand")
            self.query_one("#wordmark", Wordmark).repaint()
        # re-applied because which panels are displayed depends on `narrow`,
        # and this is the moment it changed. Toggling `display` on three
        # widgets, not recomposing a screen: that was tried, and it made
        # dragging a window feel like mud.
        for pane in self.panes:
            if hasattr(pane, "set_level"):
                pane.set_level(pane.level)
        self.call_after_refresh(self._more_check)

    def apply_theme(self) -> None:
        """One accent, one ground, both ours.

        The accent comes from `sto ui` — the same setting drives both flavours,
        so they are the same product with the same colour. The ground is this
        flavour's own preference: a terminal cannot be asked what its
        background is, so which of the three it is has to be said.
        """
        theme = theme_for(self.ground, ui.ACCENT)
        self.register_theme(theme)
        self.theme = theme.name
        # the panes hold rendered content, not live markup: a theme change has
        # to ask them to paint again or the old accent stays on screen. Only
        # the ones on screen — the rest are stale until you switch to them,
        # which is also what stops `on_mount` walking every session on disk
        # before the first frame.
        self._repaint()
        self.query_one("#wordmark", Wordmark).repaint()
        self.query_one("#topbar", Static).update(self.topbar_content())

    @property
    def panes(self):
        return [self.query_one(f"#{name}") for name in
                ("home", "sessions", "memory", "tools", "config", "help")]

    def show_tab(self, index) -> None:
        self.tab = index % len(TABS)
        # the footer caches which keys it offers, and `check_action` answers
        # per tab: without this the verbs of the tab you left stay on screen
        self.refresh_bindings()
        for i, pane in enumerate(self.panes):
            pane.display = i == self.tab
        for i, chip in enumerate(self.query(".tab")):
            chip.set_class(i == self.tab, "on")
        # focus starts on the left-hand list of the screen, which is the one
        # you choose with before you read with
        pane = self.panes[self.tab]
        if self.tab in self._stale:
            # skipped while off screen; this is the moment it is worth the half
            # second, and the moment its columns can be fitted at all
            self._stale.discard(self.tab)
            if hasattr(pane, "refresh_data"):
                pane.refresh_data()
        tables = list(pane.query(Table))
        for table in tables:
            # a hidden pane has no size, so its columns were never fitted; the
            # width is only knowable once the pane is the one on screen
            table.call_after_refresh(table.fit)
        # not while the bar itself has the focus: changing tab from up there is
        # how you look around, and being dropped into the content every time
        # means you can only ever move one tab
        if tables and not self.query_one("#tabs", TabBar).has_focus:
            tables[0].focus()
        self.call_after_refresh(self._more_check)

    # ── work off the UI thread ──

    @work(thread=True, exclusive=True)
    def load_all(self, fetch: bool = False) -> None:
        """The first paint does not wait for git, and no paint waits for ccusage.

        All of this used to be one call in `__init__`, so the terminal sat
        blank while git ran and the app felt broken before it had drawn
        anything. Moving it to a thread fixed the blankness and left the
        slowness: one worker that repainted only at the end still made the
        whole screen wait on `npx ccusage`. Now each phase repaints as it
        lands, and the strip says which one is running.
        """
        if fetch:
            self.call_from_thread(self.busy, "FETCH")
            # the phases read `.git/FETCH_HEAD` afterwards and find it fresh
            self.sync = srv.sync_status(fetch=True, force=True)
        for step, name in self.PHASES:
            self.call_from_thread(self.busy, t(step))
            getattr(self, name)()
            self.call_from_thread(self._painted)
        self.call_from_thread(self.done)

    def _repaint(self) -> None:
        """Rebuild the panes that are on screen, and mark the rest stale.

        A pane nobody is looking at costs the same to rebuild as one on screen
        — `cached_sessions`, `list_memory` and `module_items` are most of a
        second between them, on the UI thread — and with the load split in
        three this runs three times instead of once. `show_tab` rebuilds a
        stale pane at the moment it becomes visible, which is the only moment
        the work buys anything.
        """
        self._stale = set(range(len(TABS)))
        for index in {HOME, self.tab}:
            self._stale.discard(index)
            pane = self.panes[index]
            if hasattr(pane, "refresh_data"):
                pane.refresh_data()

    def _painted(self) -> None:
        self._repaint()
        self.query_one("#topbar", Static).update(self.topbar_content())

    # ── the status strip ──

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def busy(self, message) -> None:
        """Say what is running, in the strip above the keys.

        `fetch`, `reload`, `push` and `pull` all go to the network or to git
        and all of them used to look like a key that did nothing until they
        were done. A spinner beside the sentence is the difference between
        "working" and "broken".
        """
        self._busy = message
        self._frame = getattr(self, "_frame", 0)
        self._paint_status()
        if getattr(self, "_spin", None) is None:
            self._spin = self.set_interval(0.08, self._tick)

    def _paint_status(self) -> None:
        # the interval outlives the screen: an app closed while a load is still
        # running keeps ticking at a strip that is no longer there
        strip = self.query("#status")
        if not strip:
            return
        strip.first(Static).update(Content.from_markup(
            f"[$accent]{self.SPINNER[self._frame % len(self.SPINNER)]}[/]"
            f" [$foreground 70%]{esc(self._busy)}[/]"))

    def _tick(self) -> None:
        self._frame += 1
        self._paint_status()

    def done(self, message="", error=False) -> None:
        if getattr(self, "_spin", None) is not None:
            self._spin.stop()
            self._spin = None
        colour, mark = ("$error", "×") if error else ("$success", "●")
        self.query_one("#status", Static).update(
            Content.from_markup(f"[{colour}]{mark}[/] [$foreground 70%]{esc(message)}[/]")
            if message else Content(""))
        if message:
            # the strip is glanceable and the toast is unmissable; a push that
            # failed should not be a line you might have looked away from
            self.notify(message, severity="error" if error else "information")

    # ── actions ──

    def action_tab(self, index: int) -> None:
        self.show_tab(index)

    # ── the "there is more below" arrow ──

    def _scrollable(self):
        """The pane on screen, if it is one that scrolls."""
        pane = self.panes[self.tab]
        return pane if pane.max_scroll_y > 0 else None

    def _more_check(self) -> None:
        pane = self._scrollable()
        more = self.query_one("#more", Static)
        # `scroll_y` is a float and lands a hair short of `max_scroll_y` at the
        # bottom, which left the arrow on screen pointing at nothing
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

    def action_prev_tab(self) -> None:
        self.show_tab(self.tab - 1)

    def action_next_tab(self) -> None:
        self.show_tab(self.tab + 1)

    def focus_ring(self):
        """The tab bar, then every panel of the pane on screen, in DOM order.

        Written out rather than left to `focus_next`: the library walks the
        whole screen, and a widget's `focusable` asks about `visibility`, not
        `display` — so a pane switched off with `display` still offers its
        tables to `Tab`, and the Sessions screen handed the focus to a table
        belonging to the home. Walking from the pane and honouring `display` at
        every level is what keeps `Tab` inside the screen you are looking at,
        which is also what makes it work for the narrow levels for free.
        """
        def panels(node):
            for child in node.children:
                if not child.display:
                    continue
                if child.focusable:
                    yield child
                yield from panels(child)

        return [self.query_one("#tabs", TabBar)] + list(panels(self.panes[self.tab]))

    def _step(self, delta: int) -> None:
        ring = self.focus_ring()
        # not in the ring (a tab just changed, a modal just closed): the first
        # panel is a better landing than the bar you were trying to leave
        index = ring.index(self.focused) if self.focused in ring else 0
        ring[(index + delta) % len(ring)].focus()

    def action_panel_next(self) -> None:
        """The next panel of the pane you are on.

        The tab bar is the first stop of the ring, so wrapping past the last
        panel lands on it — which is what makes it reachable at all.
        """
        self._step(1)

    def action_panel_prev(self) -> None:
        self._step(-1)

    def focus_tabs(self) -> None:
        self.query_one("#tabs", TabBar).focus()

    def action_open(self) -> None:
        """`↵` opens what the screen is pointed at — unless a box owns it.

        The binding is `priority`, so the app gets the key before the focused
        widget does and an `Input` never saw its own `enter`: every
        `on_input_submitted` in this file was dead code, and the path prompt
        could be typed into but not answered. Returning early is not enough —
        the key is already consumed — so the message the box would have sent is
        sent for it.
        """
        focused = self.focused
        if isinstance(focused, Input):
            return focused.post_message(Input.Submitted(focused, focused.value))
        pane = self.panes[self.tab]
        if hasattr(pane, "open"):
            pane.open()

    def action_back(self) -> None:
        """`Esc` closes the search, then climbs one level, then does nothing."""
        pane = self.panes[self.tab]
        if hasattr(pane, "close_search") and pane.close_search():
            return
        if hasattr(pane, "back"):
            pane.back()

    def action_sort(self) -> None:
        """`s` sorts the table the keys are pointed at, and nothing else."""
        if isinstance(self.focused, Input):
            return
        if isinstance(self.focused, Table):
            self.focused.cycle_sort()

    def check_action(self, action: str, parameters: tuple):
        """Which keys the footer offers, tab by tab.

        The verbs are bound at the app so one handler dispatches them, but each
        only means something on a pane that declares it. `None` hides the key
        rather than advertising a `d` on the home that deletes nothing.
        """
        if action != "verb":
            return True
        panes = getattr(self, "panes", None)
        if not panes:
            return None                    # before mount there is no pane to ask
        verbs = getattr(panes[self.tab], "VERBS", ())
        return True if parameters and parameters[0] in verbs else None

    def action_verb(self, verb: str) -> None:
        """`a` / `d` / `R` / `k` belong to whichever screen can do them. Bound at the
        app so the footer can name them, dispatched to the pane so a screen
        with no such verb simply does not have one."""
        if isinstance(self.focused, Input):
            return
        pane = self.panes[self.tab]
        if hasattr(pane, "act"):
            pane.act(verb)

    def open_memory(self, project, slug, machine=None) -> None:
        """A memory, its body, and one level of the graph around it as rows you
        can walk into."""
        row = {"project": project, "slug": slug,
               "machine": machine or srv.LOCAL_MACHINE}
        if machine is None:
            for p in srv.list_memory():
                if p["project"] == project:
                    for m in p["memories"]:
                        if m["slug"] == slug:
                            row["machine"] = m["machine"]
        body = "\n".join(ui.strip_ansi(line) for line in ui.detail_memory(row))
        try:
            out, inc = srv.memory_neighbours(project, slug)
        except Exception:
            out, inc = [], []            # a memory reads fine without its edges
        links = [("→", mid) for mid in out] + [("←", mid) for mid in inc]
        self.push_screen(Reader(f"{project}/{slug}", body, links, markdown=True))

    def action_reload(self) -> None:
        self.load_all()

    def action_fetch(self) -> None:
        self.load_all(fetch=True)

    def action_graph(self) -> None:
        """The classic window. `cli.open_memory_graph` already knows how to
        build it and how to find a chrome-less browser, and its answer — the
        one that says what is missing when it fails — is what gets shown."""
        self.busy(t("graph_opening"))
        res = cli.open_memory_graph()
        self.done(res.get("error") or res.get("message") or "", bool(res.get("error")))

    def action_update(self) -> None:
        """`u` — the OS itself, not your knowledge. The log of what is coming is
        the manifest: an update you cannot see the shape of is one you accept
        blind."""
        if isinstance(self.focused, Input):
            return
        st = self.update
        if not st.get("available"):
            return self.notify(t("all_synced"))
        lines = [f"[$foreground 70%]{esc(line)}[/]" for line in (st.get("log") or [])[:14]]
        self.push_screen(
            Confirm(f"▲ {t('update_available')}: {st['available']}", lines),
            lambda yes: self._run_update() if yes else None)

    @work(thread=True, exclusive=True)
    def _run_update(self) -> None:
        self.call_from_thread(self.busy, t("update_available"))
        res = srv.update_apply(progress=lambda step:
                               self.call_from_thread(self.busy, t(step)))
        self.call_from_thread(self.done, res.get("error") or t("update_restart"),
                              bool(res.get("error")))
        self.reload_data()
        self.call_from_thread(self._painted)

    def action_sync(self, what: str) -> None:
        """Nothing moves before the manifest is on screen.

        The count on the key cap says how much; this says of what, which is the
        question you actually have with a finger over the key.
        """
        if isinstance(self.focused, Input):
            return
        data = self.preview[0 if what == "push" else 1]
        title = f"{'▲' if what == 'push' else '▼'} {what.upper()}"
        self.push_screen(Confirm(title, manifest(data)),
                         lambda yes: self._run_sync(what) if yes else None)

    @work(thread=True, exclusive=True)
    def _run_sync(self, what: str) -> None:
        """On a thread, with the engine's own step names in the strip.

        `sync_push` takes a progress callback and the stdlib TUI paints it live;
        blocking the UI for the length of a push and then saying "done" is the
        one thing a spinner cannot make better.
        """
        fn = srv.sync_push if what == "push" else srv.sync_pull
        self.call_from_thread(self.busy, what.upper())
        res = fn(progress=lambda step: self.call_from_thread(self.busy, t(step)))
        self.call_from_thread(self.done, res.get("error") or res.get("message") or "",
                              bool(res.get("error")))
        self.reload_data()
        self.call_from_thread(self._painted)


def run():
    StoApp().run()


if __name__ == "__main__":
    run()
