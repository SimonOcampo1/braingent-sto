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
from textual.containers import Container, Grid, VerticalScroll  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.screen import Screen  # noqa: E402
from textual.widgets import (  # noqa: E402
    DataTable, Footer, ListItem, ListView, Static,
)

t = i18n.t

# The accent is a preference of the whole OS, stored as an SGR code; Textual
# wants a colour it can put in a stylesheet.
ACCENT_CSS = {"36": "cyan", "32": "green", "35": "magenta",
              "34": "dodgerblue", "33": "orange", "31": "tomato"}

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
    tip = eighths[int((exact - full) * 8)]
    colour = "$error" if (pct or 0) >= warn else "$accent"
    rest = max(0, width - full - (1 if tip.strip() else 0))
    return Content.from_markup(
        f"[{colour}]{'█' * full}{tip}[/][$foreground 20%]{'█' * rest}[/]")


def ago(ts):
    return ui.ago(ts)


def clip(text, n):
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


class Card(Container):
    """A titled panel. Every one of them is this widget, so they cannot drift
    apart in border, padding or title style — which is what made the hand-laid
    version look uneven."""

    def __init__(self, title, *children, **kw):
        super().__init__(*children, classes="card", **kw)
        self.border_title = title


# ── the screens ──

class Home(Grid):
    """Two columns, two rows, proportions stated in the stylesheet."""

    def compose(self) -> ComposeResult:
        yield Card(t("sec_sync"), Static(id="sync-body"))
        yield Card(t("sec_parity"), DataTable(id="parity", cursor_type="row"))
        yield Card(t("sec_usage"), Static(id="usage-body"))
        yield Card(t("sec_general"), Static(id="overall-body"))

    def on_mount(self) -> None:
        table = self.query_one("#parity", DataTable)
        table.add_columns("", t("local"), t("in_repo"), "Δ L", "Δ R")
        self.refresh_data()

    def refresh_data(self) -> None:
        app = self.app
        sy = app.sync
        up, down = app.preview
        p = app.parity

        drift_l = drift_r = 0
        table = self.query_one("#parity", DataTable)
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

    A screen and not a panel: a transcript is hundreds of lines and squeezing
    it beside the list it came from gives two things too narrow to read.
    """
    BINDINGS = [Binding("escape,q", "app.pop_screen", "back", show=True)]

    def __init__(self, title, body):
        super().__init__()
        self._title, self._body = title, body

    def compose(self) -> ComposeResult:
        yield Static(self.app.topbar_content(), id="topbar")
        with Container(id="reader"):
            with Card(self._title):
                with VerticalScroll():
                    yield Static(self._body, markup=False, id="doc")
        yield Footer()


class Sessions(Container):
    def compose(self) -> ComposeResult:
        yield Card(t("tab_sessions"), DataTable(id="sessions", cursor_type="row"))
        yield Card(t("sec_detail"), Static(id="session-detail"))

    def on_mount(self) -> None:
        table = self.query_one("#sessions", DataTable)
        table.add_columns(t("col_when"), t("col_project"), t("col_prompts"),
                          t("col_tools"), t("col_title"))
        self.refresh_data()

    def refresh_data(self) -> None:
        rows, _ = cli.cached_sessions()
        self.rows = rows
        table = self.query_one("#sessions", DataTable)
        table.clear()
        for r in rows:
            table.add_row(ago(r["mtime"]), clip(r["project"], 22), str(r["n_prompts"]),
                          str(r["n_tools"]), clip(r["title"], 90), key=r["id"])
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

    def open(self) -> None:
        table = self.query_one("#sessions", DataTable)
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
        yield Card(t("tab_memory"), DataTable(id="memories", cursor_type="row"))

    def on_mount(self) -> None:
        table = self.query_one("#memories", DataTable)
        table.add_columns(t("col_slug"), t("col_when"), t("col_machine"), t("col_desc"))
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
        table = self.query_one("#memories", DataTable)
        table.clear()
        if not self.groups:
            return
        g = self.groups[max(0, min(index, len(self.groups) - 1))]
        self.current = g
        for m in g["memories"]:
            table.add_row(clip(m["slug"], 30), ago(m["mtime"]),
                          clip(m["machine"], 16), clip(m["description"], 120))

    def on_list_view_highlighted(self, event) -> None:
        if event.list_view.index is not None:
            self.fill(event.list_view.index)

    def open(self) -> None:
        table = self.query_one("#memories", DataTable)
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
        yield Card(t("tab_skills"), DataTable(id="skills", cursor_type="row"))
        yield Card(t("sec_detail"), Static(id="skill-detail"))

    def on_mount(self) -> None:
        table = self.query_one("#skills", DataTable)
        table.add_columns("", t("col_slug"), t("col_desc"))
        self.refresh_data()

    def refresh_data(self) -> None:
        self.rows = ui.module_items("skills") + ui.module_items("plugins")
        table = self.query_one("#skills", DataTable)
        table.clear()
        for r in self.rows:
            mark, colour = {"local": ("[L]", "$warning"), "repo": ("[R]", "$success"),
                            "gone": ("[x]", "$error")}.get(r.get("where"),
                                                           ("[=]", "$foreground 40%"))
            table.add_row(Content.from_markup(f"[{colour}]{mark}[/]"),
                          clip(r["label"], 34), clip(r["desc"], 120))
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

    def open(self) -> None:
        table = self.query_one("#skills", DataTable)
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
        yield Card(t("tab_config"), DataTable(id="config", cursor_type="row"))

    def on_mount(self) -> None:
        table = self.query_one("#config", DataTable)
        table.add_columns("", "", "")
        self.refresh_data()

    def refresh_data(self) -> None:
        table = self.query_one("#config", DataTable)
        keep = table.cursor_row
        table.clear()
        self.rows = []

        def head(key):
            self.rows.append(None)
            table.add_row(Content.from_markup(f"[$accent b]{t(key).upper()}[/]"), "", "")

        head("sec_prefs")
        swatch = " ".join(
            f"[{ACCENT_CSS.get(code, 'white')}]{'██' if code == ui.ACCENT else '──'}[/]"
            for _, code in ui.ACCENTS)
        self.rows.append(("accent", None))
        table.add_row(t("accent_color"), Content.from_markup(f"[$accent]{ui.accent_name()}[/]"),
                      Content.from_markup(swatch))
        self.rows.append(("lang", None))
        table.add_row(t("language"), Content.from_markup(
            "  ".join(f"[$accent b]{c}[/]" if c == i18n.LANG else f"[$foreground 50%]{c}[/]"
                      for c in i18n.LANGS)), "")
        on = srv.badge_status()["on"]
        self.rows.append(("badge", None))
        table.add_row(t("badge_row"),
                      Content.from_markup(f"[$accent]{'[x]' if on else '[ ]'}[/]"),
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
                Content.from_markup(f"[$accent]{'[x]' if m['enabled'] else '[ ]'}[/]"),
                Content.from_markup(
                    f"[$foreground 60%]{t('syncing') if m['enabled'] else t('not_syncing')}"
                    f"   {m['localFiles']} {t('local')} · {m['repoFiles']} {t('in_repo')}[/]"))
        if 0 <= keep < len(self.rows):
            table.move_cursor(row=keep)

    def open(self) -> None:
        """`↵` on the selected row. Headings and the always-synced rows are not
        actions, so landing on one does nothing rather than something odd."""
        table = self.query_one("#config", DataTable)
        row = self.rows[table.cursor_row] if table.cursor_row < len(self.rows) else None
        if row is None:
            return
        kind, arg = row
        if kind == "accent":
            codes = [c for _, c in ui.ACCENTS]
            ui.set_accent(codes[(codes.index(ui.ACCENT) + 1) % len(codes)])
            self.app.apply_accent()
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
        yield Card(t("sec_commands"), DataTable(id="help", cursor_type="row"))

    def on_mount(self) -> None:
        table = self.query_one("#help", DataTable)
        table.add_columns(t("sec_commands"), "")
        for usage, what in ui.commands():
            table.add_row(Content.from_markup(f"[$accent]{usage}[/]"),
                          Content.from_markup(f"[$foreground 60%]{what}[/]"))


# ── the app ──

class StoApp(App):
    CSS_PATH = "tui_app.tcss"
    TITLE = "braingent STO"
    BINDINGS = [
        Binding("1", "tab(0)", "", show=False),
        Binding("2", "tab(1)", "", show=False),
        Binding("3", "tab(2)", "", show=False),
        Binding("4", "tab(3)", "", show=False),
        Binding("5", "tab(4)", "", show=False),
        Binding("6", "tab(5)", "", show=False),
        Binding("tab", "next_tab", "", show=False),
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

    def tabbar_content(self) -> Content:
        out = []
        for i, key in enumerate(TABS):
            on = i == self.tab
            cap = f"[$accent on $background b]" if on else "[$background on $foreground b]"
            colour = "[$accent b]" if on else "[$foreground 50%]"
            out.append(f"{cap} {i + 1} [/]{colour} {t(key)}[/]")
        return Content.from_markup("   ".join(out))

    def compose(self) -> ComposeResult:
        yield Static(self.topbar_content(), id="topbar")
        yield Static(self.tabbar_content(), id="tabs")
        yield Home(id="home")
        yield Sessions(id="sessions", classes="split")
        yield Memory(id="memory", classes="split-even")
        yield Skills(id="skills", classes="split")
        yield Config(id="config", classes="one")
        yield Help(id="help", classes="one")
        yield Footer()

    def on_mount(self) -> None:
        self.apply_accent()
        self.show_tab(HOME)

    def apply_accent(self) -> None:
        """The accent picked in `sto ui` drives the whole stylesheet, so the two
        flavours look like the same product with the same setting."""
        self.theme_variables["accent"] = ACCENT_CSS.get(ui.ACCENT, "cyan")
        self.refresh_css()

    @property
    def panes(self):
        return [self.query_one("#home"), self.query_one("#sessions"),
                self.query_one("#memory"), self.query_one("#skills"),
                self.query_one("#config"), self.query_one("#help")]

    def show_tab(self, index) -> None:
        self.tab = index % len(TABS)
        for i, pane in enumerate(self.panes):
            pane.display = i == self.tab
        self.query_one("#tabs", Static).update(self.tabbar_content())
        pane = self.panes[self.tab]
        focusable = pane.query(DataTable).first() if pane.query(DataTable) else None
        if focusable is not None:
            focusable.focus()

    # ── actions ──

    def action_tab(self, index: int) -> None:
        self.show_tab(index)

    def action_next_tab(self) -> None:
        # Tab always walks the tab bar. Letting it mean something else inside a
        # screen is how the one key that should mean the same thing everywhere
        # stops meaning it two screens in.
        self.show_tab(self.tab + 1)

    def action_open(self) -> None:
        pane = self.panes[self.tab]
        if hasattr(pane, "open"):
            pane.open()

    def action_reload(self) -> None:
        self.reload_data()
        for pane in self.panes:
            if hasattr(pane, "refresh_data"):
                pane.refresh_data()
        self.query_one("#topbar", Static).update(self.topbar_content())

    def action_fetch(self) -> None:
        self.sync = srv.sync_status(fetch=True, force=True)
        self.action_reload()

    def action_graph(self) -> None:
        """The classic window. `cli.open_memory_graph` already knows how to
        build it and how to find a chrome-less browser, and its answer — the
        one that says what is missing when it fails — is what gets shown."""
        self.notify(t("graph_opening"))
        res = cli.open_memory_graph()
        self.notify(res.get("error") or res.get("message") or "",
                    severity="error" if res.get("error") else "information")

    def action_sync(self, what: str) -> None:
        fn = srv.sync_push if what == "push" else srv.sync_pull
        res = fn()
        self.notify(res.get("error") or res.get("message") or "",
                    severity="error" if res.get("error") else "information")
        self.action_reload()


def run():
    StoApp().run()


if __name__ == "__main__":
    run()
