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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # scripts/ is not a package

import cli  # noqa: E402
import i18n  # noqa: E402
import sessions_server as srv  # noqa: E402
import ui  # noqa: E402

from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Container, Grid, Horizontal, VerticalScroll  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.screen import Screen
from textual.theme import Theme  # noqa: E402
from textual.widgets import (  # noqa: E402
    DataTable, Footer, ListItem, ListView, Static,
)

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
    "dark":  ("#12141a", "#171a21", "#1d212a", "#e6e8ee", False),
    "light": ("#f6f7f9", "#ffffff", "#eceef2", "#1b1e26", True),
    "black": ("#000000", "#0a0a0a", "#121212", "#e6e8ee", False),
}


def make_theme(name, accent):
    background, surface, panel, foreground, light = GROUNDS[name]
    return Theme(name=f"sto-{name}", primary=accent, secondary=accent,
                 accent=accent, background=background, surface=surface,
                 panel=panel, foreground=foreground, dark=not light,
                 success="#4ade80", warning="#fbbf24", error="#f87171")

TABS = ["tab_home", "tab_sessions", "tab_memory", "tab_skills",
        "tab_config", "tab_help"]
HOME, SESSIONS, MEMORY, SKILLS, CONFIG, HELP = range(6)


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
    return Content.from_markup(
        f"[{colour}]{'█' * full}{tip}[/][$foreground 20%]{'█' * rest}[/]")


def ago(ts):
    return ui.ago(ts)


class Table(DataTable):
    """A `DataTable` that states its own column widths and keeps the last one
    filling whatever is left.

    Left to itself a `DataTable` sizes a column from its header label and never
    shrinks it, so a description column pushes the table wider than the card it
    sits in until the left-hand columns walk off the edge — and the width is not
    known at mount, only once the layout has run. Both problems belong to the
    table, not to five screens repeating the fix.
    """

    def __init__(self, *spec, **kw):
        super().__init__(cursor_type="row", **kw)
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
        cols[-1].width = max(8, self.size.width - fixed - pad * len(cols) - 1)
        self.refresh(layout=True)


def clip(text, n):
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


class Card(Container):
    """A titled panel. Every one of them is this widget, so they cannot drift
    apart in border, padding or title style — which is what made the hand-laid
    version look uneven."""

    def __init__(self, title, *children, upper=True, **kw):
        super().__init__(*children, classes="card", **kw)
        # section headings are shouted the way the prototype shouts them; a
        # document's own title is not a heading and keeps its capitals
        self.border_title = str(title).upper() if upper else str(title)


# ── the screens ──

# The wordmark, in figlet's `ansi_shadow` — solid blocks with the thin drawn
# edge down the right and the bottom, which is the face the prototype uses.
# Pasted rather than generated: it is six strings, and a whole dependency to
# produce six strings is a dependency to keep working forever. To change it:
#     uv run --no-project --with pyfiglet python -c
#       "import pyfiglet; print(pyfiglet.Figlet(font='ansi_shadow').renderText('STO'))"
WORDMARK = [
    "███████╗████████╗ ██████╗ ",
    "██╔════╝╚══██╔══╝██╔═══██╗",
    "███████╗   ██║   ██║   ██║",
    "╚════██║   ██║   ██║   ██║",
    "███████║   ██║   ╚██████╔╝",
    "╚══════╝   ╚═╝    ╚═════╝ ",
]
WORDMARK_W = len(WORDMARK[0]) + 12          # plus the name beside it


class Wordmark(Horizontal):
    """`braingent` beside `STO`, and not the whole name in blocks.

    The full name in this face is 103 columns of banner across the top of every
    home. The mark is the three letters; the name reads fine at text size next
    to them, and the screen underneath is the point of the screen.
    """

    def compose(self) -> ComposeResult:
        yield Static(Content.from_markup("[b]braingent[/]"), id="mark-name")
        block = "\n".join(f"[$accent]{line}[/]" for line in WORDMARK)
        yield Static(Content.from_markup(block), id="mark-block")


class Home(Grid):
    """Two columns, two rows, proportions stated in the stylesheet."""

    def compose(self) -> ComposeResult:
        yield Card(t("sec_sync"), Static(id="sync-body"))
        yield Card(t("sec_parity"), Table((t("sec_modules"), 16), (t("local"), 6), (t("in_repo"), 7),
                                     ("Δ L", 4), ("Δ R", 4), id="t-parity"))
        yield Card(t("sec_usage"), Static(id="usage-body"))
        yield Card(t("sec_general"), Static(id="overall-body"))

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        app = self.app
        sy = app.sync
        up, down = app.preview
        p = app.parity

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
                Content.from_markup(f"[$primary]{dr}[/]" if dr else "[$foreground 40%]·[/]"),
            )
        table.fit()

        synced = not (drift_l or drift_r or app.to_push or app.to_pull
                      or sy["ahead"] or sy["behind"])
        lines = []
        if synced:
            # "in sync" is not a percentage. A parity bar at 100 % answered a
            # question nobody asked and left the one that matters — is there
            # anything to do? — to be inferred from a full bar.
            lines.append(f"[$success]● {t('all_synced')}[/]")
        else:
            for arrow, n, parts, key in (("▲", app.to_push, ui.preview_parts(up), "to_push"),
                                         ("▼", app.to_pull, ui.preview_parts(down), "to_pull")):
                colour = "$accent" if n else "$foreground 50%"
                lines.append(f"[{colour}]{arrow} {n}[/]  [b]{t(key)}[/b]")
                lines += [f"    [$foreground 60%]{x}[/]"
                          for x in (parts or [t("nothing")])]
                lines.append("")
        lines += [
            f"[$foreground 60%]{t('last_sync'):<12}[/]{ui.last_sync()}",
            f"[$foreground 60%]{'git':<12}[/][$accent]↑{sy['ahead']} ↓{sy['behind']}[/]"
            f"[$foreground 40%] · [/]"
            + (f"[$warning]{t('dirty')}[/]" if sy["dirty"] else f"[$success]{t('clean')}[/]"),
            f"[$foreground 60%]{t('checked', ago=ui.checked_ago())}[/]",
        ]
        up_st = ui.update_state()
        if up_st.get("available"):
            lines.append(f"[$success]▲ {t('update_available')}: {up_st['available']}[/]")
        self.query_one("#sync-body", Static).update(
            Content.from_markup("\n".join(lines)))

        usage = []
        for lim in (app.usage.get("limits") or []):
            pct = lim.get("percent") or 0
            name = clip((lim.get("label") or lim.get("kind") or "?").replace("_", " "), 16)
            usage.append(Content.from_markup(
                f"[b]{name}[/b]  [$accent]{pct}%[/]"
                f"[$foreground 60%]   {ui._reset_at(lim.get('resetsAt'))}[/]"))
            usage.append(bar(pct, width=24))
            usage.append(Content(""))
        body = self.query_one("#usage-body", Static)
        body.update(Content("\n").join(usage) if usage
                    else Content.from_markup(f"[$foreground 60%]{t('no_usage')}[/]"))

        counters = "   ".join(f"[$accent b]{n}[/] [$foreground 60%]{t(k)}[/]"
                              for k, n in ui.counters())
        machines = " · ".join(
            name + (f" ({t('this_one')})" if d["local"] else "")
            for name, d in sorted(srv.list_machines().items()))
        always = " · ".join(f"{n} {t('n_' + k)}" for k, n in ui.knowledge_counts().items())
        self.query_one("#overall-body", Static).update(Content.from_markup(
            f"{counters}\n\n"
            f"[$foreground 60%]{t('sec_machines'):<16}[/]{machines}\n"
            f"[$foreground 60%]{t('sec_always'):<16}[/]{always}\n"
            f"[$foreground 60%]{'agent':<16}[/]{srv.agents.label()}"))


class Reader(Screen):
    """One document, scrolled. `Esc` goes back.

    A screen and not a panel: a transcript is hundreds of lines and squeezing it
    beside the list it came from gives two things too narrow to read. It carries
    the same top bar and the same footer as everything else — a screen you can
    reach and then cannot tell where you are is worse than no screen.
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
        # a screen binding shadows the app's. Reading a transcript with PUSH one
        # keystroke away is an accident waiting to happen, and hidden they also
        # stop being offered in the footer of a screen that cannot use them.
        *[Binding(k, "nothing", "", show=False) for k in "plfgr"],
    ]

    def action_nothing(self) -> None:
        pass

    def __init__(self, title, body):
        super().__init__()
        self._title, self._body = title, body

    def compose(self) -> ComposeResult:
        with Container(id="chrome"):
            yield Static(self.app.topbar_content(), id="topbar")
        with Container(id="reader"):
            with Card(self._title, upper=False):
                with VerticalScroll(id="doc-scroll"):
                    yield Static(self._body, markup=False, id="doc")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        # the scroll container has to hold focus or the arrows go nowhere: the
        # keys are bound to the screen, and the screen is not what scrolls
        self.query_one("#doc-scroll", VerticalScroll).focus()

    @property
    def doc(self):
        return self.query_one("#doc-scroll", VerticalScroll)

    def action_scroll(self, lines: int) -> None:
        self.doc.scroll_relative(y=lines, animate=False)

    def action_top(self) -> None:
        self.doc.scroll_home(animate=False)

    def action_bottom(self) -> None:
        self.doc.scroll_end(animate=False)


class Sessions(Container):
    def compose(self) -> ComposeResult:
        yield Card(t("tab_sessions"), Table((t("col_when"), 10), (t("col_project"), 20),
                                        (t("col_prompts"), 7), (t("col_tools"), 6),
                                        (t("col_title"), None), id="t-sessions"))
        yield Card(t("sec_detail"), Static(id="session-detail"))

    def on_mount(self) -> None:
        table = self.query_one("#t-sessions", Table)
        self.refresh_data()

    def refresh_data(self) -> None:
        rows, _ = cli.cached_sessions()
        self.rows = rows
        table = self.query_one("#t-sessions", Table)
        table.clear()
        for r in rows:
            table.add_row(ago(r["mtime"]), clip(r["project"], 22), str(r["n_prompts"]),
                          str(r["n_tools"]), clip(r["title"], 200), key=r["id"])
        table.fit()
        self.show(0)

    def show(self, index) -> None:
        if not self.rows:
            return
        r = self.rows[max(0, min(index, len(self.rows) - 1))]
        self.query_one("#session-detail", Static).update(Content.from_markup(
            f"[$foreground 60%]{t('col_project'):<10}[/][$accent]{r['project']}[/]\n"
            f"[$foreground 60%]{t('col_machine'):<10}[/]{r['machine'] or t('this_one')}\n"
            f"[$foreground 60%]{t('col_when'):<10}[/]{ago(r['mtime'])}\n\n"
            f"[$foreground 60%]{t('col_prompts'):<10}[/]{r['n_prompts']}\n"
            f"[$foreground 60%]{t('col_tools'):<10}[/]{r['n_tools']}\n"
            f"[$foreground 60%]{t('col_errors'):<10}[/]"
            + (f"[$error]{r['errors']}[/]" if r["errors"] else "0")
            + f"\n\n{clip(r['title'], 400)}"))

    def on_data_table_row_highlighted(self, event) -> None:
        self.show(event.cursor_row)

    def on_data_table_row_selected(self, event) -> None:
        self.open()          # a click on a row is the same as pressing it

    def open(self) -> None:
        table = self.query_one("#t-sessions", Table)
        if not self.rows:
            return
        r = self.rows[table.cursor_row]
        # `cli.timeline_lines` colours for the terminal TUI and puts newlines
        # inside some of its lines; both have to go before the text is handed to
        # a widget that does its own styling and its own wrapping.
        body = "\n".join(ui.strip_ansi(part)
                         for line in cli.timeline_lines(r)
                         for part in line.split("\n"))
        self.app.push_screen(Reader(clip(r["title"], 60), body))


class Memory(Container):
    def compose(self) -> ComposeResult:
        yield Card(t("n_projects"), ListView(id="projects"))
        yield Card(t("tab_memory"), Table((t("col_slug"), 28), (t("col_when"), 9),
                                      (t("col_machine"), 14), (t("col_desc"), None), id="t-memories"))

    def on_mount(self) -> None:
        table = self.query_one("#t-memories", Table)
        self.refresh_data()

    def refresh_data(self) -> None:
        self.groups = srv.list_memory()
        lv = self.query_one("#projects", ListView)
        lv.clear()
        for g in self.groups:
            lv.append(ListItem(Static(Content.from_markup(
                f"[$accent]{clip(g['project'], 22):<24}[/][$foreground 60%]{g['count']:>3}[/]"))))
        self.fill(0)

    def fill(self, index) -> None:
        table = self.query_one("#t-memories", Table)
        table.clear()
        if not self.groups:
            return
        g = self.groups[max(0, min(index, len(self.groups) - 1))]
        self.current = g
        for m in g["memories"]:
            table.add_row(clip(m["slug"], 30), ago(m["mtime"]),
                          clip(m["machine"], 16), clip(m["description"], 200))
        table.fit()

    def on_list_view_highlighted(self, event) -> None:
        if event.list_view.index is not None:
            self.fill(event.list_view.index)

    def on_list_view_selected(self, event) -> None:
        # clicking a project moves to its memories rather than opening one:
        # the project is a folder, and a folder opens into its contents
        self.query_one("#t-memories", Table).focus()

    def on_data_table_row_selected(self, event) -> None:
        self.open()

    def open(self) -> None:
        table = self.query_one("#t-memories", Table)
        if not getattr(self, "current", None) or not self.current["memories"]:
            return
        m = self.current["memories"][table.cursor_row]
        row = dict(m, project=self.current["project"])
        # `ui.detail_memory` already reads the file and appends the one level of
        # graph around it; re-reading it here would be a second answer to the
        # same question, and the two would drift.
        body = "\n".join(ui.strip_ansi(line) for line in ui.detail_memory(row))
        self.app.push_screen(Reader(f"{row['project']}/{m['slug']}", body))


class Skills(Container):
    """The skills and plugins of this machine and of the repo, side by side.

    This is the drill-down the terminal TUI does inside a config module, and it
    carries the same four states — the point of the screen is the ones that are
    only on one side.
    """

    def compose(self) -> ComposeResult:
        yield Card(t("tab_skills"), Table((t("col_name"), 34), (t("col_desc"), None), id="t-skills"))
        yield Card(t("sec_detail"), Static(id="skill-detail"))

    def on_mount(self) -> None:
        table = self.query_one("#t-skills", Table)
        self.refresh_data()

    def refresh_data(self) -> None:
        self.rows = ui.module_items("skills") + ui.module_items("plugins")
        table = self.query_one("#t-skills", Table)
        table.clear()
        for r in self.rows:
            mark, colour = {"local": (r"\[L]", "$warning"), "repo": (r"\[R]", "$success"),
                            "gone": (r"\[x]", "$error")}.get(r.get("where"),
                                                             (r"\[=]", "$foreground 40%"))
            table.add_row(Content.from_markup(f"[{colour}]{mark}[/] {clip(r['label'], 34)}"),
                          clip(r["desc"], 200))
        table.fit()
        self.show(0)

    def show(self, index) -> None:
        if not self.rows:
            return
        r = self.rows[max(0, min(index, len(self.rows) - 1))]
        state = {"local": "st_local", "repo": "st_repo",
                 "gone": "st_gone"}.get(r.get("where"), "st_both")
        self.query_one("#skill-detail", Static).update(Content.from_markup(
            f"[$accent b]{r['label']}[/]\n"
            f"[$foreground 60%]{r['what']} · {t(state)}[/]\n\n"
            f"{clip(r['desc'], 600)}"))

    def on_data_table_row_highlighted(self, event) -> None:
        self.show(event.cursor_row)

    def on_data_table_row_selected(self, event) -> None:
        self.open()

    def open(self) -> None:
        table = self.query_one("#t-skills", Table)
        if not self.rows:
            return
        r = self.rows[table.cursor_row]
        skill = srv.get_skill(r["id"]) if r["what"] == "skill" else None
        if skill is None:
            # a plugin has no SKILL.md to read, and neither does a skill the
            # repo has but this machine never installed
            self.app.notify(t("empty"))
            return
        self.app.push_screen(Reader(skill["name"], skill["content"]))


class Config(Container):
    def compose(self) -> ComposeResult:
        yield Card(t("tab_config"), Table(("", 26), ("", 14), ("", None), id="t-config", show_header=False))

    def on_mount(self) -> None:
        table = self.query_one("#t-config", Table)
        self.refresh_data()

    def refresh_data(self) -> None:
        table = self.query_one("#t-config", Table)
        keep = table.cursor_row
        table.clear()
        self.rows = []

        def head(key):
            self.rows.append(None)
            table.add_row(Content.from_markup(f"[$accent b]{t(key).upper()}[/]"), "", "")

        head("sec_prefs")
        # no swatch strip beside the name: six squares of which one meant
        # "current" was a legend nobody could read, and the row is already
        # painted in the colour it names
        self.rows.append(("accent", None))
        table.add_row(t("accent_color"), Content.from_markup(f"[$accent]{ui.accent_name()}[/]"),
                      Content.from_markup(f"[$foreground 60%]{t('k_change')}[/]"))
        ground = i18n.get_prefs().get("tui_ground", "dark")
        self.rows.append(("ground", None))
        table.add_row(t("tui_ground"), Content.from_markup(
            "  ".join(f"[$accent b]{t('ground_' + g)}[/]" if g == ground
                      else f"[$foreground 50%]{t('ground_' + g)}[/]" for g in GROUNDS)), "")
        self.rows.append(("lang", None))
        table.add_row(t("language"), Content.from_markup(
            "  ".join(f"[$accent b]{c}[/]" if c == i18n.LANG else f"[$foreground 50%]{c}[/]"
                      for c in i18n.LANGS)), "")
        on = srv.badge_status()["on"]
        self.rows.append(("badge", None))
        table.add_row(t("badge_row"),
                      Content.from_markup(f"[$accent]{BOX_ON if on else BOX_OFF}[/]"),
                      Content.from_markup(
                          f"[$foreground 60%]{t('badge_on') if on else t('badge_off')}[/]"))

        head("sec_always")
        for key, n in ui.knowledge_counts().items():
            self.rows.append(None)
            table.add_row(Content.from_markup(f"[$success]●[/] {t('n_' + key)}"), str(n),
                          Content.from_markup(f"[$foreground 60%]{t('always_syncing')}[/]"))

        head("sec_modules")
        for m in srv.config_status():
            self.rows.append(("module", m["id"]))
            table.add_row(
                m["id"],
                Content.from_markup(f"[$accent]{BOX_ON if m['enabled'] else BOX_OFF}[/]"),
                Content.from_markup(
                    f"[$foreground 60%]{t('syncing') if m['enabled'] else t('not_syncing')}"
                    f"   {m['localFiles']} {t('local')} · {m['repoFiles']} {t('in_repo')}[/]"))
        table.fit()
        if 0 <= keep < len(self.rows):
            table.move_cursor(row=keep)

    def on_data_table_row_selected(self, event) -> None:
        self.open()

    def open(self) -> None:
        """`↵` on the selected row. Headings and the always-synced rows are not
        actions, so landing on one does nothing rather than something odd."""
        table = self.query_one("#t-config", Table)
        row = self.rows[table.cursor_row] if table.cursor_row < len(self.rows) else None
        if row is None:
            return
        kind, arg = row
        if kind == "accent":
            codes = [c for _, c in ui.ACCENTS]
            ui.set_accent(codes[(codes.index(ui.ACCENT) + 1) % len(codes)])
            self.app.apply_theme()
        elif kind == "ground":
            names = list(GROUNDS)
            now = i18n.get_prefs().get("tui_ground", "dark")
            i18n.set_pref("tui_ground",
                          names[(names.index(now) + 1) % len(names)]
                          if now in names else "light")
            self.app.apply_theme()
        elif kind == "lang":
            ui.set_lang(i18n.LANGS[(i18n.LANGS.index(i18n.LANG) + 1) % len(i18n.LANGS)])
            self.app.notify(t("tab_config"))
        elif kind == "badge":
            srv.set_badge(not srv.badge_status()["on"])
        elif kind == "module":
            on = set(srv.get_sync_prefs())
            on.discard(arg) if arg in on else on.add(arg)
            srv.set_sync_prefs(sorted(on))
        self.refresh_data()


class Help(Container):
    def compose(self) -> ComposeResult:
        yield Card(t("sec_commands"), Table((t("sec_commands"), 34), ("", None), id="t-help", show_header=False))

    def on_mount(self) -> None:
        table = self.query_one("#t-help", Table)
        for usage, what in ui.commands():
            table.add_row(Content.from_markup(f"[$accent]{usage}[/]"),
                          Content.from_markup(f"[$foreground 60%]{what}[/]"))
        table.fit()


# ── the app ──

class StoApp(App):
    CSS_PATH = "tui_app.tcss"
    TITLE = "braingent STO"
    # the palette is the library's own screen, in the library's own idiom, and
    # it puts a button in our footer that leads out of the product
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("1", "tab(0)", "", show=False),
        Binding("2", "tab(1)", "", show=False),
        Binding("3", "tab(2)", "", show=False),
        Binding("4", "tab(3)", "", show=False),
        Binding("5", "tab(4)", "", show=False),
        Binding("6", "tab(5)", "", show=False),
        # priority: Tab is the library's focus-next by default, and it ate the
        # one key that is supposed to walk the tab bar everywhere
        Binding("tab", "next_tab", "", show=False, priority=True),
        Binding("shift+tab", "prev_tab", "", show=False, priority=True),
        Binding("enter", "open", "open", show=False, priority=True),
        Binding("p", "sync('push')", "PUSH"),
        Binding("l", "sync('pull')", "PULL"),
        Binding("f", "fetch", "FETCH"),
        Binding("g", "graph", "GRAPH"),
        Binding("r", "reload", "reload"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self):
        super().__init__()
        self.tab = HOME
        self.reload_data()

    # ── data ──

    def reload_data(self) -> None:
        """Everything the chrome and the home read, fetched once per refresh.

        The same functions `ui.py` calls: nothing here recomputes a rule, so
        the two flavours cannot disagree about a number.
        """
        self.sync = srv.sync_status(fetch=False)
        self.preview = ui.sync_preview(self.sync)
        self.parity = ui.parity()
        self.usage = srv.usage_snapshot(detail=False)
        self.to_push = ui.count_items(self.preview[0])
        self.to_pull = ui.count_items(self.preview[1])

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

    # ── chrome ──

    def topbar_content(self) -> Content:
        remote = (self.sync.get("remote") or "").replace("https://", "").removesuffix(".git")
        sep = "[$foreground 30%]  │  [/]"
        return Content.from_markup(
            f"[$accent b]braingent STO[/]{sep}"
            f"[$foreground 60%]repo [/]{remote}{sep}"
            f"[$foreground 60%]agent [/]{srv.agents.label()}{sep}"
            f"[$foreground 60%]{t('col_machine')} [/]{srv.LOCAL_MACHINE}")

    def paint_tabs(self) -> None:
        """The active tab is a filled rectangle in the accent colour, the way
        `sto ui` draws it — same product, same chip."""
        for i, chip in enumerate(self.query(".tab")):
            chip.set_class(i == self.tab, "on")

    def compose(self) -> ComposeResult:
        # one container docked to the top and not two widgets each docked to it:
        # docking is to an edge, so two of them land on the same row and the
        # second draws over the first
        with Container(id="chrome"):
            yield Static(self.topbar_content(), id="topbar")
            with Horizontal(id="tabs"):
                for i, key in enumerate(TABS):
                    yield Static(f" {t(key)} ", classes="tab", id=f"tab-{i}")
        yield Wordmark(id="wordmark")
        yield Home(id="home")
        yield Sessions(id="sessions", classes="split")
        yield Memory(id="memory", classes="split-even")
        yield Skills(id="skills", classes="split")
        yield Config(id="config", classes="one")
        yield Help(id="help", classes="one")
        yield Static("", id="status")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.apply_theme()
        self.query_one("#topbar", Static).update(self.topbar_content())
        self.show_tab(HOME)

    def apply_theme(self) -> None:
        """One accent, one ground, both ours.

        The accent comes from `sto ui` — the same setting drives both flavours,
        so they are the same product with the same colour. The ground is this
        flavour's own preference: a terminal TUI cannot ask the terminal what
        its background is, so which of the three it is has to be said.
        """
        accent = ACCENT_CSS.get(ui.ACCENT, "#22d3ee")
        ground = i18n.get_prefs().get("tui_ground", "dark")
        if ground not in GROUNDS:
            ground = "dark"
        self.register_theme(make_theme(ground, accent))
        self.theme = f"sto-{ground}"

    @property
    def panes(self):
        return [self.query_one("#home"), self.query_one("#sessions"),
                self.query_one("#memory"), self.query_one("#skills"),
                self.query_one("#config"), self.query_one("#help")]

    def show_tab(self, index) -> None:
        self.tab = index % len(TABS)
        # the banner belongs to the home and only when the terminal can spare
        # the rows: on a short window the table under it is worth more
        mark = self.query_one("#wordmark", Wordmark)
        mark.display = (self.tab == HOME and self.size.height >= 28
                        and self.size.width >= WORDMARK_W + 4)
        for i, pane in enumerate(self.panes):
            pane.display = i == self.tab
        self.paint_tabs()
        pane = self.panes[self.tab]
        focusable = pane.query(Table).first() if pane.query(Table) else None
        if focusable is not None:
            focusable.focus()

    # ── actions ──

    def action_tab(self, index: int) -> None:
        self.show_tab(index)

    def on_click(self, event) -> None:
        """A tab chip is a button. Nothing on this bar looked like it could be
        clicked and everything on it can be."""
        node = event.widget
        if node is not None and node.id and node.id.startswith("tab-"):
            self.show_tab(int(node.id.removeprefix("tab-")))

    def action_prev_tab(self) -> None:
        self.show_tab(self.tab - 1)

    def action_next_tab(self) -> None:
        # Tab always walks the tab bar. Letting it mean something else inside a
        # screen is how the one key that should mean the same thing everywhere
        # stops meaning it two screens in.
        self.show_tab(self.tab + 1)

    def action_open(self) -> None:
        pane = self.panes[self.tab]
        if hasattr(pane, "open"):
            pane.open()

    # ── the status strip ──

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def busy(self, message) -> None:
        """Say what is running, in the strip above the keys.

        `fetch`, `reload`, `push` and `pull` all go to the network or to git and
        all of them used to look like a key that did nothing until they were
        done. A spinner beside the sentence is the difference between "working"
        and "broken".
        """
        self._busy = message
        self._frame = 0
        self.query_one("#status", Static).update(Content.from_markup(
            f"[$accent]{self.SPINNER[0]}[/] [$foreground 70%]{message}[/]"))
        if getattr(self, "_spin", None) is None:
            self._spin = self.set_interval(0.08, self._tick)
        self.refresh()

    def _tick(self) -> None:
        self._frame += 1
        self.query_one("#status", Static).update(Content.from_markup(
            f"[$accent]{self.SPINNER[self._frame % len(self.SPINNER)]}[/]"
            f" [$foreground 70%]{self._busy}[/]"))

    def done(self, message="", error=False) -> None:
        if getattr(self, "_spin", None) is not None:
            self._spin.stop()
            self._spin = None
        colour = "$error" if error else "$success"
        mark = "✕" if error else "✓"
        self.query_one("#status", Static).update(
            Content.from_markup(f"[{colour}]{mark}[/] [$foreground 70%]{message}[/]")
            if message else Content(""))
        if message:
            # the strip is glanceable and the toast is unmissable; a push that
            # failed should not be a line you might have looked away from
            self.notify(message, severity="error" if error else "information")

    def action_reload(self) -> None:
        self.busy(t("k_reload"))
        self.reload_data()
        for pane in self.panes:
            if hasattr(pane, "refresh_data"):
                pane.refresh_data()
        self.query_one("#topbar", Static).update(self.topbar_content())
        self.done()

    def action_fetch(self) -> None:
        self.busy("FETCH")
        self.sync = srv.sync_status(fetch=True, force=True)
        self.action_reload()

    def action_graph(self) -> None:
        """The classic window. `cli.open_memory_graph` already knows how to
        build it and how to find a chrome-less browser, and its answer — the
        one that says what is missing when it fails — is what gets shown."""
        self.busy(t("graph_opening"))
        res = cli.open_memory_graph()
        self.done(res.get("error") or res.get("message") or "", bool(res.get("error")))

    def action_sync(self, what: str) -> None:
        self.busy(what.upper())
        fn = srv.sync_push if what == "push" else srv.sync_pull
        res = fn()
        self.done(res.get("error") or res.get("message") or "", bool(res.get("error")))
        self.action_reload()


def run():
    StoApp().run()


if __name__ == "__main__":
    run()
