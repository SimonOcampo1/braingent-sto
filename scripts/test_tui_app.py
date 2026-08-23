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


def test_tab_walks_the_tab_bar_and_a_document_has_its_own_keys():
    """`tab` is the library's focus-next by default, and it ate the one key
    that is supposed to mean the same thing on every screen.

    And a reader shadows the keys that act on the repo: reading a transcript
    with PUSH one keystroke away is an accident, and hiding them also stops the
    footer offering keys the screen cannot use.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            for expected in (1, 2, 3):
                await pilot.press("tab")
                await pilot.pause()
                assert app.tab == expected, (app.tab, expected)
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.tab == 2, app.tab

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


if __name__ == "__main__":
    test_the_wordmark_is_a_rectangle()
    test_the_accent_and_the_ground_are_one_theme_each()
    test_a_screen_renders_with_its_chrome_pinned()
    test_tab_walks_the_tab_bar_and_a_document_has_its_own_keys()
    test_focus_starts_on_the_left_and_a_project_hands_it_to_the_right()
    test_the_last_column_takes_the_width_the_others_leave()
    test_the_search_box_is_on_screen_and_narrows_the_list()
    test_nothing_that_writes_runs_before_the_manifest_is_on_screen()
    test_a_transcript_is_a_conversation_of_blocks()
    test_only_the_bracket_is_escaped()
    test_the_home_does_not_pay_for_ccusage_before_it_paints()
    test_a_count_nobody_has_run_yet_is_not_a_zero()
    test_a_pane_off_screen_is_rebuilt_when_you_reach_it_and_not_before()
    print("OK")
