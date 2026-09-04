"""The Textual flavour, rendered headless.

It skips itself when `textual` is not installed, so `python test_tui_app.py`
stays runnable next to the other four suites on a machine that never opted into
the flavour. Run it with the library on:

    uv run --no-project --with textual python scripts/test_tui_app.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import textual  # noqa: F401
except ImportError:
    print("OK (textual not installed — skipped)")
    raise SystemExit(0)

import tui_app  # noqa: E402
import tui_widgets  # noqa: E402
from textual.widgets import Markdown  # noqa: E402


def screen_text(app):
    return [strip.text for strip in app.screen._compositor.render_strips()]


async def on_kind(app, pilot, kind="skills"):
    """Put the Tools cursor on one kind and hand back that pane.

    The tab used to be skills and nothing else; now the rows are whichever kind
    you are standing on, so a test about the row list has to say which.
    """
    await pilot.press("4")
    await pilot.pause()
    pane = app.query_one("#tools")
    kinds = pane.query_one("#t-kinds", tui_app.Table)
    kinds.move_cursor(row=pane.modules.index(kind))
    pane.fill()
    await pilot.pause()
    return pane


def test_the_wordmark_is_a_rectangle():
    """Pasted art goes crooked the moment somebody edits one line of it.

    Every row has to be the same width or the block leans, and it has to stay
    small: the same name in the face of the prototype is 103 columns of banner
    across the top of every home, which is most of the screen spent saying what
    the screen already is.
    """
    rows = tui_app.WORDMARK
    assert len({len(r) for r in rows}) == 1, [len(r) for r in rows]
    assert len(rows) == 2, len(rows)          # one line, two rows of blocks
    assert len(rows[0]) < 60, len(rows[0])


def test_the_accent_and_the_ground_are_one_theme_each():
    """Textual repaints when the *name* of the theme changes, so a theme
    re-registered under the same name with a new accent left the old colours on
    screen. Every pair is its own name."""
    a = tui_app.theme_for("dark", "36")
    b = tui_app.theme_for("dark", "31")
    c = tui_app.theme_for("light", "36")
    assert len({a.name, b.name, c.name}) == 3, (a.name, b.name, c.name)
    assert a.background != c.background


def test_a_screen_renders_with_its_chrome_pinned():
    """The header, the tab bar and the footer are on screen at every height.

    They are the three things that must not scroll away, and the way that is
    arranged — one container docked top, `Footer` docked bottom — is exactly
    the kind of thing that keeps working in code and stops working on screen.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 28)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            lines = screen_text(app)
            assert "braingent STO" in lines[0], lines[0]
            assert "Home" in lines[1] and "Config" in lines[1], lines[1]
            assert "PUSH" in lines[-1], lines[-1]
            # the library's own way out of the product is not in our footer
            assert "palette" not in lines[-1], lines[-1]

            for key in "23456":
                await pilot.press(key)
                await pilot.pause()
                painted = screen_text(app)
                assert "braingent STO" in painted[0], key
                assert "PUSH" in painted[-1], key

    asyncio.run(go())


def test_a_document_has_its_own_keys():
    """A reader shadows the keys that act on the repo: reading a transcript
    with PUSH one keystroke away is an accident, and hiding them also stops the
    footer offering keys the screen cannot use.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("enter")        # the project hands over its rows
            await pilot.pause()
            await pilot.press("enter")        # open one
            await pilot.pause()
            foot = screen_text(app)[-1]
            assert "back" in foot and "PUSH" not in foot, foot
            doc = app.screen.query_one("#doc-scroll")
            await pilot.press("pagedown")
            await pilot.pause()
            assert doc.scroll_offset.y > 0, "the document did not scroll"
            await pilot.press("escape")
            await pilot.pause()
            assert app.tab == 1, app.tab

    asyncio.run(go())


def test_focus_starts_on_the_left_and_a_project_hands_it_to_the_right():
    """You pick the project before you read what is in it, so that is the order
    the focus goes in — and both lists are tables so they highlight, hover and
    take focus the same way."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("3")            # memories
            await pilot.pause()
            pane = app.query_one("#memory")
            groups = pane.query_one("#t-groups", tui_app.Table)
            rows = pane.query_one("#t-rows", tui_app.Table)
            assert groups.has_focus, "focus did not start on the projects"
            await pilot.press("enter")
            await pilot.pause()
            assert rows.has_focus, "a project did not hand focus to its rows"

    asyncio.run(go())


def test_the_last_column_takes_the_width_the_others_leave():
    """A `DataTable` sizes a column from its header and never shrinks it, so
    without this the description column pushes the table wider than its card
    and the left-hand columns walk off the edge."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            pane = await on_kind(app, pilot)  # skills: name + description
            await pilot.pause()
            table = pane.query_one("#t-rows", tui_app.Table)
            widths = [c.width for c in table.columns.values()]
            assert widths[0] == 34, widths
            assert widths[-1] > 20, widths
            assert sum(widths) <= table.size.width, (widths, table.size.width)

    asyncio.run(go())


def test_the_search_box_is_on_screen_and_narrows_the_list():
    """It used to be summoned with `/` and docked at the foot. A box you cannot
    see is a feature nobody finds, and one under the rows it filters is one you
    cannot watch them narrow into."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(130, 30)) as pilot:
            pane = await on_kind(app, pilot)
            box = pane.query_one("#search", tui_app.Search)
            assert box.display, "the search box is not on screen"
            before = len(pane.rows)
            box.focus()
            for ch in "caveman":
                await pilot.press(ch)
            await pilot.pause()
            assert 0 < len(pane.rows) < before, (before, len(pane.rows))

    asyncio.run(go())


def test_nothing_that_writes_runs_before_the_manifest_is_on_screen():
    """PUSH and the three skill verbs all go through the same confirmation.

    They are the same question, and four differently worded boxes for it is
    four chances to phrase the dangerous one gently.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(130, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert type(app.screen).__name__ == "Confirm", app.screen
            await pilot.press("escape")
            await pilot.pause()

            pane = await on_kind(app, pilot)
            pane.query_one("#t-rows", tui_app.Table).focus()
            await pilot.pause()
            await pilot.press("d")            # delete this skill from here
            await pilot.pause()
            assert type(app.screen).__name__ == "Confirm", app.screen
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ == "Screen"

    asyncio.run(go())


def test_a_transcript_is_a_conversation_of_blocks():
    """One block per turn, so a wrapped paragraph keeps the indent of whoever
    is saying it — and the gutter that says who survives the wrap. One long
    string could do neither."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            rows = app.query_one("#sessions").rows
            if not rows:
                return                        # a machine with no sessions yet
            blocks = tui_app.transcript(rows[0])
            kinds = {css for css, _ in blocks}
            assert any(k.startswith("who") for k in kinds), kinds
            assert all(isinstance(text, str) for _, text in blocks)

    asyncio.run(go())


def test_only_the_bracket_is_escaped():
    r"""Doubling backslashes as well — the Rich habit — put every Windows path
    in a transcript on screen as `C:\\Users\\...`. Only `[` opens a tag."""
    assert tui_app.esc(r"C:\Users\Simon") == r"C:\Users\Simon"
    assert tui_app.esc("a [b] c") == r"a \[b] c"


def test_the_home_does_not_pay_for_ccusage_before_it_paints():
    """`usage_snapshot(detail=True)` shells out to `npx ccusage` twice — twenty
    seconds cold — and the only thing on the home that reads the detail is the
    spend sparkline. The percentages are one https call.

    Asking for both in the phase that paints the screen is what made opening
    the app feel broken, and it is a regression the stdlib flavour already fell
    into once, so this asserts against it by name and not by timing.
    """
    calls = []
    real_usage, real_update = tui_app.srv.usage_snapshot, tui_app.ui.update_state

    def fake_usage(detail=True):
        calls.append(detail)
        return {"limits": [], "daily": []}

    tui_app.srv.usage_snapshot = fake_usage
    tui_app.ui.update_state = lambda force=False: {"available": 0}
    try:
        app = tui_app.StoApp()
        app.load_fast()
        assert calls == [False], calls
        app.load_slow()
        assert calls == [False, True], calls
    finally:
        tui_app.srv.usage_snapshot = real_usage
        tui_app.ui.update_state = real_update


def test_a_count_nobody_has_run_yet_is_not_a_zero():
    """`0 to push` and `not counted yet` are different answers, and the home
    painted the first while it meant the second — which reads as "nothing to
    sync" for as long as the phase takes."""
    app = tui_app.StoApp()
    assert app.counted is False
    app.load_counts()
    assert app.counted is True

    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            if not app.sync.get("remote"):
                return                    # no remote: every number is moot
            app.counted = False
            app.query_one("#home").refresh_data()
            await pilot.pause()
            body = "\n".join(screen_text(app))
            assert "\u00b7\u00b7\u00b7" in body, body

    asyncio.run(go())


def test_a_pane_off_screen_is_rebuilt_when_you_reach_it_and_not_before():
    """Rebuilding all six panes costs most of a second on the UI thread, and
    the load repaints three times now instead of once. Only what is on screen
    is rebuilt; the rest carry a mark and catch up in `show_tab`."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert tui_app.SESSIONS in app._stale, app._stale
            await pilot.press("2")
            await pilot.pause()
            assert tui_app.SESSIONS not in app._stale, app._stale

    asyncio.run(go())


def test_the_wordmark_goes_when_it_does_not_fit_and_not_before():
    """It is 51 columns and two rows, and it was hidden below 100 — at 70 it
    fits with nineteen to spare.

    What was actually broken at 70 was everything under it being pushed off
    the screen, which is a different bug with a different fix. Width and height
    get their own breakpoints so the banner answers for its own size.
    """
    async def go():
        for size, want in (((70, 30), True), ((50, 30), False), ((120, 20), False)):
            app = tui_app.StoApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                mark = app.query_one("#wordmark")
                assert mark.display is want, (size, mark.display, want)

    asyncio.run(go())


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


def test_a_narrow_split_shows_one_level_and_walks_between_them():
    """Picking a project and reading what it holds is a hierarchy, and in one
    column a hierarchy is one panel at a time.

    The level is state on the pane, not a screen stack: the widgets stay
    mounted, so coming back is coming back to where you were.
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
            assert app.query_one("#rows").display, "the session list is not on screen"
            assert not app.query_one("#groups").display

            await pilot.press("escape")           # back out
            await pilot.pause()
            assert pane.level == 0, pane.level
            assert app.query_one("#groups").display
            assert groups.cursor_row == picked, (groups.cursor_row, picked)

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
            assert app.query_one("#t-rows", tui_app.Table).has_focus

    asyncio.run(go())


def test_tab_walks_panels_and_the_tab_bar_is_somewhere_you_can_stand():
    """`Tab` used to cycle the six tabs, which left nothing for the panels
    inside one — so half the interface could only be reached with a mouse.

    Now it walks the panels of the pane you are on and wraps through the tab
    bar, which is focusable: standing there the arrows change tab and `↓` drops
    back into the content. `1`-`6` still jump directly, from anywhere.
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
                assert app.tab == 1, "tab changed the pestana, not the panel"
                if app.focused is not None:
                    seen.add(app.focused.id)
            assert {"t-groups", "t-rows"} <= seen, seen
            assert "tabs" in seen, seen

            app.query_one("#tabs").focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            assert app.tab == 2, app.tab
            await pilot.press("left")
            await pilot.pause()
            assert app.tab == 1, app.tab
            await pilot.press("down")
            await pilot.pause()
            assert app.focused is not None and app.focused.id != "tabs"

            # `↓` lands on the first panel, which is the search box, and there
            # a digit is a digit — that is what the box is for. `↑` is the way
            # back out of it, and one `Tab` is the way on to the list
            assert app.focused.id == "search", app.focused.id
            await pilot.press("5")
            await pilot.pause()
            assert app.tab == 1, "a digit typed in the search box changed tab"
            app.query_one("#sessions").query_one("#search").value = ""

            await pilot.press("tab")
            await pilot.pause()
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
            for _ in range(2):
                await pilot.press("up")
                await pilot.pause()
            assert table.cursor_row == 0, table.cursor_row
            await pilot.press("up")
            await pilot.pause()
            assert app.focused is app.query_one("#tabs"), app.focused

    asyncio.run(go())


def test_s_cycles_the_sort_and_comes_back_to_the_natural_order():
    """One key with the semantics of a header click: the next sortable column
    ascending, or the same column reversed if you are already on it.

    Past the last one the cycle ends at `None`, which is the order the pane
    wrote — these lists are newest-first, which is what you want almost always
    — so `s` can never strand you in a sort you cannot leave.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            table = app.query_one("#t-rows", tui_app.Table)
            table.focus()
            await pilot.pause()
            if table.row_count < 3:
                return                      # a machine with almost no sessions
            pane = app.query_one("#sessions")
            natural = [r["id"] for r in pane.rows]

            await pilot.press("s")
            await pilot.pause()
            assert table.sort_by is not None, "s did not sort"
            col, reverse = table.sort_by
            assert reverse is False, table.sort_by
            # the rows, not the cells: a cell is a rendering and `5 d` sorted
            # as text puts weeks among hours
            field = pane.SORT_FIELDS[col]
            up = [r[field] for r in pane.rows]
            assert up == sorted(up), up

            await pilot.press("s")
            await pilot.pause()
            assert table.sort_by == (col, True), table.sort_by
            down = [r[field] for r in pane.rows]
            assert down == sorted(up, reverse=True), (up, down)

            for _ in range(20):
                await pilot.press("s")
                await pilot.pause()
                if table.sort_by is None:
                    break
            assert table.sort_by is None, "the cycle never returned to unsorted"
            assert [r["id"] for r in pane.rows] == natural, \
                "unsorted is not the order the pane wrote"

    asyncio.run(go())


def test_a_column_sorts_the_datum_and_not_the_cell():
    """`when` renders `2 h`, `5 d`, `3 w` and `errors` renders markup. Sorted
    as text the first interleaves hours with weeks and the second is not
    comparable at all -- so both sort the row behind the cell.

    Leaving them out of the cycle was the first answer and it was wrong: they
    are exactly the columns somebody wants sorted.
    """
    table = tui_app.Table((tui_app.t("col_when"), 10, "data"),
                          (tui_app.t("col_project"), 18, "data"),
                          ("", 7))
    assert table.sortable == [0, 1], table.sortable

    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(150, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            pane = app.query_one("#sessions")
            if len(pane.rows) < 3:
                return
            rows = pane.query_one("#t-rows", tui_app.Table)
            rows.focus()
            await pilot.pause()

            # `when` is column 0 and the first step of the cycle
            await pilot.press("s")
            await pilot.pause()
            assert rows.sort_by == (0, False), rows.sort_by
            stamps = [r["mtime"] for r in pane.rows]
            assert stamps == sorted(stamps), "when did not sort by time"

            # walk to `errors` and check it sorts by the count, not the markup
            while rows.sort_by is not None and rows.sort_by[0] != 4:
                await pilot.press("s")
                await pilot.pause()
            assert rows.sort_by is not None, "errors never came up in the cycle"
            counts = [r["errors"] for r in pane.rows]
            assert counts == sorted(counts), counts

    asyncio.run(go())


def test_the_marquee_runs_only_where_text_is_cut_and_only_with_focus():
    """The selected row scrolls what its column cut off — that row and no
    other, and only while the table has the keys.

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
            await pilot.pause()
            table = app.query_one("#t-rows", tui_app.Table)
            if table.row_count == 0:
                return
            table.focus()
            table.move_cursor(row=0)
            await pilot.pause()
            assert table.raw, "no raw cell text was kept"

            widths = [c.get_render_width(table) for c in table.columns.values()]
            cut = any(len(v) > widths[c] for (r, c), v in table.raw.items()
                      if r == 0 and c < len(widths))
            assert (table._marquee is not None) is cut, (cut, table._marquee)

            app.query_one("#tabs").focus()
            await pilot.pause()
            assert table._marquee is None, "the marquee outlived the focus"

    asyncio.run(go())


def test_a_memory_renders_as_markdown_and_a_transcript_does_not():
    """A memory and a SKILL.md are documents; `**bold**` on screen as four
    asterisks is the reader failing at its one job.

    A transcript is not a document, it is a conversation, and its own renderer
    -- who spoke with their gutter, code on the panel, tools in amber --
    carries what markdown cannot. That one keeps its blocks.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.push_screen(tui_app.Reader("note", "# Title\n\n**bold** text",
                                           markdown=True))
            await pilot.pause()
            assert app.screen.query(Markdown), "the document is not markdown"
            painted = "\n".join(screen_text(app))
            assert "**bold**" not in painted, painted
            await pilot.press("escape")
            await pilot.pause()

            app.push_screen(tui_app.Reader("plain", [("user", "hello")]))
            await pilot.pause()
            assert not app.screen.query(Markdown), "a transcript went to markdown"

    asyncio.run(go())


def test_tools_reaches_every_config_module_and_reads_one():
    """The tab used to be skills only, so `settings.json` and `CLAUDE.md` --
    which sync carries and the parity table counts -- could be seen as a number
    and never as a file.

    The kinds come from `CONFIG_MODULES` itself, so the tab cannot drift from
    what push actually moves.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(150, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("4")
            await pilot.pause()
            pane = app.query_one("#tools")
            assert pane.modules == list(tui_app.srv.CONFIG_MODULES), pane.modules

            pane = await on_kind(app, pilot, "claude-md")
            assert pane.rows, "claude-md listed nothing"
            assert pane.content(pane.rows[0]) is not None, "the file did not read"

            # a plugin is a manifest entry with no document behind it, and that
            # is an answer rather than a crash
            plugins = tui_app.ui.module_items("plugins")
            if plugins:
                assert pane.content(plugins[0]) is None, plugins[0]

    asyncio.run(go())


def test_the_home_search_finds_things_that_are_not_sessions():
    """The box on the home used to hand its text to the Sessions tab, which
    made it a worse copy of the box already on that screen. It searches every
    corpus now, and each row says which one it came from."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            home = app.query_one("#home")
            assert not app.query_one("#results").display, "results before a query"

            box = home.query_one("#search", tui_app.Search)
            box.focus()
            for ch in "claude":
                await pilot.press(ch)
            await pilot.pause(0.4)          # past the debounce
            assert app.tab == tui_app.HOME, "the home handed the query away"
            assert app.query_one("#results").display, "no results panel"
            assert home.hits, "nothing found for a word this repo is full of"
            assert {h["kind"] for h in home.hits} <= {"session", "memory",
                                                      "tool", "note"}
            assert not app.query_one("#home-grid").display, "the dashboard stayed"

            await pilot.press("escape")
            await pilot.pause()
            assert not app.query_one("#results").display, "escape left it open"
            assert app.query_one("#home-grid").display, "the dashboard did not return"

    asyncio.run(go())


def test_a_memory_shows_its_body_and_its_neighbours():
    """A memory opened blank: only its links, no text.

    `#reader` was a grid whose first row was `1fr` and whose second was `auto`,
    and a `1fr` card inside an `auto` row resolves to its own natural height --
    so the neighbours strip took the screen and the document was laid out at
    zero. `enter` on one of those links opened the next memory just as blank,
    which is what read as a loop.

    Sessions and skills were never affected: they have no neighbours, so the
    strip is never composed and the document is the only child. That is why
    this asserts on the one shape that has both.
    """
    async def go():
        real_list = tui_app.srv.list_memory
        real_nb = tui_app.srv.memory_neighbours
        real_detail = tui_app.ui.detail_memory
        tui_app.srv.list_memory = lambda *a, **k: [
            {"project": "demo", "machines": ["BoxA"], "count": 1,
             "memories": [{"slug": "una", "type": "project", "machine": "BoxA",
                           "mtime": 1.0, "description": "d"}]}]
        tui_app.srv.memory_neighbours = lambda p, s: (["demo/otra"], ["demo/cita"])
        tui_app.ui.detail_memory = lambda row: ["# una memoria", "",
                                                "el cuerpo que se tiene que ver"]
        try:
            app = tui_app.StoApp()
            async with app.run_test(size=(96, 26)) as pilot:
                await app.workers.wait_for_complete()
                app.open_memory("demo", "una", "BoxA")
                await pilot.pause()
                await pilot.pause()
                doc = app.screen.query_one("#doc-scroll")
                links = app.screen.query_one("#links")
                assert doc.size.height > 3, (doc.size, "the document has no room")
                assert links.size.height > 3, (links.size, "the neighbours vanished")
                painted = "\n".join(screen_text(app))
                assert "el cuerpo que se tiene que ver" in painted, painted
                assert "demo/otra" in painted and "demo/cita" in painted, painted
        finally:
            tui_app.srv.list_memory = real_list
            tui_app.srv.memory_neighbours = real_nb
            tui_app.ui.detail_memory = real_detail

    asyncio.run(go())


def test_a_coloured_cell_scrolls_too():
    """The marquee skipped every cell that carried colour.

    The machines columns are exactly that -- the local one in the accent, the
    rest dim -- so the one place you most need to read a list that does not fit
    was the one place nothing moved. `Content` slices and carries its spans
    across, so it scrolls with its colours rather than being left out or
    flattened to plain text.

    The other half was `clip(machine, 12)` into a column twelve wide: a cell
    pre-cut to its own column can never be found to overflow.
    """
    async def go():
        real = tui_app.cli.cached_sessions
        names = ["MaquinaDeEscritorioLarga", "LaptopDelTrabajo-2024"]

        def fake():
            rows, prompts = real()
            for i, r in enumerate(rows):
                r["machine"] = names[i % len(names)]
            return rows, prompts

        tui_app.cli.cached_sessions = fake
        try:
            app = tui_app.StoApp()
            async with app.run_test(size=(120, 20)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("2")
                await pilot.pause()
                for table_id in ("#t-groups", "#t-rows"):
                    table = app.query_one(table_id, tui_app.Table)
                    if table.row_count < 2:
                        continue
                    table.focus()
                    table.move_cursor(row=1)
                    await pilot.pause()
                    await pilot.pause()
                    assert table._marquee is not None, (table_id, "nothing scrolls")
                    kinds = {type(v).__name__ for (r, _), v in table.raw.items() if r == 1}
                    assert "Content" in kinds or table_id == "#t-rows", kinds
                    before = tui_widgets._plain(table.get_row_at(1)[-1])
                    for _ in range(9):
                        table._marquee_tick()
                        await pilot.pause()
                    after = tui_widgets._plain(table.get_row_at(1)[-1])
                    assert after != before, (table_id, before, after)
        finally:
            tui_app.cli.cached_sessions = real

    asyncio.run(go())



def test_keeping_a_conversation_asks_first_and_never_writes_on_escape():
    """`k` is the one key on this tab that puts bytes in the repo.

    It goes through the same Confirm every writing verb goes through, and
    escaping it has to leave `keep_session` uncalled — not called and rolled
    back, not called on a copy: uncalled.
    """
    async def go():
        llamadas = []
        real = tui_app.srv.keep_session
        tui_app.srv.keep_session = lambda *a, **k: llamadas.append(a) or {"bytes": 1024}
        try:
            app = tui_app.StoApp()
            async with app.run_test(size=(130, 30)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("2")
                await pilot.pause()
                pane = app.query_one("#sessions")
                if not pane.rows:
                    return                      # a machine with no transcripts
                pane.query_one("#t-rows", tui_app.Table).focus()
                await pilot.pause()
                await pilot.press("k")
                await pilot.pause()
                assert type(app.screen).__name__ == "Confirm", app.screen
                await pilot.press("escape")
                await pilot.pause()
                assert llamadas == [], llamadas
        finally:
            tui_app.srv.keep_session = real

    asyncio.run(go())


def test_bringing_a_conversation_that_was_never_kept_says_so_instead_of_failing():
    """The two verbs are halves of one round trip, and the row says which half
    you are on. Asking to bring a transcript nobody archived is the common
    mistake, so it answers with the missing step rather than an engine error.
    """
    async def go():
        llamadas = []
        real = tui_app.srv.resume_session
        tui_app.srv.resume_session = lambda *a, **k: llamadas.append(a) or {"ok": True}
        try:
            app = tui_app.StoApp()
            async with app.run_test(size=(130, 30)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("2")
                await pilot.pause()
                pane = app.query_one("#sessions")
                if not pane.rows:
                    return
                for r in pane.rows:
                    r["kept"] = False
                pane.query_one("#t-rows", tui_app.Table).focus()
                await pilot.pause()
                await pilot.press("a")          # bring it here
                await pilot.pause()
                # no confirmation, and above all no write
                assert type(app.screen).__name__ == "Screen", app.screen
                assert llamadas == [], llamadas
        finally:
            tui_app.srv.resume_session = real

    asyncio.run(go())


def test_the_kept_column_is_a_column_and_sorts_like_the_others():
    """Every column on this tab sorts, and the state marker is not an exception:
    "which of these travelled" is exactly the question you sort by."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(150, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            pane = app.query_one("#sessions")
            assert "kept" in pane.SORT_FIELDS
            table = pane.query_one("#t-rows", tui_app.Table)
            # one column per sort field, in the same order
            assert len(table.columns) == len(pane.SORT_FIELDS)
            if pane.rows:
                assert all("kept" in r for r in pane.rows)

    asyncio.run(go())


def test_the_footer_offers_a_verb_only_where_it_does_something():
    """The verbs live at the app so one handler dispatches them, and before
    this they were hidden bindings nobody could find.

    Showing them all instead is worse: `delete here` over a dashboard with
    nothing to delete is a promise the key does not keep. `check_action` turns
    each one off away from its pane and the CSS drops the dead key rather than
    dimming it, so the footer is a list of what actually works right here.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(150, 30)) as pilot:
            await app.workers.wait_for_complete()

            async def footer():
                await pilot.pause()
                return [s.text for s in app.screen._compositor.render_strips()][-1]

            await pilot.press("1")
            home = await footer()
            assert " k " not in home and " d " not in home, home

            await pilot.press("2")
            sessions = await footer()
            assert "keep" in sessions and "bring" in sessions, sessions
            assert "delete" not in sessions, sessions

            await pilot.press("4")
            tools = await footer()
            assert "bring" in tools and "delete" in tools, tools
            assert "keep" not in tools, tools

    asyncio.run(go())

if __name__ == "__main__":
    test_the_wordmark_is_a_rectangle()
    test_the_accent_and_the_ground_are_one_theme_each()
    test_a_screen_renders_with_its_chrome_pinned()
    test_a_document_has_its_own_keys()
    test_focus_starts_on_the_left_and_a_project_hands_it_to_the_right()
    test_the_last_column_takes_the_width_the_others_leave()
    test_the_search_box_is_on_screen_and_narrows_the_list()
    test_nothing_that_writes_runs_before_the_manifest_is_on_screen()
    test_a_transcript_is_a_conversation_of_blocks()
    test_only_the_bracket_is_escaped()
    test_the_home_does_not_pay_for_ccusage_before_it_paints()
    test_a_count_nobody_has_run_yet_is_not_a_zero()
    test_a_pane_off_screen_is_rebuilt_when_you_reach_it_and_not_before()
    test_the_wordmark_goes_when_it_does_not_fit_and_not_before()
    test_every_card_of_the_home_is_reachable_in_one_column()
    test_a_narrow_split_shows_one_level_and_walks_between_them()
    test_a_wide_split_shows_every_level_at_once()
    test_tab_walks_panels_and_the_tab_bar_is_somewhere_you_can_stand()
    test_up_leaves_a_list_only_from_its_first_row()
    test_s_cycles_the_sort_and_comes_back_to_the_natural_order()
    test_a_column_sorts_the_datum_and_not_the_cell()
    test_the_marquee_runs_only_where_text_is_cut_and_only_with_focus()
    test_a_memory_renders_as_markdown_and_a_transcript_does_not()
    test_tools_reaches_every_config_module_and_reads_one()
    test_the_home_search_finds_things_that_are_not_sessions()
    test_a_memory_shows_its_body_and_its_neighbours()
    test_a_coloured_cell_scrolls_too()
    test_keeping_a_conversation_asks_first_and_never_writes_on_escape()
    test_bringing_a_conversation_that_was_never_kept_says_so_instead_of_failing()
    test_the_kept_column_is_a_column_and_sorts_like_the_others()
    test_the_footer_offers_a_verb_only_where_it_does_something()
    print("OK")
