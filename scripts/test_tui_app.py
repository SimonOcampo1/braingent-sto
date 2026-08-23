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
from textual.widgets import Markdown  # noqa: E402


def screen_text(app):
    return [strip.text for strip in app.screen._compositor.render_strips()]


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
            await pilot.press("4")            # skills: name + description
            await pilot.pause()
            await pilot.pause()
            table = app.query_one("#skills").query_one("#t-rows", tui_app.Table)
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
            await pilot.press("4")
            await pilot.pause()
            pane = app.query_one("#skills")
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

            await pilot.press("4")
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
            down = [table.get_row_at(i)[col] for i in range(table.row_count)]
            assert down == list(reversed(up)), (up, down)

            for _ in range(20):
                await pilot.press("s")
                await pilot.pause()
                if table.sort_by is None:
                    break
            assert table.sort_by is None, "the cycle never returned to unsorted"
            after = [table.get_row_at(i)[5] for i in range(table.row_count)]
            assert after == natural, "unsorted is not the order the pane wrote"

    asyncio.run(go())


def test_a_column_whose_only_correct_order_is_the_default_is_not_in_the_cycle():
    """`when` renders `2 h`, `5 d`, `3 w`. Sorted as text that interleaves
    hours with weeks; sorted correctly it is `mtime`, which is already the
    order the pane arrives in."""
    table = tui_app.Table((tui_app.t("col_when"), 10),
                          (tui_app.t("col_project"), 18, "text"),
                          (tui_app.t("col_prompts"), 7, "num"))
    assert table.sortable == [1, 2], table.sortable


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
    test_a_column_whose_only_correct_order_is_the_default_is_not_in_the_cycle()
    test_the_marquee_runs_only_where_text_is_cut_and_only_with_focus()
    test_a_memory_renders_as_markdown_and_a_transcript_does_not()
    print("OK")
