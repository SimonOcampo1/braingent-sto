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


def test_the_wordmark_is_a_rectangle():
    """Pasted art goes crooked the moment somebody edits one line of it.

    Every row has to be the same width or the block leans, and it has to stay
    small: the whole point of spelling only `STO` is that the banner is a mark
    beside the name and not a wall across the top of the home.
    """
    rows = tui_app.WORDMARK
    assert len({len(r) for r in rows}) == 1, [len(r) for r in rows]
    assert len(rows) == 6, len(rows)
    assert len(rows[0]) < 30, len(rows[0])


def test_a_screen_renders_with_its_chrome_pinned():
    """The header, the tab bar and the footer are on screen at every height.

    They are the three things that must not scroll away, and the way that is
    arranged — one container docked top, `Footer` docked bottom — is exactly
    the kind of thing that keeps working in code and stops working on screen.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            lines = [s.text for s in app.screen._compositor.render_strips()]
            assert "braingent STO" in lines[0], lines[0]
            assert "Home" in lines[1] and "Config" in lines[1], lines[1]
            assert "PUSH" in lines[-1], lines[-1]
            # the library's own way out of the product is not in our footer
            assert "palette" not in lines[-1], lines[-1]

            # and every tab paints without falling over
            for key in "23456":
                await pilot.press(key)
                await pilot.pause()
                painted = [s.text for s in app.screen._compositor.render_strips()]
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
        async with app.run_test(size=(124, 34)) as pilot:
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
            await pilot.press("enter")
            await pilot.pause()
            foot = [s.text for s in app.screen._compositor.render_strips()][-1]
            assert "back" in foot and "PUSH" not in foot, foot
            doc = app.screen.query_one("#doc-scroll")
            await pilot.press("pagedown")
            await pilot.pause()
            assert doc.scroll_offset.y > 0, "the document did not scroll"
            await pilot.press("escape")
            await pilot.pause()
            assert app.tab == 1, app.tab

    asyncio.run(go())


def test_the_last_column_takes_the_width_the_others_leave():
    """A `DataTable` sizes a column from its header and never shrinks it, so
    without this the description column pushes the table wider than its card
    and the left-hand columns walk off the edge."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.press("4")           # skills: name + description
            await pilot.pause()
            table = app.query_one("#t-skills", tui_app.Table)
            widths = [c.width for c in table.columns.values()]
            assert widths[0] == 34, widths
            assert widths[-1] > 20, widths
            assert sum(widths) <= table.size.width, (widths, table.size.width)

    asyncio.run(go())


if __name__ == "__main__":
    test_the_wordmark_is_a_rectangle()
    test_a_screen_renders_with_its_chrome_pinned()
    test_tab_walks_the_tab_bar_and_a_document_has_its_own_keys()
    test_the_last_column_takes_the_width_the_others_leave()
    print("OK")
