"""braingent STO — the optional Textual flavour of the TUI.

`sto ui` is the one that always runs: Python stdlib, no dependencies, on any
machine. This is the flavour you pick, and it is allowed to want a library.

It imports `cli` and `sessions_server` **directly**, exactly like `ui.py` does.
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
import ui  # noqa: E402

from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Container, Grid, VerticalScroll  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.screen import ModalScreen, Screen  # noqa: E402
from textual.widgets import Footer, Input, Markdown, Static  # noqa: E402

from tui_widgets import (  # noqa: E402
    BOX_OFF, BOX_ON, GROUNDS, WORDMARK, WORDMARK_W, Card,
    Search, Table, Wordmark, ago, bar, clip, esc, spark, theme_for)

t = i18n.t

TABS = ["tab_home", "tab_sessions", "tab_memory", "tab_skills",
        "tab_config", "tab_help"]
HOME, SESSIONS, MEMORY, SKILLS, CONFIG, HELP = range(6)


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
            out.append(("tool", f"[$warning]\u2699 {esc(item['tool'])}[/]"
                                f"  {esc(clip(item.get('detail', ''), 120))}"))
        elif kind == "image":
            out.append(("tool", f"\u26f6 {t('cli_image')}"))
        elif kind == "error":
            out.append(("bad", f"\u2715 {esc(clip(item['text'], 400))}"))
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
        *[Binding(k, "nothing", "", show=False) for k in "plfgrus"],
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
        narrow = self.app.has_class("narrow")
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
        if self.app.has_class("narrow") and self.level > 0:
            self.set_level(self.level - 1)
            return True
        return False

    def drill(self) -> bool:
        """`↵` going one panel deeper. True if it moved.

        Only in one column: in a wide window every panel is already on screen
        and `↵` means what it has always meant.
        """
        if self.app.has_class("narrow") and self.level < len(self.LEVELS) - 1:
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

    def compose(self) -> ComposeResult:
        yield Search(id="search")
        yield Card(t("n_projects"),
                   Table((t("col_project"), self.GROUP_W - 14, "text"),
                         (t("col_total"), None, "num"), id="t-groups"), id="groups")
        yield Card(self.TITLE, self.make_table(), id="rows")

    def on_mount(self) -> None:
        self.q = ""          # the search text; `self.query` is the DOM query
        self.index = 0
        self.rows = []
        self.level = 0
        self.refresh_data()
        # focus starts on the left: you pick the project first, and the
        # right-hand list is what you move to once you have
        self.set_level(0)
        self.query_one("#t-groups", Table).focus()

    def set_groups(self, pairs, total) -> None:
        table = self.query_one("#t-groups", Table)
        keep = table.cursor_row
        table.clear()
        table.add_row(Content.from_markup(f"[$accent b]{t('show_all')}[/]"), str(total))
        for name, n in pairs:
            table.add_row(clip(name, self.GROUP_W - 15), str(n))
        table.fit()
        if 0 < keep < table.row_count:
            table.move_cursor(row=keep)

    def on_data_table_row_highlighted(self, event) -> None:
        if event.data_table.id == "t-groups":
            self.index = event.cursor_row
            self.fill()
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


class Sessions(Split):
    TITLE = t("tab_sessions")

    def make_table(self):
        # `col_when` has no third field and so is not in the cycle: it renders
        # `2 h` and `5 d`, and its correct order is `mtime`, which is the one
        # the rows already arrive in. `col_errors` is a `Content` with markup,
        # which is neither a number nor comparable text.
        return Table((t("col_when"), 10), (t("col_project"), 18, "text"),
                     (t("col_prompts"), 7, "num"), (t("col_tools"), 6, "num"),
                     (t("col_errors"), 7), (t("col_title"), None, "text"),
                     id="t-rows")

    def refresh_data(self) -> None:
        rows, _ = cli.cached_sessions()
        self.all_rows = rows
        groups = {}
        for r in rows:
            groups.setdefault(r["project"], []).append(r)
        self.groups = sorted(groups.items(), key=lambda kv: -kv[1][0]["mtime"])
        self.set_groups([(name, len(items)) for name, items in self.groups], len(rows))
        self.fill()

    def fill(self) -> None:
        pool = (self.all_rows if self.index == 0 or self.index > len(self.groups)
                else self.groups[self.index - 1][1])
        if self.q:
            q = self.q.lower()
            pool = [r for r in pool if q in f"{r['project']} {r['title']}".lower()]
        self.rows = pool
        table = self.query_one("#t-rows", Table)
        table.clear()
        for r in pool:
            table.add_row(ago(r["mtime"]), clip(r["project"], 18), str(r["n_prompts"]),
                          str(r["n_tools"]),
                          Content.from_markup(f"[$error]{r['errors']}[/]"
                                              if r["errors"] else "0"),
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


class Memory(Split):
    TITLE = t("tab_memory")

    def make_table(self):
        return Table((t("col_slug"), 28, "text"), (t("col_when"), 9),
                     (t("col_machine"), 14, "text"), (t("col_desc"), None, "text"),
                     id="t-rows")

    def refresh_data(self) -> None:
        self.projects = srv.list_memory()
        self.all_rows = [dict(m, project=p["project"])
                         for p in self.projects for m in p["memories"]]
        self.all_rows.sort(key=lambda m: -m["mtime"])
        self.set_groups([(p["project"], p["count"]) for p in self.projects],
                        len(self.all_rows))
        self.fill()

    def fill(self) -> None:
        pool = (self.all_rows if self.index == 0 or self.index > len(self.projects)
                else [dict(m, project=self.projects[self.index - 1]["project"])
                      for m in self.projects[self.index - 1]["memories"]])
        if self.q:
            q = self.q.lower()
            pool = [m for m in pool
                    if q in f"{m['project']} {m['slug']} {m['description']}".lower()]
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


class Skills(Levels, Container):
    """The skills and plugins of this machine and of the repo, together.

    This is the drill-down the terminal TUI does inside a config module, and it
    carries the same four states — the point of the screen is the rows that are
    only on one side.
    """

    LEVELS = ("rows", "detail")

    def compose(self) -> ComposeResult:
        yield Search(id="search")
        yield Card(t("tab_skills"),
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
        self.query_one("#t-rows", Table).focus()

    def refresh_data(self) -> None:
        rows = ui.module_items("skills") + ui.module_items("plugins")
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
                           else t("cli_no_skills"))
        self.preview(min(keep, max(0, len(rows) - 1)))

    def on_input_changed(self, event) -> None:
        self.q = event.value
        self.refresh_data()

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
        self.preview(event.cursor_row)

    def on_data_table_row_selected(self, event) -> None:
        self.open()

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
        self.app.push_screen(Reader(skill["name"], skill["content"], markdown=True))

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

    def ask(self, title, lines, danger, run) -> None:
        def answered(yes):
            if yes:
                run()
                self.app.action_reload()
        self.app.push_screen(Confirm(title, lines, danger), answered)

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
        yield Search(id="search")
        with Grid(id="home-grid"):
            yield Card(t("sec_sync"), Static(id="sync-body"))
            yield Card(t("sec_parity"),
                       Table((t("sec_modules"), 16), (t("local"), 6),
                             (t("in_repo"), 7), ("Δ L", 4), ("Δ R", 4),
                             id="t-parity"))
            yield Card(t("sec_usage"), Static(id="usage-body"))
            yield Card(t("sec_general"), Static(id="overall-body"))

    def on_mount(self) -> None:
        self.refresh_data()

    def on_input_submitted(self, event) -> None:
        """The home has no list of its own, so its box hands the query to the
        screen that does — which is what you wanted when you typed it here."""
        self.app.search_sessions(event.value)

    def refresh_data(self) -> None:
        app = self.app
        sy, p = app.sync, app.parity
        up, down = app.preview

        drift_l = drift_r = 0
        table = self.query_one("#t-parity", Table)
        table.clear()
        for m in p["modules"]:
            dl, dr = app.deltas(m)
            drift_l, drift_r = drift_l + dl, drift_r + dr
            dot = ("[$success]●[/]" if dl == dr == 0 and m["localFiles"]
                   else "[$warning]◐[/]" if dl
                   else "[$primary]◑[/]" if dr
                   else "[$foreground 40%]○[/]")
            name = m["id"] if m["enabled"] else f"[$foreground 50%]{m['id']}[/]"
            table.add_row(
                Content.from_markup(f"{dot} {name}"),
                str(m["localFiles"]), str(m["repoFiles"]),
                Content.from_markup(f"[$warning]{dl}[/]" if dl else "[$foreground 40%]·[/]"),
                Content.from_markup(f"[$primary]{dr}[/]" if dr else "[$foreground 40%]·[/]"))

        lines = []
        if not sy.get("remote"):
            # the one state where every number on this screen is meaningless
            lines.append(f"[$warning]{t('no_remote')}[/]")
            lines.append(f"[$foreground 60%]{t('guide_hint')} · {t('tab_help')}[/]")
        elif not app.counted:
            # the counts land one phase after the git status, and `0` there
            # reads as "nothing to sync" — the opposite of "not known yet"
            for arrow, key in (("▲", "to_push"), ("▼", "to_pull")):
                lines.append(f"[$foreground 50%]{arrow} ···[/]  "
                             f"[$foreground 60%]{t(key)}[/]")
            lines.append("")
        elif not (drift_l or drift_r or app.to_push or app.to_pull
                  or sy["ahead"] or sy["behind"]):
            # "in sync" is not a percentage. A parity bar at 100 % answered a
            # question nobody asked and left the one that matters — is there
            # anything to do? — to be inferred from a full bar.
            lines.append(f"[$success]● {t('all_synced')}[/]")
        else:
            for arrow, n, parts, key in (("▲", app.to_push, ui.preview_parts(up), "to_push"),
                                         ("▼", app.to_pull, ui.preview_parts(down), "to_pull")):
                colour = "$accent" if n else "$foreground 50%"
                lines.append(f"[{colour}]{arrow} {n}[/]  [b]{t(key)}[/b]")
                lines += [f"    [$foreground 60%]{x}[/]" for x in (parts or [t("nothing")])]
                lines.append("")
        lines += [
            f"[$foreground 60%]{t('last_sync'):<12}[/]{ui.last_sync()}",
            f"[$foreground 60%]{'git':<12}[/][$accent]↑{sy['ahead']} ↓{sy['behind']}[/]"
            f"[$foreground 40%] · [/]"
            + (f"[$warning]{t('dirty')}[/]" if sy["dirty"] else f"[$success]{t('clean')}[/]"),
            f"[$foreground 60%]{t('checked', ago=ui.checked_ago())}[/]",
        ]
        if app.update.get("available"):
            lines.append(f"[$success]▲ {t('update_available')}: "
                         f"{app.update['available']}[/]  [$accent b]u[/]")
        self.query_one("#sync-body", Static).update(Content.from_markup("\n".join(lines)))

        usage = []
        for lim in (app.usage.get("limits") or []):
            pct = lim.get("percent") or 0
            name = clip((lim.get("label") or lim.get("kind") or "?").replace("_", " "), 16)
            usage.append(f"[b]{name}[/b]  [$accent]{pct}%[/]"
                         f"[$foreground 60%]   {ui._reset_at(lim.get('resetsAt'))}[/]")
            usage.append(bar(pct, width=24))
            usage.append("")
        costs = [d.get("totalCost") or 0 for d in (app.usage.get("daily") or [])]
        if costs:
            usage.append(f"[$foreground 60%]{t('usage_daily')}[/]")
            usage.append(f"[$accent]{spark(costs, 24)}[/]"
                         f"[$foreground 60%]  {costs[-1]:.0f}[/]")
        self.query_one("#usage-body", Static).update(Content.from_markup(
            "\n".join(usage) or f"[$foreground 60%]{t('no_usage')}[/]"))

        counters = "   ".join(f"[$accent b]{n}[/] [$foreground 60%]{t(k)}[/]"
                              for k, n in ui.counters())
        machines = " · ".join(name + (f" ({t('this_one')})" if d["local"] else "")
                              for name, d in sorted(srv.list_machines().items()))
        always = " · ".join(f"{n} {t('n_' + k)}"
                            for k, n in ui.knowledge_counts().items())
        self.query_one("#overall-body", Static).update(Content.from_markup(
            f"{counters}\n\n"
            f"[$foreground 60%]{t('sec_machines'):<16}[/]{machines}\n"
            f"[$foreground 60%]{t('sec_always'):<16}[/]{always}\n"
            f"[$foreground 60%]{'agent':<16}[/]{srv.agents.label()}"))


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
                   Table(("", 16), ("", 6), ("", None), id="t-modules",
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
        prefs.add_row(t("badge_row"), Content.from_markup(
            f"[$accent]{BOX_ON if on else BOX_OFF}[/] "
            f"[$foreground 60%]{t('badge_on') if on else t('badge_off')}[/]"))
        prefs.fit()
        if 0 <= keep < prefs.row_count:
            prefs.move_cursor(row=keep)

        mods = self.query_one("#t-modules", Table)
        keep = mods.cursor_row
        mods.clear()
        for key, n in ui.knowledge_counts().items():
            mods.add_row(Content.from_markup(f"[$success]●[/] {t('n_' + key)}"), str(n),
                         Content.from_markup(f"[$foreground 60%]{t('always_syncing')}[/]"))
        self.modules = srv.config_status()
        for m in self.modules:
            mods.add_row(
                m["id"],
                Content.from_markup(f"[$accent]{BOX_ON if m['enabled'] else BOX_OFF}[/]"),
                Content.from_markup(
                    f"[$foreground 60%]{t('syncing') if m['enabled'] else t('not_syncing')}"
                    f"   {m['localFiles']} {t('local')} · {m['repoFiles']} {t('in_repo')}[/]"))
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
                lines.append(f"[$foreground 70%]{esc(t(key))}[/]")
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
        Binding("a", "verb('bring')", "", show=False),
        Binding("d", "verb('delete')", "", show=False),
        Binding("R", "verb('forget')", "", show=False),
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
    # call. The same functions `ui.py` calls — nothing here recomputes a rule,
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
        yield Skills(id="skills", classes="split wide-left")
        yield Config(id="config", classes="three")
        yield Help(id="help", classes="two")
        # one container docked to the bottom and not three widgets each docked
        # to it. The same lesson the chrome learned at the top edge: docking is
        # to an *edge*, not a stack, so the third one lands on the footer's row
        # and the two draw over each other.
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
                ("home", "sessions", "memory", "skills", "config", "help")]

    def show_tab(self, index) -> None:
        self.tab = index % len(TABS)
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
        colour, mark = ("$error", "✕") if error else ("$success", "✓")
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
        if isinstance(self.focused, Input):
            return
        pane = self.panes[self.tab]
        if hasattr(pane, "open"):
            pane.open()

    def action_back(self) -> None:
        """`Esc` climbs one level, and does nothing at the top."""
        pane = self.panes[self.tab]
        if hasattr(pane, "back"):
            pane.back()

    def action_sort(self) -> None:
        """`s` sorts the table the keys are pointed at, and nothing else."""
        if isinstance(self.focused, Input):
            return
        if isinstance(self.focused, Table):
            self.focused.cycle_sort()

    def action_verb(self, verb: str) -> None:
        """`a` / `d` / `R` belong to whichever screen can do them. Bound at the
        app so the footer can name them, dispatched to the pane so a screen
        with no such verb simply does not have one."""
        if isinstance(self.focused, Input):
            return
        pane = self.panes[self.tab]
        if hasattr(pane, "act"):
            pane.act(verb)

    def search_sessions(self, text) -> None:
        """The home's box hands its query to the screen that has the list."""
        self.show_tab(SESSIONS)
        box = self.panes[SESSIONS].query_one("#search", Search)
        box.value = text
        box.focus()

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
