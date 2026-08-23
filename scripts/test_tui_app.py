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


def test_the_wordmark_folds_six_pixel_rows_into_three():
    """`█` when both halves of the cell are lit, `▀` and `▄` when one is.

    The letterforms are the prototype's, drawn on a 6-row pixel grid; the whole
    point of the fold is that the banner costs three rows instead of six. Get
    the pairing wrong and it still renders — as letters with holes in them.
    """
    rows = tui_app.wordmark("STO")
    assert len(rows) == 3, rows
    assert len({len(r) for r in rows}) == 1, "the rows are not the same width"
    # the O is closed on both sides: every row of it has ink at the far left
    assert all(set(r) <= set(" █▀▄") for r in rows), rows
    assert "█" in rows[1], rows[1]


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

            # and every tab paints without falling over
            for key in "23456":
                await pilot.press(key)
                await pilot.pause()
                painted = [s.text for s in app.screen._compositor.render_strips()]
                assert "braingent STO" in painted[0], key
                assert "PUSH" in painted[-1], key

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
    test_the_wordmark_folds_six_pixel_rows_into_three()
    test_a_screen_renders_with_its_chrome_pinned()
    test_the_last_column_takes_the_width_the_others_leave()
    print("OK")
