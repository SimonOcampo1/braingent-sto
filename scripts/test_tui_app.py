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

from textual.geometry import Offset

import sessions_server as srv
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


def test_the_wordmark_has_one_typeface_and_three_sizes():
    """Pasted art goes crooked the moment somebody edits one line of it, and a
    second typeface for the narrow case is worse than a smaller logo: the
    product looks like two products.

    So the name wraps to two blocks before it changes how it is drawn, and only
    gives up the face when even the wrapped one does not fit. None of the three
    is stored as a rectangle — the generator right-strips — so the widget pads
    before it centres, and it is the padded block that has to be square.
    Centring a ragged block shears a six-row letterform into a staircase.
    """
    one, stack = tui_widgets.WORDMARK, tui_widgets.WORDMARK_STACK
    for art in (one, stack):
        width = max(len(r) for r in art)
        padded = [f"{r:<{width}}" for r in art]
        assert len({len(r) for r in padded}) == 1, [len(r) for r in padded]
    # the wrapped one is the same letters on two lines: narrower and taller
    assert tui_widgets.WORDMARK_STACK_W < tui_widgets.WORDMARK_W
    assert len(stack) > len(one)
    # and the same face, which is what "one typeface" means here: every glyph
    # of the wrapped art appears in the single-line art
    assert set("".join(stack)) <= set("".join(one)), "the narrow face drifted"
    assert tui_widgets.WORDMARK_FLAT.strip(), "no name is left at the last size"


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
    """The tab bar and the footer are on screen at every height.

    The two things that must not scroll away, arranged the way that keeps
    working in code and stops working on screen: one container docked top,
    `Footer` docked bottom. There used to be three — a title bar saying the
    name of the app above a screen with the name of the app on it, plus three
    facts that change about once a year. Those moved to the foot of the home.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(124, 28)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            bar = "\n".join(screen_text(app)[:3])
            assert "HOME" in bar and "CONFIG" in bar, bar
            assert "PUSH" in screen_text(app)[-1]
            # the library's own way out of the product is not in our footer
            assert "palette" not in screen_text(app)[-1]
            # the facts the title bar carried are at the foot of the home, which
            # is a scroll away rather than pinned over every screen
            app.query_one("#home").scroll_end(animate=False)
            await pilot.pause()
            home = "\n".join(screen_text(app))
            assert "agent" in home and srv.LOCAL_MACHINE in home, home
            app.query_one("#home").scroll_home(animate=False)
            await pilot.pause()

            for key in "23456":
                await pilot.press(key)
                await pilot.pause()
                painted = screen_text(app)
                assert "HOME" in "\n".join(painted[:3]), key
                assert "PUSH" in painted[-1], key

    asyncio.run(go())


def _is_tint(hex_colour, ground, accent):
    """Is this the accent laid over the ground at some opacity?

    A cursor is allowed to be one — that is how a highlight stays legible
    without repainting the text. A *tone* is not: the grey `background-tint`
    Textual adds by itself lands between the ground and the foreground, so its
    channels move by three different fractions. A real blend moves all three by
    the same one, which is what this checks.
    """
    def rgb(value):
        value = value.lstrip("#")
        return [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    here, base, top = rgb(hex_colour), rgb(ground), rgb(accent)
    ratios = []
    for got, a, b in zip(here, base, top):
        if abs(b - a) < 8:
            continue                  # that channel says nothing about the mix
        ratios.append((got - a) / (b - a))
    return bool(ratios) and max(ratios) - min(ratios) < 0.08


def test_pure_black_is_pure_black_everywhere():
    """A theme is one ground, and what separates a panel from the screen is its
    outline — not a second shade behind it.

    Three tones used to be on screen at once: a background, a card a little
    lighter, a bar lighter again. "Pure black" was black only in the gaps.
    Textual 8 adds a fourth by itself — `background-tint`, `$foreground 5%` by
    default on several widgets — which put a table at #0b0b0b on a screen
    painted #000000, so the one thing you were reading was the one thing that
    was not black.

    Every ground the compositor paints has to be a colour this design chose:
    the ground itself, the raised tone behind a button, or the accent under a
    cursor.
    """
    async def go():
        for ground in ("black", "dark", "light"):
            app = tui_app.StoApp()
            app.ground = ground
            async with app.run_test(size=(126, 30)) as pilot:
                app.apply_theme()
                await app.workers.wait_for_complete()
                for key in "12456":
                    await pilot.press(key)
                    await pilot.pause()
                    theme = app.current_theme
                    allowed = {c.lower() for c in
                               (theme.background, theme.panel, theme.surface,
                                theme.accent, theme.primary, theme.error,
                                theme.warning, theme.success)}
                    painted = set()
                    for strip in app.screen._compositor.render_strips():
                        for seg in strip:
                            style = getattr(seg.style, "rich_style", seg.style)
                            col = getattr(style, "bgcolor", None)
                            if col is not None:
                                painted.add(col.get_truecolor().hex.lower())
                    stray = {c for c in painted - allowed
                             if not _is_tint(c, theme.background, theme.accent)}
                    assert not stray, (ground, key, sorted(stray), sorted(allowed))

    asyncio.run(go())


def _polarity(app, table, y):
    """(text luminance, ground luminance) averaged over one painted row."""
    def lum(color):
        out = 0.0
        for channel, weight in zip(color.get_truecolor(), (0.2126, 0.7152, 0.0722)):
            c = channel / 255
            out += weight * (c / 12.92 if c <= 0.03928
                             else ((c + 0.055) / 1.055) ** 2.4)
        return out
    ink, ground, n = 0.0, 0.0, 0
    for seg in app.screen._compositor.render_strips()[y]:
        style = getattr(seg.style, "rich_style", seg.style)
        if not seg.text.strip() or style.color is None or style.bgcolor is None:
            continue
        ink += lum(style.color) * len(seg.text)
        ground += lum(style.bgcolor) * len(seg.text)
        n += len(seg.text)
    assert n, "nothing with ink on that row"
    return ink / n, ground / n


def test_the_row_cursor_keeps_the_polarity_of_the_screen():
    """The selected row goes monochrome — `DataTable` applies the cursor's own
    foreground over the cell's spans and it carries one by default, so every
    table works that way and this one is no exception.

    What must not change is the direction. The screen is light text on a dark
    ground; the cursor used to paint the row a slab of accent and force the
    text to `$background`, so one row came out dark-on-bright — the row you
    selected in order to look at it turned into a different design, the grey
    outline of its buttons went black, and the dimmed states disappeared. A
    tint keeps the ground recognisably the ground.

    Checked against every accent, because "is this legible" is not a question a
    single colour can answer for the other five.
    """
    async def go():
        for _, code in tui_app.ui.ACCENTS:
            app = tui_app.StoApp()
            async with app.run_test(size=(132, 30)) as pilot:
                tui_app.ui.ACCENT = code
                app.apply_theme()
                await app.workers.wait_for_complete()
                await pilot.press("2")
                await pilot.pause()
                table = app.query_one("#t-groups", tui_app.Table)
                if table.row_count < 3:
                    continue
                table.focus()
                table.move_cursor(row=2)
                await pilot.pause()
                head = table.region.y + 1
                plain_ink, plain_bg = _polarity(app, table, head + 1)
                ink, bg = _polarity(app, table, head + 2)
                assert (ink > bg) is (plain_ink > plain_bg), \
                    (code, "the cursor row inverted", round(ink, 3), round(bg, 3))
                # and a tint, not a slab: the ground stays nearer the screen's
                # own than the accent's
                assert abs(bg - plain_bg) < 0.25, (code, round(bg, 3), round(plain_bg, 3))

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


def test_the_wordmark_shrinks_before_it_disappears():
    """It used to be hidden the moment it did not fit, and the only thing that
    fit was one flat face. Now the window picks a size, not a typeface.

    One line while the window is wide enough for it, the same letters wrapped
    to two blocks while *that* fits, and the bare name when there is no room
    for a logo at all. It still goes entirely on a terminal too short to spend
    six rows on a banner, which is a height question and not a width one.
    """
    async def go():
        cases = (((120, 34), 6),     # one line of ansi_shadow
                 ((90, 34), 13),     # the same letters, wrapped
                 ((90, 24), 1),      # no rows to wrap into: the name, plainly
                 ((60, 30), 1))      # too narrow even for the wrapped face
        for size, rows in cases:
            app = tui_app.StoApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                mark = app.query_one("#wordmark", tui_widgets.Wordmark)
                assert mark.display, size
                assert len(mark.art()) == rows, (size, len(mark.art()), rows)

        app = tui_app.StoApp()
        async with app.run_test(size=(120, 20)) as pilot:
            await pilot.pause()
            assert not app.query_one("#wordmark").display, "a banner on 20 rows"

    asyncio.run(go())


def test_the_whole_home_is_reachable_in_a_short_window():
    """At 70x30 the home rendered SYNC and half of CONFIG PARITY, and USAGE and
    OVERALL were not on the screen at all.

    Not clipped — absent, with no scroll in the pane, so no key and no mouse
    could reach them. A `1fr` child inside an `auto` row resolves to its own
    natural height, and the first one took the screen. The home is cards-free
    now and fits at that size, so the rule is checked where it can still break:
    a window too short for the masthead, the counts and the gauges together.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(70, 16)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            home = app.query_one("#home")
            assert home.max_scroll_y > 0, "the home does not scroll"
            assert app.query_one("#more").display, "nothing says there is more"
            home.scroll_end(animate=False)
            await pilot.pause()
            seen = "\n".join(screen_text(app))
            usage = app.usage.get("limits") or []
            if usage:
                name = (usage[0].get("label") or usage[0].get("kind") or "")
                assert name.replace("_", " ")[:7] in seen, seen
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


def test_a_split_lays_the_hierarchy_out_or_walks_it():
    """Sessions and memories are two lists — the projects, and what one project
    holds — and the window decides whether you see both or one.

    Wide enough for two lists: side by side, each in its own box, and the
    search box on top belongs to this tab and filters this tab. Under that, the
    same hierarchy walked instead of laid out: the rail would be too narrow to
    read a project name in, and the rows would belong to projects nobody had
    chosen. `→` goes in and `←` comes back out, and the widgets stay mounted
    either way, so resizing across the breakpoint keeps your place.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(170, 30)) as pilot:
            await app.workers.wait_for_complete()
            for tab in ("2", "3"):
                await pilot.press(tab)
                await pilot.pause()
                assert app.query_one("#groups").display, tab
                assert app.query_one("#rows").display, tab
                # every tab's own box filters its own tab
                pane = app.panes[app.tab]
                assert pane.query_one("#search").display, tab

        app = tui_app.StoApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            assert app.query_one("#groups").display
            assert not app.query_one("#rows").display, "the sessions were on screen"
            await pilot.press("right")
            await pilot.pause()
            assert app.query_one("#rows").display
            assert not app.query_one("#groups").display
            assert app.query_one("#t-rows", tui_app.Table).has_focus
            await pilot.press("left")
            await pilot.pause()
            assert app.query_one("#groups").display

    asyncio.run(go())


def test_tab_walks_tabs_and_the_arrows_walk_everything_inside_one():
    """One key, one axis.

    `Tab` used to walk the panels inside a screen, which left the six screens
    themselves reachable only by digit or by mouse and forced two escape
    hatches into existence so the bar could be focused at all. Now `Tab` walks
    tabs — which is what the key is called — `←`/`→` walk the panels of the
    screen you are on, and `↑`/`↓` walk the rows of the panel you are in.

    In a hierarchy "the next panel" is the next level, so `→` opens the project
    and `←` comes back out.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 34)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()

            await pilot.press("tab")
            await pilot.pause()
            assert app.tab == 2, app.tab
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.tab == 1, app.tab

            pane = app.query_one("#sessions")
            groups = pane.query_one("#t-groups", tui_app.Table)
            groups.focus()
            await pilot.pause()

            await pilot.press("right")            # into the project
            await pilot.pause()
            assert pane.level == 1, pane.level
            assert app.focused is not None and app.focused.id == "t-rows"
            await pilot.press("left")             # and back out
            await pilot.pause()
            assert pane.level == 0, pane.level

            # out of the outermost level, the arrows walk what is left: the
            # list and the box that filters it
            await pilot.press("left")
            await pilot.pause()
            assert app.focused is not None and app.focused.id == "search"
            # and a digit typed in the box is a digit -- that is what it is for
            await pilot.press("5")
            await pilot.pause()
            assert app.tab == 1, "a digit typed in the search box changed tab"
            pane.query_one("#search").value = ""

            # `←`/`→` belong to the text while the box has the focus, so the
            # way back down into the list it filters is `↓`
            await pilot.press("down")
            await pilot.pause()
            table = app.focused
            assert isinstance(table, tui_app.Table), app.focused
            if table.row_count > 2:
                table.move_cursor(row=0)
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                assert table.cursor_row == 1, table.cursor_row
                await pilot.press("up")
                await pilot.pause()
                assert table.cursor_row == 0, table.cursor_row
                # at the top it stays: there is no hatch to fall through any
                # more, because there is nothing above a list to reach
                await pilot.press("up")
                await pilot.pause()
                assert app.focused is table, "up left the list from its first row"
                assert table.cursor_row == 0, table.cursor_row

            await pilot.press("5")
            await pilot.pause()
            assert app.tab == 4, app.tab

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
            # column 2: the first two are the buttons, and a button does not sort
            assert rows.sort_by == (2, False), rows.sort_by
            stamps = [r["mtime"] for r in pane.rows]
            assert stamps == sorted(stamps), "when did not sort by time"

            # walk to `errors` and check it sorts by the count, not the markup
            while rows.sort_by is not None and rows.sort_by[0] != 5:
                await pilot.press("s")
                await pilot.pause()
            assert rows.sort_by is not None, "errors never came up in the cycle"
            counts = [r["errors"] for r in pane.rows]
            assert counts == sorted(counts), counts

    asyncio.run(go())


def test_s_on_the_project_rail_sorts_the_projects_and_not_the_rows():
    """The rail handed its sort to the pane, and the pane sorted the rows
    beside it: `s` on the projects moved everything except the projects."""
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(150, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            pane = app.query_one("#sessions")
            if len(pane.groups) < 3:
                return
            groups = pane.query_one("#t-groups", tui_app.Table)
            groups.focus()
            await pilot.pause()
            await pilot.press("s")                  # the count, ascending
            await pilot.pause()
            counts = [len(items) for _, items in pane.groups]
            assert counts == sorted(counts), counts
            await pilot.press("s", "s")             # the name, ascending
            await pilot.pause()
            names = [name.lower() for name, _ in pane.groups]
            assert names == sorted(names), names
            # and the rail still points at the group it shows
            groups.move_cursor(row=1)
            await pilot.pause()
            assert {r["project"] for r in pane.rows} == {pane.groups[0][0]}

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

            # the tab bar is not a place the keyboard stands any more, so the
            # focus goes somewhere that is: the box above the list
            await pilot.press("left")
            await pilot.pause()
            assert not table.has_focus, app.focused
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
            # narrow on purpose: a marquee is what a cell does when its column
            # cut it, so the column has to be able to cut it
            async with app.run_test(size=(70, 20)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("2")
                await pilot.pause()
                for table_id in ("#t-groups", "#t-rows"):
                    if table_id == "#t-rows":
                        # one level in: the sessions are not on screen until a
                        # project has been chosen
                        app.query_one("#t-groups", tui_app.Table).focus()
                        await pilot.press("enter")
                        await pilot.pause()
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
                # one level in: the conversations are behind their project
                pane.query_one("#t-groups", tui_app.Table).focus()
                await pilot.press("enter")
                await pilot.pause()
                table = pane.query_one("#t-rows", tui_app.Table)
                table.move_cursor(row=0)
                # recorded here and never archived: `e` means keep
                pane.rows[0]["machine"], pane.rows[0]["kept"] = None, False
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                assert type(app.screen).__name__ == "Confirm", app.screen
                await pilot.press("escape")
                await pilot.pause()
                assert llamadas == [], llamadas
        finally:
            tui_app.srv.keep_session = real

    asyncio.run(go())


def test_a_conversation_with_nowhere_to_go_is_not_a_write():
    """`e` is one button with two meanings, and the row decides which.

    Recorded on another machine and never archived there, it has nothing to
    bring: the button says so and writes nothing, rather than handing the
    engine an id it will fail on.
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
                pane.query_one("#t-groups", tui_app.Table).focus()
                await pilot.press("enter")
                await pilot.pause()
                for r in pane.rows:
                    r["machine"], r["kept"] = "otra-maquina", False
                pane.query_one("#t-rows", tui_app.Table).move_cursor(row=0)
                await pilot.pause()
                await pilot.press("e")          # nothing to bring
                await pilot.pause()
                # no confirmation, and above all no write
                assert type(app.screen).__name__ == "Screen", app.screen
                assert llamadas == [], llamadas
        finally:
            tui_app.srv.resume_session = real

    asyncio.run(go())


def test_the_two_buttons_are_columns_and_they_never_sort():
    """The state marker became a button: the first column says what `e` would
    do to that row, so `kept` is on screen where you can act on it rather than
    as a dot in a column of its own.

    Neither button sorts. They are the same glyph for every row in the same
    state, so ordering by one of them orders by nothing — `SORT_FIELDS` says
    so with a `None`, and the count still has to match the columns.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(150, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            pane = app.query_one("#sessions")
            assert pane.SORT_FIELDS[:2] == (None, None), pane.SORT_FIELDS
            table = pane.query_one("#t-rows", tui_app.Table)
            # one column per sort field, in the same order
            assert len(table.columns) == len(pane.SORT_FIELDS)
            if pane.rows:
                assert all("kept" in r for r in pane.rows)
                # the glyph is the verb: kept locally is done, unkept is a push
                local = next((r for r in pane.rows if not r.get("machine")), None)
                if local is not None:
                    assert pane._todo(local) == (None if local["kept"] else "keep")

    asyncio.run(go())


def test_the_row_buttons_are_clickable_and_open_their_own_modal():
    """They are chips in a column because a `DataTable` cannot hold a real
    `Button`, but they have to behave like buttons: the pointer lands on one
    and the thing it names opens.

    Clicking also moves the cursor to the row under the pointer first — the
    table sets it from the same coordinate, but only after this bubbles, so
    acting on `cursor_row` without moving it acts on the previous row.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("2")
            await pilot.pause()
            pane = app.query_one("#sessions")
            if not pane.groups:
                return                          # a machine with no transcripts
            groups = pane.query_one("#t-groups", tui_app.Table)
            widths = [c.get_render_width(groups) for c in groups.columns.values()]

            # the second column, on the second row of the table: row 0 is the
            # header, row 1 is "all", row 2 is the first real project
            x = widths[0] + groups.cell_padding * 3
            await pilot.click(groups, offset=Offset(x, 3))
            await pilot.pause()
            assert type(app.screen).__name__ == "PathPrompt", app.screen
            assert app.screen._project == pane.groups[1][0], app.screen._project
            await pilot.press("escape")
            await pilot.pause()

            # and the first column is the other verb, with its own modal
            await pilot.click(groups, offset=Offset(2, 3))
            await pilot.pause()
            assert type(app.screen).__name__ in ("Confirm", "Screen"), app.screen
            if type(app.screen).__name__ == "Confirm":
                await pilot.press("escape")

    asyncio.run(go())


def test_w_asks_where_the_project_lives_and_writes_only_on_enter():
    """The second button on the row. A project sits at a different absolute
    path on every machine, `claude --resume` only reads the directory matching
    the path a session was filed against, and nothing else on the screen could
    say what that path is here.

    Escaping the prompt writes nothing, the way every other verb behaves.

    The listing fills the registry on its own from each transcript's cwd, and
    through the same `set_project_path`. With that stubbed nothing ever lands
    on disk, so every refresh "finds" the paths again and writes them again --
    the test was counting the loader, not the prompt. It is switched off here.
    """
    async def go():
        saved = []
        real = tui_app.srv.set_project_path
        real_remember = tui_app.srv.remember_project_paths
        tui_app.srv.set_project_path = lambda *a: saved.append(a)
        tui_app.srv.remember_project_paths = lambda rows: None
        try:
            app = tui_app.StoApp()
            async with app.run_test(size=(140, 30)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("2")
                await pilot.pause()
                pane = app.query_one("#sessions")
                if not pane.groups:
                    return                       # a machine with no transcripts
                groups = pane.query_one("#t-groups", tui_app.Table)
                groups.focus()
                groups.move_cursor(row=1)        # row 0 is "all", not a project
                await pilot.pause()

                await pilot.press("w")
                await pilot.pause()
                assert type(app.screen).__name__ == "PathPrompt", app.screen
                await pilot.press("escape")
                await pilot.pause()
                assert saved == [], saved

                await pilot.press("w")
                await pilot.pause()
                app.screen.query_one("#path-input").value = "/tmp/donde-vive"
                await pilot.press("enter")
                await pilot.pause()
                assert saved == [(pane.groups[0][0], "/tmp/donde-vive")], saved
        finally:
            tui_app.srv.set_project_path = real
            tui_app.srv.remember_project_paths = real_remember

    asyncio.run(go())


def test_the_home_leads_with_the_counts_and_the_two_arrows():
    """The dashboard was four cards of four different densities, and the one
    number anybody opens the screen for — is there anything to sync? — was a
    cell in a parity table.

    Now it is the wordmark, the box that searches everything, the counts, and
    the two arrows, in that order.
    """
    async def go():
        app = tui_app.StoApp()
        async with app.run_test(size=(140, 34)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = "\n".join(screen_text(app))
            for key in ("n_sessions", "n_projects", "n_memories", "n_skills",
                        "n_machines"):
                assert tui_app.i18n.t(key).upper()[:11] in body, (key, body)
            assert "\u25b2" in body and "\u25bc" in body, body
            # and the parity detail it dropped is on the screen that can change it
            await pilot.press("5")
            await pilot.pause()
            mods = app.query_one("#t-modules", tui_app.Table)
            assert mods.row_count, "the modules went nowhere"

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
            # the two buttons on the row, and only those: `keep` and `bring`
            # were two key caps for the one decision the row already makes
            assert " e " in sessions and " w " in sessions, sessions
            assert "delete" not in sessions and "keep" not in sessions, sessions

            await pilot.press("4")
            tools = await footer()
            assert "bring" in tools and "delete" in tools, tools
            assert " e " not in tools and " w " not in tools, tools

    asyncio.run(go())

if __name__ == "__main__":
    test_the_wordmark_has_one_typeface_and_three_sizes()
    test_the_accent_and_the_ground_are_one_theme_each()
    test_a_screen_renders_with_its_chrome_pinned()
    test_pure_black_is_pure_black_everywhere()
    test_the_row_cursor_keeps_the_polarity_of_the_screen()
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
    test_the_wordmark_shrinks_before_it_disappears()
    test_the_whole_home_is_reachable_in_a_short_window()
    test_a_narrow_split_shows_one_level_and_walks_between_them()
    test_a_split_lays_the_hierarchy_out_or_walks_it()
    test_tab_walks_tabs_and_the_arrows_walk_everything_inside_one()
    test_s_cycles_the_sort_and_comes_back_to_the_natural_order()
    test_a_column_sorts_the_datum_and_not_the_cell()
    test_s_on_the_project_rail_sorts_the_projects_and_not_the_rows()
    test_the_marquee_runs_only_where_text_is_cut_and_only_with_focus()
    test_a_memory_renders_as_markdown_and_a_transcript_does_not()
    test_tools_reaches_every_config_module_and_reads_one()
    test_the_home_search_finds_things_that_are_not_sessions()
    test_a_memory_shows_its_body_and_its_neighbours()
    test_a_coloured_cell_scrolls_too()
    test_keeping_a_conversation_asks_first_and_never_writes_on_escape()
    test_a_conversation_with_nowhere_to_go_is_not_a_write()
    test_the_two_buttons_are_columns_and_they_never_sort()
    test_the_row_buttons_are_clickable_and_open_their_own_modal()
    test_w_asks_where_the_project_lives_and_writes_only_on_enter()
    test_the_home_leads_with_the_counts_and_the_two_arrows()
    test_the_footer_offers_a_verb_only_where_it_does_something()
    print("OK")
