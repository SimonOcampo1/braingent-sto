import tempfile
import threading
import time
from pathlib import Path

import ui

# We replace status_summary outright (not just its cache, which is TTL-bound —
# SUMMARY_TTL=30s — and would expire if the file takes longer than that to run)
# so no draw() below fires real git or network. Only
# test_header_shows_usage_and_sync_on_the_right overrides it again, saving and
# restoring this one around itself.
ui.status_summary = lambda: "uso ?%  ↑0 ↓0"

# cli.COLOR is False when stdout is not a tty — that is, always while the tests
# run. We force it to True to exercise the ANSI path: it is the one that runs for
# real, and the only one where fit()/strip_ansi() have anything to do.
ui.cli.COLOR = True
ui.load_prefs()             # in case the machine has another language saved
ui.i18n.LANG = "es"         # los asserts de abajo son sobre los strings en castellano

SES, MEM, CFG = ui.SESSIONS, ui.MEMORY, ui.CONFIG
AYU = ui.HELP
ESC, ENTER = chr(27), chr(13)
DIA = ui.cli._day(0.0)   # the epoch day in this machine's timezone


def _rows(n=5, project="projA"):
    return [{"id": f"{i}" * 8, "project": project, "mtime": 0.0, "kind": "session",
             "n_prompts": i, "n_tools": i, "title": f"sesión {i}",
             "machine": None, "path": f"/tmp/{i}.jsonl"} for i in range(n)]


def _st(n=5):
    """Estado con n filas falsas en la tab de sesiones, ya adentro de un proyecto."""
    st = ui.new_state()
    st["tab"], st["proj"] = SES, "projA"
    st["rows"] = _rows(n)
    return st


def test_moves_within_bounds():
    st = _st()
    st = ui.handle(st, "down")
    assert st["sel"] == 1
    for _ in range(20):
        st = ui.handle(st, "down")
    assert st["sel"] == 4          # no se pasa del final
    for _ in range(20):
        st = ui.handle(st, "up")
    assert st["sel"] == 0          # ni del principio


def test_tabs_cycle_and_reset_selection():
    st = _st()
    st["sel"] = 3
    st = ui.handle(st, "right")
    assert st["tab"] == MEM and st["sel"] == 0 and st["top"] == 0
    for _ in range(3):
        st = ui.handle(st, "right")
    assert st["tab"] == ui.HOME    # cicla sobre las cinco secciones
    st = ui.handle(st, "4")
    assert st["tab"] == CFG
    st = ui.handle(st, "5")
    assert st["tab"] == AYU


def test_draw_returns_exact_geometry_and_marks_active_tab():
    st = _st()
    lines = ui.draw(st, 60, 12)
    assert len(lines) == 12
    assert all(len(ui.strip_ansi(l)) == 60 for l in lines)
    assert "Sesiones" in ui.strip_ansi(lines[0])
    assert ui.strip_ansi(lines[2]).startswith(">")     # the cursor is on row 0
    assert "sesión 0" in ui.strip_ansi(lines[2])       # the title leads the row
    assert DIA in ui.strip_ansi(lines[3])              # date + counters underneath
    assert "salir" in ui.strip_ansi(lines[-1])


def test_two_line_rows_halve_the_visible_window_and_scroll_by_row():
    # h=12 → body_height=8 → with ROW_H=2 four sessions fit, not eight.
    st = _st(n=50)
    assert ui.visible_rows(st, 12) == 4
    body = [ui.strip_ansi(l) for l in ui.draw(st, 60, 12)[2:10]]
    assert sum(1 for l in body if "sesión" in l) == 4               # 4 cabeceras
    assert sum(1 for l in body if l[4:].startswith(DIA)) == 4       # 4 sub-lines
    # the window advances one session at a time (two lines), never splitting one
    for _ in range(4):
        st = ui.handle(st, "down")
    body = [ui.strip_ansi(l) for l in ui.draw(st, 60, 12)[2:10]]
    assert st["top"] == 1                       # draw() es quien corre _clamp()
    assert "sesión 1" in body[0] and body[1][4:].startswith(DIA)
    assert "sesión 0" not in "\n".join(body)


def test_a_row_says_which_machine_it_came_from_without_losing_its_title():
    """Both lists answer "where is this from" in the same column, and a local
    session says so by name instead of leaving the column blank."""
    r = dict(_rows(1)[0], title="arreglar el escapado de settings.json",
             n_prompts=1, n_tools=12)
    head, sub = ui.strip_ansi(ui.fmt_session(r, 100)).split("\n")
    assert head.startswith("arreglar el escapado")
    assert head.rstrip().endswith(ui.srv.LOCAL_MACHINE[:ui.MACHINE_W])
    assert "1 prompt " in sub + " " and "12 tools" in sub   # singular is not "1 prompts"
    assert r["id"][:8] in sub

    # a session pulled from another machine names that one, not this one
    otra = ui.strip_ansi(ui.fmt_session(dict(r, machine="NotebookX"), 100))
    assert otra.split("\n")[0].rstrip().endswith("NotebookX")

    # the row never overruns the space draw() leaves it, at any width
    for w in (40, 60, 80, 120):
        for linea in ui.strip_ansi(ui.fmt_session(r, w)).split("\n"):
            assert len(linea) <= w - 4, (w, linea)
    # and on a narrow terminal the machine column is what gives way
    assert ui.srv.LOCAL_MACHINE not in ui.strip_ansi(ui.fmt_session(r, 40))


def test_a_title_with_newlines_still_occupies_exactly_two_lines():
    # titles come from the first prompt: a multi-line one would push the rows
    # below and the cursor would stop landing where `sel` says
    st = _st(n=3)
    st["rows"][0]["title"] = "primera línea\nsegunda\ntercera"
    body = [ui.strip_ansi(l) for l in ui.draw(st, 60, 12)[2:10]]
    assert body[0][2:].strip().startswith("primera línea segunda tercera")
    assert body[1][4:].startswith(DIA)        # its sub-line, not the next row
    assert sum(1 for l in body if l[4:].startswith(DIA)) == 3


def test_draw_clamps_a_formatter_that_returns_more_lines_than_row_h():
    st = _st(n=3)
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], real[1], lambda r, w=100: "a\nb\nc\nd", real[3])
    try:
        body = [ui.strip_ansi(l) for l in ui.draw(st, 60, 12)[2:10]]
        assert [l[2:].strip() for l in body[:6]] == ["a", "b", "a", "b", "a", "b"]
    finally:
        ui.TABS[SES] = real


def test_draw_scrolls_the_window_with_the_cursor():
    st = _st(n=50)
    for _ in range(40):
        st = ui.handle(st, "down")
    lines = [ui.strip_ansi(l) for l in ui.draw(st, 60, 12)]
    assert any("sesión 40" in l for l in lines)
    assert not any("sesión 0 " in l for l in lines)


def test_quit_sets_the_flag():
    assert ui.handle(_st(), "q")["quit"] is True


def test_enter_opens_detail_and_esc_returns():
    st = _st()
    st["sel"] = 2
    # the real loader reads from disk: swap in a fake one
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], real[1], real[2], lambda row: [f"línea {i}" for i in range(40)])
    try:
        st = ui.handle(st, "\r")
        assert st["mode"] == "detail" and st["detail"][0] == "línea 0"
        lines = [ui.strip_ansi(l) for l in ui.draw(st, 60, 12)]
        assert any("línea 3" in l for l in lines)

        st = ui.handle(st, "pgdn")
        assert st["dscroll"] > 0
        for _ in range(50):
            st = ui.handle(st, "pgdn")
        assert st["dscroll"] <= 40                     # no se pasa del final
        st = ui.handle(st, "\x1b")
        assert st["mode"] == "list" and st["sel"] == 2  # vuelve donde estaba
    finally:
        ui.TABS[SES] = real


def test_enter_does_nothing_on_a_panel_tab():
    st = ui.new_state()                 # home: no tiene detalle
    st["rows"] = ["una línea de panel"]
    assert ui.handle(st, "\r")["mode"] == "list"


def test_enter_gated_on_formatter_even_if_opener_exists():
    # a None formatter means "panel without cursor": Enter must not open a
    # detail even when the opener is set.
    st = ui.new_state()
    st["tab"] = MEM
    st["rows"] = ["una línea de panel"]
    real = ui.TABS[MEM]
    ui.TABS[MEM] = (real[0], real[1], None, lambda row: ["no debería verse"])
    try:
        assert ui.handle(st, "\r")["mode"] == "list"
    finally:
        ui.TABS[MEM] = real


def test_detail_scroll_clamps_to_last_page_without_going_blank():
    st = _st()
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], real[1], real[2], lambda row: [f"línea {i}" for i in range(40)])
    try:
        st = ui.handle(st, "\r")
        for _ in range(50):                 # far more than the content
            st = ui.handle(st, "pgdn")
        lines = [ui.strip_ansi(l) for l in ui.draw(st, 60, 12)]
        assert any("línea 39" in l for l in lines)   # last visible line
        assert not all(l.strip() == "" for l in lines[2:10])  # body not empty
    finally:
        ui.TABS[SES] = real


def test_filter_types_backspaces_and_clears():
    st = _st()
    real = ui.TABS[SES]
    seen = []
    ui.TABS[SES] = (real[0], lambda s: seen.append(s["q"]) or
                    [r for r in _rows() if s["q"] in r["title"]], real[2], real[3])
    try:
        st = ui.handle(st, "/")
        assert st["mode"] == "search"
        for ch in "sesión 3":
            st = ui.handle(st, ch)
        assert st["q"] == "sesión 3"
        assert [r["title"] for r in st["rows"]] == ["sesión 3"]

        st = ui.handle(st, "\x08")               # backspace
        assert st["q"] == "sesión "
        st = ui.handle(st, "\r")                 # Enter fija el resultado
        assert st["mode"] == "list" and st["q"] == "sesión "

        st = ui.handle(st, "/")
        st = ui.handle(st, "\x1b")               # Esc limpia
        assert st["q"] == "" and st["mode"] == "list"
        assert len(st["rows"]) == 5
    finally:
        ui.TABS[SES] = real


def test_filter_prompt_is_visible_while_typing():
    st = _st()
    st["mode"], st["q"] = "search", "memo"
    assert "/memo" in ui.strip_ansi(ui.draw(st, 60, 12)[-1])


def test_active_filter_shows_in_list_bottom_bar_and_esc_clears_it():
    st = _st()
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], lambda s: [r for r in _rows() if s["q"] in r["title"]],
                    real[2], real[3])
    try:
        st = ui.handle(st, "/")
        for ch in "sesión 3":
            st = ui.handle(st, ch)
        st = ui.handle(st, "\r")           # fija el filtro, vuelve a modo lista
        assert st["mode"] == "list" and st["q"] == "sesión 3"
        bottom = ui.strip_ansi(ui.draw(st, 60, 12)[-1])
        assert "sesión 3" in bottom        # the active filter shows on the bar

        st = ui.handle(st, "\x1b")         # Esc en modo lista limpia el filtro
        assert st["q"] == "" and len(st["rows"]) == 5
        bottom2 = ui.strip_ansi(ui.draw(st, 60, 12)[-1])
        assert "sesión 3" not in bottom2
    finally:
        ui.TABS[SES] = real


def test_esc_at_the_top_level_does_nothing():
    st = _st()
    st["proj"], st["flat"] = None, True     # top level: no filter, no project
    st["sel"] = 2
    st = ui.handle(st, "\x1b")
    assert st["mode"] == "list" and st["sel"] == 2 and st["quit"] is False


def test_esc_goes_up_one_level_filter_first_then_project():
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], lambda s: _rows(3), real[2], real[3])
    try:
        st = _st()
        st["q"], st["sel"] = "algo", 2
        st = ui.handle(st, "\x1b")          # primero se va el filtro
        assert st["q"] == "" and st["proj"] == "projA" and st["sel"] == 0
        st["sel"] = 1
        st = ui.handle(st, "\x1b")          # then the project
        assert st["proj"] is None and st["sel"] == 0
        st = ui.handle(st, "\x1b")          # arriba de todo no hace nada
        assert st["proj"] is None
    finally:
        ui.TABS[SES] = real


def test_switching_tabs_resets_the_filter():
    st = _st()
    st["q"] = "algo"
    st = ui.handle(st, "right")
    assert st["q"] == ""
    st["q"] = "otro"
    st = ui.handle(st, "3")
    assert st["q"] == ""


def test_filter_letter_q_does_not_quit_while_typing():
    st = _st()
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], lambda s: [r for r in _rows() if s["q"] in r["title"]],
                    real[2], real[3])
    try:
        st = ui.handle(st, "/")
        for ch in "quiero":
            st = ui.handle(st, ch)
        assert st["q"] == "quiero"
        assert st["quit"] is False
    finally:
        ui.TABS[SES] = real


def test_ctrl_c_quits_even_while_in_search_mode():
    st = _st()
    st = ui.handle(st, "/")
    st = ui.handle(st, "\x03")
    assert st["quit"] is True


def test_fit_truncates_lines_longer_than_w():
    plain = "x" * 80
    out = ui.fit(plain, 60)
    assert len(out) == 60                  # sin ANSI, largo == columnas visibles
    assert out == "x" * 60

    colored = "\033[1m" + "y" * 80 + "\033[0m"
    out2 = ui.fit(colored, 60)
    assert len(ui.strip_ansi(out2)) == 60  # el color no cuenta como ancho
    assert ui.strip_ansi(out2) == "y" * 60


def test_memory_rows_flatten_projects_and_filter_by_text():
    real = ui.srv.list_memory
    try:
        ui.srv.list_memory = lambda: [
            {"project": "sto-agentic-os", "machines": ["PC"], "count": 2, "memories": [
                {"slug": "estado", "type": "project", "machine": "PC", "mtime": 2.0,
                 "description": "arquitectura del OS"},
                {"slug": "caveman", "type": "user", "machine": "NB", "mtime": 1.0,
                 "description": "cómo habla"}]},
            {"project": "monumental", "machines": ["NB"], "count": 1, "memories": [
                {"slug": "deploy", "type": "project", "machine": "NB", "mtime": 3.0,
                 "description": "cómo se sube"}]}]
        st = ui.new_state()
        st["tab"] = MEM

        # grouped by default: one row per project, most recent first
        grupos = ui.load_memory(st)
        assert [g["project"] for g in grupos] == ["monumental", "sto-agentic-os"]
        assert [g["n"] for g in grupos] == [1, 2]
        txt = ui.strip_ansi(ui.fmt_memory(grupos[0]))
        assert "monumental" in txt and "1 memoria" in txt

        # entering a project leaves only its memories, in 2 lines
        st["proj"] = "sto-agentic-os"
        rows = ui.load_memory(st)
        assert [r["slug"] for r in rows] == ["estado", "caveman"]     # mtime desc
        fila = ui.strip_ansi(ui.fmt_memory(rows[0])).split("\n")
        # the slug leads, the machine gets the right-hand column, and what the
        # memory is about rides underneath with its type and date
        assert "estado" in fila[0] and fila[0].rstrip().endswith("PC")
        assert fila[1].strip().endswith("arquitectura del OS")
        assert rows[0]["type"] in fila[1]

        # `a` flattens: every project together
        st["proj"], st["flat"] = None, True
        assert [r["slug"] for r in ui.load_memory(st)] == ["deploy", "estado", "caveman"]

        # filtering is flat too, with or without a project picked
        st["flat"], st["q"] = False, "arquitect"
        assert [r["slug"] for r in ui.load_memory(st)] == ["estado"]
    finally:
        ui.srv.list_memory = real


def test_memory_detail_reads_the_markdown():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "proj" / "PC"
        f.mkdir(parents=True)
        (f / "estado.md").write_text("# nota\ncuerpo", encoding="utf-8")
        real = ui.srv.KNOWLEDGE_MEMORY
        try:
            ui.srv.KNOWLEDGE_MEMORY = Path(d)
            lines = ui.detail_memory({"project": "proj", "machine": "PC", "slug": "estado"})
            assert lines == ["# nota", "cuerpo"]
            falta = ui.detail_memory({"project": "proj", "machine": "PC", "slug": "no-existe"})
            assert falta and "error" in falta[0]
        finally:
            ui.srv.KNOWLEDGE_MEMORY = real


def _skill(dirpath, name, desc="x"):
    from pathlib import Path
    d = Path(dirpath) / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\ncuerpo",
                                encoding="utf-8")


def _plugin_skill(claude_dir, plugin_key, name, desc="x"):
    """Install a plugin skill (source != 'personal') through installed_plugins.json,
    como hace de verdad claude plugin install — no bajo claude_dir/skills/."""
    import json
    from pathlib import Path
    install_root = Path(claude_dir) / "plugins" / "cache" / name
    install_root.mkdir(parents=True)
    (install_root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\ncuerpo", encoding="utf-8")
    manifest = Path(claude_dir) / "plugins" / "installed_plugins.json"
    manifest.write_text(json.dumps(
        {"plugins": {plugin_key: [{"installPath": str(install_root)}]}}), encoding="utf-8")


def test_parity_splits_local_only_repo_only_and_synced():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        local, repo = Path(d) / "claude", Path(d) / "config"
        _skill(local, "tackler")
        _skill(local, "caveman")
        _skill(repo / "skills", "caveman")
        _skill(repo / "skills", "apuntes-a-notion")
        _plugin_skill(local, "superpowers@official", "brainstorming")
        real = ui.srv.plugins_to_apply
        try:
            ui.srv.plugins_to_apply = lambda *a, **k: ({}, ["superpowers@official"])
            p = ui.parity(claude_dir=local, repo_config=repo)
            assert p["local_only"] == ["tackler"]
            assert p["repo_only"] == ["apuntes-a-notion"]
            assert p["sync"] == ["caveman"]
            assert p["plugins"] == ["superpowers@official"]
            # the central subtlety: a plugin skill does not travel in the repo,
            # so it must not leak into any side of the personal-skills diff.
            assert "brainstorming" not in p["local_only"]
            assert "brainstorming" not in p["repo_only"]
            assert "brainstorming" not in p["sync"]
        finally:
            ui.srv.plugins_to_apply = real


def _stub_home():
    """Siembra todo lo que home_lines() lee de disco/red. Devuelve los reales."""
    reales = (ui.srv.usage_snapshot, ui.srv.sync_status, ui.srv.list_machines,
              ui.parity, ui.srv.config_status, ui.last_sync,
              ui.cli.cached_sessions, ui.srv.list_memory, ui._personal_skills,
              ui.sync_preview)
    ui.srv.usage_snapshot = lambda detail=True: {"limits": [{"label": "sesión", "percent": 42,
                                                 "resetsAt": "2026-08-14T18:00:00Z"}],
                                     "daily": []}
    ui.srv.sync_status = lambda fetch=True, **k: {"remote": "git@x", "branch": "main",
                                                  "ahead": 3, "behind": 0, "dirty": False,
                                                  "machine": "PC", "fetchError": None}
    ui.srv.list_machines = lambda: {"PC": {"type": "desktop", "local": True},
                                    "NB": {"type": "laptop", "local": False}}
    ui.srv.config_status = lambda: [{"id": "skills", "localFiles": 38,
                                     "repoFiles": 34, "enabled": True}]
    ui.last_sync = lambda: "hace 2 días · NB"
    ui.parity = lambda **k: {"local_only": ["tackler"], "repo_only": ["apuntes"],
                             "sync": ["caveman"], "plugins": [], "modules": []}
    ui.cli.cached_sessions = lambda **k: ([{"project": "a"}, {"project": "a"},
                                           {"project": "b"}], {})
    ui.srv.list_memory = lambda: [{"project": "a", "machines": ["PC"], "count": 7,
                                   "memories": []}]
    ui._personal_skills = lambda d=None: {
        "tackler": {"id": "personal:tackler", "description": "hace cosas"},
        "caveman": {"id": "personal:caveman", "description": "habla raro"}}
    ui.sync_preview = lambda sy=None: (
        ui.classify(["knowledge/sessions/PC/a.jsonl",
                     "knowledge/memory/proj/PC/x.md",
                     "knowledge/config/skills/skills/tackler/SKILL.md"]),
        ui.classify([]))
    return reales


def _unstub_home(reales):
    (ui.srv.usage_snapshot, ui.srv.sync_status, ui.srv.list_machines,
     ui.parity, ui.srv.config_status, ui.last_sync,
     ui.cli.cached_sessions, ui.srv.list_memory, ui._personal_skills,
     ui.sync_preview) = reales


def _home_txt(st):
    """El home ya no son strings: son filas que pinta fmt_home()."""
    return [ui.strip_ansi(ui.fmt_home(r, st.get("w", 100))) for r in ui.home_lines(st)]


def test_home_panel_shows_sync_machines_and_only_the_drift():
    st = ui.new_state()
    reales = _stub_home()
    try:
        txt = "\n".join(_home_txt(st))
        assert "42%" in txt and "↑3" in txt
        assert "PC (esta)" in txt and "NB" in txt
        assert "hace 2 días" in txt
        assert "↑ tackler" in txt and "↓ apuntes" in txt
    finally:
        _unstub_home(reales)


def test_the_home_scrolls_one_line_per_arrow_instead_of_sitting_still():
    # the dashboard is almost all text: with the window following the cursor
    # only from the edge, the first few ↓ moved nothing and it looked stuck
    st = ui.new_state()
    reales = _stub_home()
    try:
        st = ui.reload_tab(st)
        assert len(st["rows"]) > 12          # hay de sobra para scrollear
        primeras = ui.draw(st, 80, 16)
        st = ui.handle(st, "down")
        assert ui.draw(st, 80, 16) != primeras and st["top"] == 1
        st = ui.handle(st, "down")
        ui.draw(st, 80, 16)                  # draw() es quien corre _clamp()
        assert st["top"] == 2
        st = ui.handle(st, "up")
        ui.draw(st, 80, 16)
        assert st["top"] == 1
        # at the very bottom the top pins itself and the cursor walks the modules
        for _ in range(len(st["rows"]) + 5):
            st = ui.handle(st, "down")
            ui.draw(st, 80, 16)
        assert st["sel"] == len(st["rows"]) - 1
        assert st["top"] == len(st["rows"]) - ui.visible_rows(st, 16)
    finally:
        _unstub_home(reales)


def test_one_arrow_lands_on_the_first_module_of_the_home():
    # the dashboard is 30+ lines of text with the modules at the end: moving one
    # line at a time it took twenty arrows to reach `skills`
    st = ui.new_state()
    reales = _stub_home()
    try:
        ui.parity = lambda **k: {"local_only": [], "repo_only": [], "sync": [],
                                 "plugins": [],
                                 "modules": [{"id": "skills", "localFiles": 3,
                                              "repoFiles": 3, "enabled": True},
                                             {"id": "agents", "localFiles": 1,
                                              "repoFiles": 1, "enabled": True}]}
        st = ui.reload_tab(st)
        mods = [i for i, r in enumerate(st["rows"])
                if isinstance(r, dict) and r.get("kind") == "module"]
        assert len(mods) == 2 and mods[0] > 10      # they sit well below the panel
        st = ui.handle(st, "down")
        assert st["sel"] == mods[0]
        st = ui.handle(st, "down")
        assert st["sel"] == mods[1]
        st = ui.handle(st, "up")
        assert st["sel"] == mods[0]
        st = ui.handle(st, "up")                    # above the first module: back to the top
        assert st["sel"] == 0
        # PgDn does not snap: it scrolls the panel so you can read it
        st = ui.handle(st, "pgdn")
        assert st["sel"] == 10
    finally:
        _unstub_home(reales)


def test_home_shows_the_banner_the_usage_bar_and_the_counters():
    st = ui.new_state()
    reales = _stub_home()
    try:
        lines = _home_txt(st)
        txt = "\n".join(lines)
        assert any("████" in l for l in lines[:6])    # el bloque del wordmark
        assert lines[0] == ""                        # margen contra las tabs
        assert "resetea " in txt
        # the bar: 42% of 18 cells → 8 full, 10 empty
        assert "█" * 8 + "░" * 10 in txt
        assert "3 sesiones" in txt and "2 proyectos" in txt
        assert "7 memorias" in txt and "2 skills" in txt and "2 máquinas" in txt
    finally:
        _unstub_home(reales)


def test_banner_rows_all_have_the_same_visible_width():
    # if one wordmark row measures differently, the letters below start in
    # another column and the block comes out crooked
    assert len({len(w) for w in ui.WORDMARK}) == 1
    assert len({len(w) for w in ui.FULL}) == 1
    # y cada glifo mide lo mismo, que es lo que mantiene el bloque derecho
    assert {len(r) for ch, g in ui._GLYPHS.items() if ch != " " for r in g} == {6}
    lineas = ui.banner(120)          # el nombre completo entra
    assert lineas[0] == ""
    assert len({len(ui.strip_ansi(l)) for l in lineas[1:]}) == 1


def test_bar_clamps_out_of_range_percentages():
    assert ui.strip_ansi(ui.bar(0, 10)) == "░" * 10
    assert ui.strip_ansi(ui.bar(None, 10)) == "░" * 10
    assert ui.strip_ansi(ui.bar(100, 10)) == "█" * 10
    assert ui.strip_ansi(ui.bar(140, 10)) == "█" * 10      # over-quota no desborda
    assert len(ui.strip_ansi(ui.bar(37, 10))) == 10


def test_reset_at_converts_utc_to_local_and_survives_junk():
    from datetime import datetime, timezone
    utc = datetime(2026, 8, 14, 18, 0, tzinfo=timezone.utc)
    assert ui._reset_at("2026-08-14T18:00:00Z") == f"resetea {utc.astimezone():%H:%M}"
    assert ui._reset_at(None) == ""
    assert ui._reset_at("2026-08-14") == ""
    assert ui._reset_at("mañana") == ""


def test_slash_does_nothing_on_a_panel_tab_without_formatter():
    # the home tab has no row formatter: filtering there would filter nothing
    # and every key would fire an expensive reload (~5 git subprocesses).
    st = ui.new_state()
    st = ui.handle(st, "/")
    assert st["mode"] == "list"


def test_slash_does_nothing_on_config_even_though_it_has_a_formatter():
    st = ui.new_state()
    st["tab"] = CFG
    assert ui.handle(st, "/")["mode"] == "list"


# ── config ──

def test_enter_cycles_the_accent_and_persists_it():
    with tempfile.TemporaryDirectory() as d:
        reales = (ui.i18n.PREFS, ui.ACCENT, ui.i18n.LANG)
        try:
            ui.i18n.PREFS = Path(d) / "sto-ui.json"
            ui.ACCENT, ui.i18n.LANG = "36", "es"
            st = ui.new_state()
            st["tab"] = CFG
            st["rows"] = [{"kind": "accent"}]
            st = ui.handle(st, "\r")
            assert ui.ACCENT == "32"                       # turquesa → verde
            assert "verde" in st["flash"]
            assert ui.i18n.get_prefs() == {"accent": "32"}  # it landed on disk
            ui.ACCENT = "36"
            assert ui.load_prefs() == ("32", "en")          # y se relee al arrancar
        finally:
            ui.i18n.PREFS, ui.ACCENT, ui.i18n.LANG = reales


def test_enter_cycles_the_language_and_translates_on_the_spot():
    with tempfile.TemporaryDirectory() as d:
        reales = (ui.i18n.PREFS, ui.ACCENT, ui.i18n.LANG)
        try:
            ui.i18n.PREFS = Path(d) / "sto-ui.json"
            ui.ACCENT, ui.i18n.LANG = "36", "es"
            assert ui.t("tab_sessions") == "Sesiones"
            st = ui.new_state()
            st["tab"] = CFG
            st["rows"] = [{"kind": "lang"}]
            st = ui.handle(st, "\r")
            assert ui.i18n.LANG == "en" and "en" in st["flash"]
            assert ui.t("tab_sessions") == "Sessions"       # traduce en caliente
            assert ui.i18n.get_prefs()["lang"] == "en"
            st = ui.handle(st, "\r")
            assert ui.i18n.LANG == "es"                     # cicla y vuelve
        finally:
            ui.i18n.PREFS, ui.ACCENT, ui.i18n.LANG = reales


def test_both_languages_define_the_same_keys():
    # a key missing in one language falls back to the other and mixes the frame
    assert set(ui.STRINGS["es"]) == set(ui.STRINGS["en"])
    assert all(v.strip() for v in ui.STRINGS["en"].values())
    assert all(v.strip() for v in ui.STRINGS["es"].values())


def test_t_falls_back_to_english_and_then_to_the_key_itself():
    real = ui.i18n.LANG
    try:
        ui.i18n.LANG = "es"
        assert ui.t("no_existe_esta_clave") == "no_existe_esta_clave"
        ui.STRINGS["es"].pop("no_data")
        assert ui.t("no_data") == "no data"           # falls back to English
        ui.STRINGS["es"]["no_data"] = "sin datos"
    finally:
        ui.i18n.LANG = real


def test_load_prefs_falls_back_when_the_file_is_junk_or_the_value_unknown():
    with tempfile.TemporaryDirectory() as d:
        reales = (ui.i18n.PREFS, ui.ACCENT, ui.i18n.LANG)
        try:
            ui.i18n.PREFS = Path(d) / "sto-ui.json"
            assert ui.load_prefs() == ("36", "en")      # sin archivo
            ui.i18n.PREFS.write_text("no soy json", encoding="utf-8")
            assert ui.load_prefs() == ("36", "en")
            ui.i18n.PREFS.write_text('{"accent": "99", "lang": "klingon"}',
                                     encoding="utf-8")
            assert ui.load_prefs() == ("36", "en")      # valores que no conocemos
        finally:
            ui.i18n.PREFS, ui.ACCENT, ui.i18n.LANG = reales


def test_enter_toggles_a_sync_module_both_ways():
    guardado = []
    reales = (ui.srv.get_sync_prefs, ui.srv.set_sync_prefs)
    try:
        ui.srv.get_sync_prefs = lambda: list(guardado)
        ui.srv.set_sync_prefs = lambda mods: guardado.__setitem__(slice(None), mods)
        st = ui.new_state()
        st["tab"] = CFG
        st["rows"] = [{"kind": "module", "id": "skills", "on": False}]
        st = ui.handle(st, "\r")
        assert guardado == ["skills"] and "sincroniza" in st["flash"]

        st["rows"] = [{"kind": "module", "id": "skills", "on": True}]
        st = ui.handle(st, "\r")
        assert guardado == [] and "no sincroniza" in st["flash"]
    finally:
        ui.srv.get_sync_prefs, ui.srv.set_sync_prefs = reales


def test_enter_on_a_text_row_of_config_does_nothing():
    st = ui.new_state()
    st["tab"] = CFG
    st["rows"] = [{"kind": "head", "text": "repo remoto"},
                  {"kind": "text", "text": "1. creá un repo"}]
    st["sel"] = 1
    st = ui.handle(st, "\r")
    assert st["mode"] == "list" and st["flash"] == ""


def test_config_rows_list_the_modules_and_the_remote_guide():
    reales = (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin)
    try:
        ui.srv.get_sync_prefs = lambda: ["skills"]
        ui.srv.CONFIG_MODULES = {"skills": (), "settings": ()}
        ui._origin = lambda: "git@github.com:yo/sto.git"
        # guide=True: the steps are folded away by default, and this is the test
        # about what they say, not about whether they start open
        rows = ui.load_config(dict(ui.new_state(), guide=True))
        txt = "\n".join(ui.strip_ansi(ui.fmt_config(r, 100)) for r in rows)
        assert "Color de acento" in txt
        assert "[x] skills" in txt and "[ ] settings" in txt
        assert "git@github.com:yo/sto.git" in txt
        assert "git push -u origin main" in txt
    finally:
        ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin = reales


def test_config_says_when_there_is_no_remote_yet():
    reales = (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin, ui._upstream)
    try:
        ui.srv.get_sync_prefs = lambda: []
        ui.srv.CONFIG_MODULES = {}
        ui._origin = ui._upstream = lambda: ""
        txt = "\n".join(ui.strip_ansi(ui.fmt_config(r, 100))
                        for r in ui.load_config(ui.new_state()))
        assert txt.count("todavía no configurado") == 2   # origin and upstream
    finally:
        (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES,
         ui._origin, ui._upstream) = reales


def test_config_teaches_the_two_remotes_and_how_to_update():
    """The setup used to say `git remote add origin` on a clone that already
    has one, and said nothing about updates. Both live here, next to the two
    remotes they are about."""
    reales = (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin, ui._upstream)
    try:
        ui.srv.get_sync_prefs = lambda: []
        ui.srv.CONFIG_MODULES = {}
        ui._origin = lambda: "git@github.com:yo/mio.git"
        ui._upstream = lambda: "https://github.com/quien/sto-agentic-os.git"
        txt = "\n".join(ui.strip_ansi(ui.fmt_config(r, 100))
                        for r in ui.load_config(dict(ui.new_state(), guide=True)))
        assert "git remote rename origin upstream" in txt
        assert "git remote add origin" in txt
        assert txt.index("rename origin upstream") < txt.index("remote add origin")
        assert "sto update --apply" in txt and "sto update --link" in txt
        assert "yo/mio" in txt and "quien/sto-agentic-os" in txt
        # the step everybody got stuck on: WHERE do I run this. Compared on the
        # whitespace-collapsed text, because these lines are wrapped to the
        # terminal and a phrase can straddle two of them.
        plano = " ".join(txt.split())
        assert "en la carpeta que clonaste" in plano
        assert "El repo nuevo de GitHub NO se clona" in plano
        assert "TU repo privado" in plano        # the other machine clones yours
        # and the reassurance that lets you PUSH on a machine full of memories
        assert "sin publicar nunca se pisan" in plano
    finally:
        (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES,
         ui._origin, ui._upstream) = reales


def test_the_memory_tab_pins_a_graph_button_and_g_opens_it():
    st = ui.new_state()
    st["tab"] = MEM
    reales = (ui.srv.list_memory, ui.cli.open_memory_graph)
    abiertos = []
    try:
        ui.srv.list_memory = lambda: [{"project": "p", "machines": ["PC"], "count": 1,
                                       "memories": [{"slug": "x", "type": "project",
                                                     "machine": "PC", "mtime": 1.0,
                                                     "description": "una memoria"}]}]
        ui.cli.open_memory_graph = lambda: abiertos.append(1) or {"message": "grafo abierto"}
        st = ui.reload_tab(st)
        boton = "\n".join(ui.strip_ansi(l) for l in ui.pinned_of(st, 24))
        assert "[g]" in boton and "GRAFO" in boton
        st = ui.handle(st, "g")
        assert abiertos == [1] and "grafo abierto" in st["flash"]
    finally:
        ui.srv.list_memory, ui.cli.open_memory_graph = reales


# ── render ──

def test_diff_frame_only_repaints_the_lines_that_changed():
    prev = ["a", "b", "c"]
    assert ui.diff_frame(["a", "b", "c"], prev) == ""       # identical frame: nothing
    out = ui.diff_frame(["a", "B", "c"], prev)
    assert out == "\033[2;1HB"                              # solo la fila 2
    # a resize cannot be diffed: clear and repaint the whole thing
    full = ui.diff_frame(["a", "b"], prev)
    assert full.startswith("\033[2J") and "\033[1;1Ha" in full and "\033[2;1Hb" in full


def test_enter_and_exit_sequences_use_the_alternate_screen():
    # without the alt screen every frame stays in the scrollback and mouse
    # scrolling shows old frames stacked; with autowrap on, the last cell scrolls
    assert "\033[?1049h" in ui.ENTER_TUI and "\033[?7l" in ui.ENTER_TUI
    assert "\033[?1049l" in ui.EXIT_TUI and "\033[?7h" in ui.EXIT_TUI
    assert "\033[?25h" in ui.EXIT_TUI          # el cursor vuelve siempre


def test_whitespace_only_query_does_not_filter_memory():
    real = ui.srv.list_memory
    try:
        ui.srv.list_memory = lambda: [
            {"project": "p", "machines": ["PC"], "count": 1, "memories": [
                {"slug": "a", "type": "project", "machine": "PC", "mtime": 1.0,
                 "description": "x"}]}]
        st = ui.new_state()
        st["tab"], st["q"] = MEM, "   "
        assert len(ui.load_memory(st)) == 1     # espacios == sin filtro
    finally:
        ui.srv.list_memory = real


def test_empty_state_tells_loading_apart_from_nothing_there():
    """`sin datos` on a tab that has not run yet is a lie, and it is the first
    thing you saw every time you came back to the home."""
    st = _st()
    st["rows"], st["loaded_at"] = [], 0.0
    txt = "\n".join(ui.strip_ansi(l) for l in ui.draw(st, 60, 12))
    assert "cargando" in txt and "sin datos" not in txt

    st["loaded_at"] = 1.0                      # it ran, and there was nothing
    txt = "\n".join(ui.strip_ansi(l) for l in ui.draw(st, 60, 12))
    assert "sin datos" in txt

    st["q"] = "algo"
    txt2 = "\n".join(ui.strip_ansi(l) for l in ui.draw(st, 60, 12))
    assert "sin resultados" in txt2


def test_coming_back_to_a_tab_shows_its_last_rows_at_once():
    """Switching tabs used to blank the rows, so returning to the home paid
    1.3 s of git and dry runs with an empty screen up. Driven through the keys,
    because that is the path that was broken."""
    real = ui.TABS
    try:
        # a loader that counts how often it actually has to run
        corridas = []
        ui.TABS = list(ui.TABS)
        ui.TABS[MEM] = (ui.TABS[MEM][0],
                        lambda st: (corridas.append(1), ["a", "b", "c"])[1],
                        ui.TABS[MEM][2], ui.TABS[MEM][3])
        st = ui.new_state()
        st["tab"] = MEM
        st = ui.reload_tab(st)
        assert st["rows"] == ["a", "b", "c"] and len(corridas) == 1

        st = ui.handle(st, "5")                 # off to help
        assert st["tab"] != MEM
        st = ui.handle(st, "3")                 # and back
        assert st["tab"] == MEM
        # the rows are already there, on the keystroke, without re-running it
        assert st["rows"] == ["a", "b", "c"]
        assert len(corridas) == 1
    finally:
        ui.TABS = real


def test_a_tab_never_visited_comes_back_empty_not_stale():
    st = ui.new_state()
    st["tab"] = MEM
    assert ui._recall(st) is False
    assert st["rows"] == [] and st["loaded_at"] == 0.0


def test_the_badge_row_can_be_reached_and_toggled_with_the_keys():
    """It shipped dead: `badge` was missing from SELECTABLE, so `_snap` walked
    straight past the row and `↵` could never land on it."""
    reales = (ui.srv.badge_status, ui.srv.set_badge,
              ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES)
    puesto = []
    try:
        estado = {"on": False}
        ui.srv.badge_status = lambda: {"on": estado["on"], "other": "otro.ps1"}
        ui.srv.set_badge = lambda on: (puesto.append(on),
                                       estado.__setitem__("on", on), {"ok": True})[2]
        ui.srv.get_sync_prefs = lambda: []
        ui.srv.CONFIG_MODULES = {}
        st = ui.new_state()
        st["tab"] = CFG
        st = ui.reload_tab(st)
        for _ in range(12):                     # walk down like a user does
            if st["rows"][st["sel"]].get("kind") == "badge":
                break
            st = ui.handle(st, "down")
        else:
            raise AssertionError("the cursor never lands on the badge row")
        st = ui.handle(st, "\r")
        assert puesto == [True] and estado["on"] is True
        assert "badge" in st["flash"]
    finally:
        (ui.srv.badge_status, ui.srv.set_badge,
         ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES) = reales


def test_only_the_plain_view_is_cached():
    """A drilled-in or filtered list belongs to the keys that built it: handing
    it back on a later visit would show a filter the user never re-typed."""
    st = _st()
    st["tab"], st["rows"] = MEM, ["x"]
    st["proj"] = "algo"
    assert ui._plain_view(st) is False
    st["proj"], st["q"] = None, "  "           # blanks are not a filter
    assert ui._plain_view(st) is True


def test_no_frame_line_ever_runs_past_the_terminal_edge():
    """`draw` closes with a `fit(l, w)` over the whole frame, and that is the
    only thing standing between a row the loaders got wrong and a line that
    overwrites the edge (autowrap off) or wraps and pushes the frame down one
    (autowrap on). Nothing else pinned it."""
    st = ui.new_state()
    st["tab"] = ui.HELP
    st["loaded_at"] = 1.0
    st["rows"] = [ui._txt("x" * 400), ui._txt("corta")]
    for w, h in ((80, 12), (44, 20), (30, 8)):
        lineas = ui.draw(st, w, h)
        assert len(lineas) == h
        assert all(len(ui.strip_ansi(l)) <= w for l in lineas), w
    # and with a scrollbar up, which takes the other branch
    st["rows"] = [ui._txt("y" * 400)] * 60
    assert all(len(ui.strip_ansi(l)) <= 80 for l in ui.draw(st, 80, 12))


def test_manifest_lines_marks_truncated_skills_list():
    data = ui.classify([f"knowledge/config/skills/skills/skill{i}/SKILL.md"
                        for i in range(10)])
    txt = "\n".join(ui.strip_ansi(l) for l in ui.manifest_lines("push", data))
    assert "…+2" in txt                          # 10 skills, se muestran 8


def test_confirm_prompt_shows_in_bottom_bar_even_when_body_is_short():
    st = ui.new_state()
    st["confirm"] = {"kind": "push"}
    st["manifest"] = ui.manifest_lines("push",
                                       ui.classify(["knowledge/sessions/PC/a.jsonl"]))
    lines = [ui.strip_ansi(l) for l in ui.draw(st, 60, 6)]   # h chico: bh recorta el body
    assert "confirmar" in lines[-1]


def test_p_flashes_error_instead_of_crashing_on_oserror():
    st = ui.new_state()
    real = ui.srv.sync_stage
    try:
        def boom():
            raise OSError("disco lleno")
        ui.srv.sync_stage = boom
        st = ui.handle(st, "p")
        assert st["confirm"] is None
        assert "disco lleno" in st["flash"]
    finally:
        ui.srv.sync_stage = real


def test_the_home_says_what_would_push_and_what_would_pull():
    reales = _stub_home()
    try:
        st = ui.new_state()
        txt = "\n".join(_home_txt(st))
        assert "Para subir" in txt and "Para bajar" in txt
        # the breakdown says what the files are, not only how many
        assert "1 sesiones" in txt and "1 memorias" in txt and "1 skills" in txt
        assert "nada" in txt                       # para bajar no hay nada
        # and the button number is that total, not the commit count
        assert "PUSH   3" in ui.strip_ansi(st["pinned"][1])
        assert "PULL   0" in ui.strip_ansi(st["pinned"][1])
    finally:
        _unstub_home(reales)


def test_f_forces_fetch_only_on_the_home_tab():
    st = ui.new_state()
    st["tab"] = SES
    st = ui.handle(st, "f")
    assert st["fetch"] is False
    st["tab"] = ui.HOME
    st = ui.handle(st, "f")
    assert st["fetch"] is True


def test_last_sync_falls_back_to_question_mark_without_separator():
    real = ui.srv._git
    try:
        # a commit that did not come from sync_push (no "sync from <machine>")
        hace_3_dias = time.time() - 3 * 86400
        ui.srv._git = lambda *a, **k: (0, f"{hace_3_dias}|fix: ajuste manual en knowledge")
        assert ui.last_sync() == "hace 3 d · ?"
        # git's %cr printed in English no matter the language: now we format it
        ui.srv._git = lambda *a, **k: (0, "no-es-un-timestamp|sync from NB")
        assert ui.last_sync() == ui.t("never_synced")
    finally:
        ui.srv._git = real


def _config_st(w=96):
    st = ui.new_state()
    st["tab"], st["w"] = CFG, w
    return ui.reload_tab(st)


def test_config_folds_the_setup_guide_so_the_screen_fits():
    """It did not fit, and the overflow was not only cosmetic: the cursor lands
    only on SELECTABLE rows, the window follows the cursor, and the last
    selectable row was a module — so the whole tail was unreachable."""
    real = ui.srv.get_sync_prefs
    try:
        ui.srv.get_sync_prefs = lambda: ["skills"]
        st = _config_st()
        assert not any(r.get("kind") == "sub" for r in st["rows"])   # plegada
        guia = [i for i, r in enumerate(st["rows"]) if r.get("kind") == "guide"]
        assert guia == [len(st["rows"]) - 1]     # y el toggle es la última fila
        plegadas = len(st["rows"])

        # ↵ sobre ella la despliega, y deja otro toggle al final para poder bajar
        st["sel"] = guia[0]
        st = ui.handle(st, "\r")
        assert st["guide"] is True
        assert len(st["rows"]) > plegadas
        assert any(r.get("kind") == "sub" for r in st["rows"])
        assert st["rows"][-1]["kind"] == "guide"
        # el cursor se queda en el toggle que apretaste, no salta al final
        assert st["rows"][st["sel"]]["kind"] == "guide"

        # y desde el toggle de abajo se vuelve a plegar sin dejar `sel` colgado
        st["sel"] = len(st["rows"]) - 1
        st = ui.handle(st, "\r")
        assert st["guide"] is False and len(st["rows"]) == plegadas
        assert 0 <= st["sel"] < len(st["rows"])
        assert st["rows"][st["sel"]]["kind"] == "guide"
    finally:
        ui.srv.get_sync_prefs = real


def test_config_scrolls_to_the_last_row_and_back_to_the_first():
    """`_clamp` derives the window from the cursor, so a tail of non-selectable
    rows could never be scrolled to. The guide toggle sits at the end precisely
    so the cursor can drag the window all the way down."""
    real = ui.srv.get_sync_prefs
    try:
        ui.srv.get_sync_prefs = lambda: []
        st = _config_st()
        h = 16                                    # a propósito corta: no entra
        vis = ui.visible_rows(st, h)
        assert len(st["rows"]) > vis
        for _ in range(len(st["rows"]) + 5):
            st = ui.handle(st, "down")
            ui.draw(st, 96, h)                    # draw() es quien corre _clamp
        assert st["top"] == len(st["rows"]) - vis     # el fondo, visible
        assert "Guía" in ui.strip_ansi(ui.fmt_config(st["rows"][-1], 96))
        for _ in range(len(st["rows"]) + 5):
            st = ui.handle(st, "up")
            ui.draw(st, 96, h)
        assert st["top"] == 0                        # y se vuelve al principio
    finally:
        ui.srv.get_sync_prefs = real


class _AliveThread:
    def is_alive(self):
        return True


def test_a_background_reload_clears_the_message_it_put_up():
    """The bug: `f` put up "fetcheando…" and only an error ever replaced it, so
    a finished fetch looked exactly like a hung one until an unrelated keypress
    wiped the line."""
    st = ui.new_state()
    st["tab"], st["rows"] = SES, _rows(2)
    st["flash"], st["fetch"] = ui.t("fetching"), True
    try:
        ui._BG["thread"], ui._BG["box"] = None, (_rows(3), [], "", ui._view_key(st))
        st = ui.bg_reload(st)
        assert st["flash"] == ""
        assert len(st["rows"]) == 3 and st["fetch"] is False
        # an error still gets said
        ui._BG["box"] = ([], [], "error: git no responde", ui._view_key(st))
        st = ui.bg_reload(st)
        assert st["flash"] == "error: git no responde"
    finally:
        ui._BG["thread"], ui._BG["box"] = None, None


def test_a_reload_that_lands_on_another_tab_is_dropped():
    """The crash: load the sessions tab, switch to memory before it comes back,
    and the session rows landed in the memory tab -> `KeyError: 'type'` in
    fmt_memory. The rows of a screen you already left are worth nothing."""
    st = ui.new_state()
    st["tab"], st["rows"] = MEM, _rows(2)
    viejas = ui.new_state()
    viejas["tab"] = SES
    try:
        ui._BG["thread"] = None
        ui._BG["box"] = (_rows(9), [], "", ui._view_key(viejas))   # from the other tab
        st = ui.bg_reload(st)
        assert len(st["rows"]) == 2, "the memory tab keeps its own rows"
        # entering a project is another view of the same tab
        dentro = dict(st, proj="algo")
        ui._BG["box"] = (_rows(9), [], "", ui._view_key(dentro))
        st = ui.bg_reload(st)
        assert len(st["rows"]) == 2, st["rows"]
        # and the answer to the screen that IS up does land
        ui._BG["thread"] = None
        ui._BG["box"] = (_rows(9), [], "", ui._view_key(st))
        st = ui.bg_reload(st)
        assert len(st["rows"]) == 9
    finally:
        ui._BG["thread"], ui._BG["box"] = None, None


def test_changing_the_accent_repaints_what_was_cached():
    """The bug: the home rows and the button strip are rendered strings with the
    ANSI inside, so after picking another accent the logo, the buttons and the
    bars kept the old colour until each tab expired on its own."""
    real = ui.ACCENT
    try:
        ui.set_accent("36")
        st = ui.new_state()
        st["tab"], st["w"] = CFG, 100
        st["cache"][ui.HOME] = ([ui.cli.c("logo", "36")], [ui.cli.c("[p]", "36")], 1.0)
        st["rows"] = ui.load_config(st)
        st["sel"] = next(i for i, r in enumerate(st["rows"]) if r["kind"] == "accent")
        st = ui.config_activate(st)
        assert ui.ACCENT != "36", "the key cycles the accent"
        assert st["cache"] == {}, st["cache"]
        assert st["loaded_at"] == 0.0
    finally:
        ui.set_accent(real)


def test_the_message_spins_while_the_work_is_really_running():
    st = ui.new_state()
    st["tab"], st["rows"] = SES, _rows(2)
    st["flash"] = ui.t("fetching")
    real = ui._BG["thread"]
    try:
        ui._BG["thread"] = _AliveThread()
        assert ui.busy() is True
        vistos = set()
        for f in range(len(ui.SPIN)):
            st["frame"] = f
            bottom = ui.strip_ansi(ui.draw(st, 80, 12)[-1])
            assert ui.t("fetching") in bottom
            vistos.add(bottom.strip()[0])
        assert vistos == set(ui.SPIN)          # se mueve de verdad, no es un adorno fijo
        # y tick() sigue moviendo el cuadro mientras haya trabajo, que es lo que
        # hace que run() marque la pantalla como sucia y repinte
        st["loaded_at"], st["frame"] = time.monotonic(), -1
        assert ui.tick(st)["frame"] >= 0
    finally:
        ui._BG["thread"] = real
    # sin trabajo en curso no hay spinner: el mensaje sale tal cual
    assert ui.strip_ansi(ui.draw(st, 80, 12)[-1]).strip()[0] not in ui.SPIN


def test_a_finished_update_asks_for_a_restart_and_keeps_asking():
    """`u` merges new code into the repo, but this process already imported the
    old one. A flash would be gone on the next repaint, with nothing changed."""
    st = ui.new_state()
    assert st["updated"] is False
    st["job"] = {"kind": "update", "steps": [], "res": {"message": "3 commits"}}
    st = ui.job_tick(st)
    assert st["updated"] is True

    reales = _stub_home()
    try:
        linea = [l for l in _home_txt(st) if "reabrí" in l]
        assert len(linea) == 1, _home_txt(st)
        assert "sto ui" in linea[0]
        # y sale en el color de aviso, no en el acento (que el usuario cambia)
        pintadas = [l for l in ui.home_lines(st)
                    if f"\033[{ui.NOTICE}m" in (l["text"] if isinstance(l, dict) else l)]
        assert len(pintadas) == 1
        assert ui.NOTICE not in dict(ui.ACCENTS).values()
        # sigue ahí después de recargar: solo se va al reiniciar el proceso
        st["loaded_at"] = 0.0
        assert any("reabrí" in l for l in _home_txt(st))
    finally:
        _unstub_home(reales)


def test_the_update_key_asks_again_instead_of_trusting_the_cache():
    """Same bug from the other end: the home caches the update check for five
    minutes, so pressing `u` right after a release said "already on the latest
    version" without asking anyone."""
    real, pedidos = ui.srv.update_status, []
    try:
        ui._UPDATE["ts"], ui._UPDATE["data"] = ui.time.monotonic(), {
            "available": 0, "linked": True, "log": [], "error": None}

        def fake(fetch=True, force=False):
            pedidos.append(force)
            return {"available": 2 if force else 0, "linked": True,
                    "log": ["aaa nuevo", "bbb nuevo"], "error": None}
        ui.srv.update_status = fake
        st = ui.new_state()
        st = ui.handle(st, "u")
        assert pedidos == [True], pedidos
        assert st["confirm"] == {"kind": "update"}, st
    finally:
        ui.srv.update_status = real
        ui._UPDATE["ts"], ui._UPDATE["data"] = 0.0, {}


def test_a_failed_update_has_nothing_to_restart_for():
    st = ui.new_state()
    st["job"] = {"kind": "update", "steps": [], "res": {"error": "merge conflict"}}
    st = ui.job_tick(st)
    assert st["updated"] is False
    assert st["flash"] == "merge conflict"


def test_the_relative_time_is_translated_and_rounds_down():
    assert ui.ago(time.time()) == "recién"
    assert ui.ago(time.time() - 90) == "hace 1 min"
    assert ui.ago(time.time() - 3 * 3600 - 59 * 60) == "hace 3 h"   # no redondea para arriba
    assert ui.ago(time.time() - 2 * 86400) == "hace 2 d"
    assert ui.ago(None) == "nunca"
    assert ui.ago(time.time() + 500) == "recién"       # un reloj adelantado no da negativo


def test_fetch_moves_the_checked_age_and_the_sync_line_does_not():
    """The confusion this replaces: one relative time stood for both the age of
    ↑↓ and the age of the last sync, so pressing FETCH — which writes no commit
    — appeared to do nothing at all."""
    real = ui.srv.REPO_ROOT
    try:
        with tempfile.TemporaryDirectory() as d:
            ui.srv.REPO_ROOT = Path(d)
            assert ui.checked_ago() == "nunca"          # sin FETCH_HEAD todavía
            (Path(d) / ".git").mkdir()
            (Path(d) / ".git" / "FETCH_HEAD").write_text("", encoding="utf-8")
            assert ui.checked_ago() == "recién"         # lo que hace un fetch recién corrido
    finally:
        ui.srv.REPO_ROOT = real


def test_classify_groups_paths_by_meaning():
    out = ui.classify([
        "knowledge/config/skills/skills/tackler/SKILL.md",
        "knowledge/config/skills/skills/tackler/refs/x.md",
        "knowledge/config/skills/skills/humanizer/SKILL.md",
        "knowledge/config/settings/settings.json",
        "knowledge/config/plugins/plugins.json",
        "knowledge/memory/sto-agentic-os/PC/estado.md",
        "knowledge/memory/sto-agentic-os/PC/otra.md",
        "knowledge/memory/monumental/NB/deploy.md",
        "knowledge/sessions/PC/aaa.jsonl",
        "knowledge/sessions/PC/bbb.jsonl",
        "vault/wiki/nota.md",
    ])
    assert out["skills"] == ["tackler", "humanizer"]       # sin repetir
    assert out["config"] == ["settings", "plugins"]
    assert out["memories"] == {"sto-agentic-os": 2, "monumental": 1}
    assert out["sessions"] == 2 and out["vault"] == 1


def test_manifest_lines_name_what_travels():
    txt = "\n".join(ui.strip_ansi(l) for l in ui.manifest_lines("push", ui.classify([
        "knowledge/config/skills/skills/tackler/SKILL.md",
        "knowledge/memory/sto-agentic-os/PC/estado.md"])))
    assert "push a origin" in txt
    assert "tackler" in txt and "sto-agentic-os" in txt
    assert "confirmar" in txt


def test_manifest_lines_says_nothing_to_sync_when_empty():
    vacio = ui.classify([])
    txt = "\n".join(ui.strip_ansi(l) for l in ui.manifest_lines("push", vacio))
    assert "nada para sincronizar" in txt
    assert "confirmar" in txt


def _wait_job(st, limite=5.0):
    """Corre `tick()` hasta que el hilo del push/pull termina."""
    fin = time.monotonic() + limite
    while st["job"] and time.monotonic() < fin:
        st = ui.tick(st)
    assert st["job"] is None, "the job never finished"
    return st


def test_p_asks_before_pushing_and_esc_cancels():
    st = ui.new_state()
    llamadas = []
    reales = (ui.srv.sync_stage, ui.srv.sync_push)
    try:
        ui.srv.sync_stage = lambda: {"paths": ["knowledge/sessions/PC/a.jsonl"],
                                     "sessions": 1, "config": 0, "memory": 0}
        ui.srv.sync_push = lambda progress=None: llamadas.append("push") or {
            "ok": True, "message": "pushed 1 commit(s)"}
        st = ui.handle(st, "p")
        assert st["confirm"]["kind"] == "push" and llamadas == []
        st = ui.handle(st, ESC)
        assert st["confirm"] is None and llamadas == []

        st = ui.handle(st, "p")
        st = ui.handle(st, ENTER)
        st = _wait_job(st)
        assert llamadas == ["push"]
        assert "pushed 1 commit(s)" in st["flash"]
        assert st["confirm"] is None
    finally:
        ui.srv.sync_stage, ui.srv.sync_push = reales


def test_the_push_draws_its_steps_while_it_runs_instead_of_freezing():
    st = ui.new_state()
    soltar = threading.Event()
    real = ui.srv.sync_push
    try:
        def lento(progress=None):
            progress("s_sessions")
            progress("s_push")
            soltar.wait(5)
            return {"ok": True, "message": "pushed 1 commit(s)"}

        ui.srv.sync_push = lento
        st["confirm"] = {"kind": "push"}
        st = ui.handle(st, ENTER)
        fin = time.monotonic() + 5
        while len(st["job"]["steps"]) < 2 and time.monotonic() < fin:
            time.sleep(0.005)
        st = ui.tick(st)
        panel = "\n".join(ui.strip_ansi(l) for l in ui.draw(st, 80, 20))
        assert "exportando sesiones" in panel and "subiendo a origin" in panel
        assert "✓ exportando sesiones" in panel          # el paso cerrado
        assert any(c + " subiendo" in panel for c in ui.SPIN)  # el que corre, girando
        # and keys do nothing until it is done
        assert ui.handle(st, "q")["quit"] is False
        soltar.set()
        st = _wait_job(st)
        assert "pushed 1 commit(s)" in st["flash"] and st["job"] is None
    finally:
        soltar.set()
        ui.srv.sync_push = real


def test_pull_shows_incoming_and_reports_errors():
    st = ui.new_state()
    real = ui.srv.sync_incoming
    try:
        ui.srv.sync_incoming = lambda: {"paths": [], "error": "fetch failed: sin red"}
        st = ui.handle(st, "l")
        assert st["confirm"] is None
        assert "sin red" in st["flash"]
    finally:
        ui.srv.sync_incoming = real


def test_header_shows_usage_and_sync_on_the_right():
    st = ui.new_state()
    real = ui.status_summary
    try:
        ui.status_summary = lambda: "uso 42%  ↑3"
        line = ui.strip_ansi(ui.draw(st, 70, 10)[0])
        assert line.startswith("  Home ")  # la activa va con su relleno
        assert "Config" in line            # all four tabs are on the bar
        assert line.rstrip().endswith("uso 42%  ↑3")
        assert len(line) == 70
    finally:
        ui.status_summary = real


# ── grouping by project ──

def test_sessions_open_grouped_and_enter_drills_into_one_project():
    todas = _rows(3, "projA") + _rows(2, "projB")
    real = ui.cli.cached_sessions
    try:
        ui.cli.cached_sessions = lambda **k: (todas, {})
        st = ui.new_state()
        st["tab"] = SES
        st = ui.reload_tab(st)
        assert [r["kind"] for r in st["rows"]] == ["project", "project"]
        assert {r["project"] for r in st["rows"]} == {"projA", "projB"}

        st["sel"] = [r["project"] for r in st["rows"]].index("projB")
        st = ui.handle(st, "\r")            # ↵ entra al proyecto
        assert st["proj"] == "projB" and st["sel"] == 0
        assert len(st["rows"]) == 2 and all(r["kind"] == "session" for r in st["rows"])

        st = ui.handle(st, "\r")            # ↵ inside does open the detail
        assert st["mode"] == "detail"
    finally:
        ui.cli.cached_sessions = real


def test_a_flattens_every_project_and_toggles_back():
    todas = _rows(3, "projA") + _rows(2, "projB")
    real = ui.cli.cached_sessions
    try:
        ui.cli.cached_sessions = lambda **k: (todas, {})
        st = ui.new_state()
        st["tab"] = SES
        st = ui.handle(st, "a")
        assert st["flat"] is True and len(st["rows"]) == 5
        st = ui.handle(st, "a")
        assert st["flat"] is False and len(st["rows"]) == 2   # vuelve a proyectos
    finally:
        ui.cli.cached_sessions = real


def test_g_toggles_agents_only_on_the_sessions_tab():
    st = ui.new_state()
    st["tab"] = SES
    assert ui.handle(st, "g")["agents"] is True
    st["tab"] = MEM
    st["agents"] = False
    assert ui.handle(st, "g")["agents"] is False


def test_group_rows_count_and_use_the_most_recent_activity():
    filas = [{"project": "a", "mtime": 10.0}, {"project": "a", "mtime": 30.0},
             {"project": "b", "mtime": 20.0}]
    g = ui.group_by_project(filas, "n_sessions")
    assert [x["project"] for x in g] == ["a", "b"]      # a is more recent (30)
    assert [x["n"] for x in g] == [2, 1]
    assert g[0]["mtime"] == 30.0
    assert "2 sesiones" in ui.strip_ansi(ui.fmt_project(g[0]))


def test_project_rows_say_singular_and_clip_long_names():
    uno = ui.group_by_project([{"project": "p", "mtime": 0.0}], "n_sessions")[0]
    assert "1 sesión" in ui.strip_ansi(ui.fmt_project(uno))
    una = ui.group_by_project([{"project": "p", "mtime": 0.0}], "n_memories")[0]
    assert "1 memoria" in ui.strip_ansi(ui.fmt_project(una))

    # a long name must not push the counter column
    largo = ui.group_by_project([{"project": "L" * 60, "mtime": 0.0}], "n_sessions")[0]
    corto = ui.group_by_project([{"project": "x", "mtime": 0.0}], "n_sessions")[0]
    col = lambda r: ui.strip_ansi(ui.fmt_project(r)).index("1 sesión")
    assert col(largo) == col(corto)


def test_project_rows_also_occupy_exactly_two_lines():
    # measuring differently than a session would make ROW_H lie inside a project
    g = ui.group_by_project([{"project": "a", "mtime": 0.0}], "n_sessions")
    assert len(ui.fmt_project(g[0]).split("\n")) == ui.ROW_H[SES] == 2


def test_the_header_breadcrumb_names_the_open_project():
    st = _st()
    assert "› projA" in ui.strip_ansi(ui.draw(st, 80, 12)[0])
    st["proj"] = None
    assert "›" not in ui.strip_ansi(ui.draw(st, 80, 12)[0])


# ── sync buttons ──

def test_sync_buttons_are_accented_when_there_is_something_to_do():
    encendido = ui.sync_buttons({"ahead": 3, "behind": 0, "dirty": False}, 100)
    txt = "\n".join(ui.strip_ansi(l) for l in encendido)
    assert "[p]" in txt and "PUSH" in txt and "[l]" in txt and "PULL" in txt
    assert len(encendido) == 3
    # push has pending commits → accent; pull has nothing → dim
    assert f"\033[{ui.ACCENT}m" in encendido[1]
    assert f"\033[{ui.cli.DIM}m" in encendido[1]


def test_pending_items_enable_the_buttons_with_git_already_in_sync():
    """The bug this replaces: a repo with nothing ahead/behind painted both
    buttons dim while the panel above showed `158 local . 149 in repo` in
    yellow. Being level with GitHub says nothing about whether the config the
    repo carries is installed on THIS machine."""
    sy = {"ahead": 0, "behind": 0, "dirty": False}
    accent = f"\033[{ui.ACCENT}m"
    # BUTTONS_W and not 100: this asks about the colour of PUSH/PULL, and at a
    # wide width the always-lit FETCH box shares the line with them
    w = ui.BUTTONS_W
    def tira(**kw):
        return "\n".join(ui.sync_buttons(sy, w, **kw))
    assert accent not in tira(up=0, down=0)
    assert accent in tira(up=3, down=0)
    assert accent in tira(up=0, down=3)


def test_the_strip_says_it_is_synced_only_when_nothing_is_pending():
    """Two dim buttons look the same as a screen that has not loaded yet, and
    with the session churn fixed this state is now reachable."""
    sy = {"ahead": 0, "behind": 0, "dirty": False}
    verde = f"\033[{ui.cli.GREEN}m"
    for w in (100, ui.BUTTONS_W, 40):
        lineas = ui.sync_buttons(sy, w, up=0, down=0)
        assert "\u2713" in ui.strip_ansi(lineas[0]), (w, lineas[0])   # above the buttons
        assert verde in lineas[0], (w, lineas[0])
        for kw in ({"up": 1}, {"down": 1}):
            texto = ui.strip_ansi("\n".join(ui.sync_buttons(sy, w, **kw)))
            assert "\u2713" not in texto, (w, kw)
    for pend in ({"ahead": 1, "behind": 0}, {"ahead": 0, "behind": 1}):
        malo = ui.sync_buttons({**pend, "dirty": False}, 100, up=0, down=0)
        assert "\u2713" not in ui.strip_ansi("\n".join(malo)), pend
    for lang in ui.LANGS:
        real = ui.i18n.LANG
        try:
            ui.i18n.LANG = lang
            assert ui.t("all_synced") != "all_synced"
        finally:
            ui.i18n.LANG = real


def test_fetch_gets_a_button_when_there_is_room_and_the_legend_always():
    """↑↓ is read off the last `git fetch`, not off the network, so the way to
    refresh it had better be visible. `f` existed and nothing said so."""
    sy = {"ahead": 0, "behind": 0, "dirty": False}
    ancho = ui.sync_buttons(sy, 100)[1:]          # [0] is the synced legend
    assert len(ancho) == 3                        # sigue siendo una tira de 3
    txt = "\n".join(ui.strip_ansi(l) for l in ancho)
    assert "[f]" in txt and "FETCH" in txt
    assert f"\033[{ui.ACCENT}m" in ancho[1]       # fetch is always something to do
    # and it is the first thing to go when the terminal narrows
    medio = ui.sync_buttons(sy, ui.BUTTONS_W)
    assert "[f]" not in "\n".join(ui.strip_ansi(l) for l in medio)
    assert all(len(ui.strip_ansi(l)) <= ui.BUTTONS_W for l in medio)
    for lang in ui.LANGS:
        real = ui.i18n.LANG
        try:
            ui.i18n.LANG = lang
            assert "f fetch" in ui.t("k_home")
        finally:
            ui.i18n.LANG = real


def test_count_items_counts_what_only_a_dry_run_can_see():
    """Config to activate and memories to land show up in no git diff."""
    vacio = ui.classify([])
    assert ui.count_items(vacio) == 0
    vacio["activate"], vacio["pending_memories"] = 2, 14
    assert ui.count_items(vacio) == 16
    # git and the dry import describe the same memories: max(), not a sum
    con_git = ui.classify(["knowledge/memory/proj/PC/a.md"])
    con_git["pending_memories"] = 1
    assert ui.count_items(con_git) == 1


def test_the_button_strip_is_pinned_and_does_not_scroll_away():
    st = ui.new_state()
    st["pinned"] = ui.sync_buttons({"ahead": 1, "behind": 0, "dirty": False}, 100)
    st["rows"] = [f"línea {i}" for i in range(60)]
    for _ in range(50):
        st = ui.handle(st, "down")
    lines = [ui.strip_ansi(l) for l in ui.draw(st, 80, 20)]
    assert "PUSH" in lines[-4]                  # justo arriba del separador
    assert "línea 0" not in "\n".join(lines)     # the body did scroll
    # and the body gives up the height: 16 lines minus the 3 pinned ones
    assert ui.visible_rows(st, 20) == ui.body_height(20) - 3


def test_the_strip_never_eats_the_whole_body_on_a_tiny_terminal():
    st = ui.new_state()
    st["pinned"] = ui.sync_buttons({"ahead": 1, "behind": 1, "dirty": False}, 100)
    st["rows"] = ["una línea"]
    lines = ui.draw(st, 80, 6)                   # body_height = 2
    assert len(lines) == 6 and ui.visible_rows(st, 6) >= 1


def test_the_strip_hides_while_confirming_so_the_manifest_gets_the_room():
    st = ui.new_state()
    st["pinned"] = ui.sync_buttons({"ahead": 1, "behind": 0, "dirty": False}, 100)
    st["confirm"] = {"kind": "push"}
    st["manifest"] = ui.manifest_lines("push", ui.classify([]))
    assert ui.pinned_of(st, 20) == []


# ── scrollbar ──

def test_scrollbar_is_blank_when_everything_fits():
    assert ui.scrollbar(5, 0, 10, 8) == [" "] * 8


def test_scrollbar_thumb_tracks_the_top_and_reaches_both_ends():
    arriba = ui.scrollbar(100, 0, 10, 10)
    abajo = ui.scrollbar(100, 90, 10, 10)
    assert arriba[0] == "█" and arriba[-1] == "│"     # pegado arriba
    assert abajo[-1] == "█" and abajo[0] == "│"       # pegado abajo
    assert all(len(c) == 1 for c in arriba + abajo)
    assert 1 <= arriba.count("█") <= 10


def test_the_scrollbar_shows_up_in_the_frame_without_stealing_width():
    st = _st(n=50)
    lines = ui.draw(st, 60, 12)
    assert all(len(ui.strip_ansi(l)) == 60 for l in lines)
    cuerpo = [ui.strip_ansi(l) for l in lines[2:10]]
    assert any(l.endswith("█") for l in cuerpo)
    assert any(l.endswith("│") for l in cuerpo)


def test_the_footer_counts_the_visible_slice_when_it_fits():
    st = _st(n=50)
    assert "1–4 / 50" in ui.strip_ansi(ui.draw(st, 100, 12)[-1])
    # at w=60 it does not fit without eating a key hint, so it is not painted
    assert "/ 50" not in ui.strip_ansi(ui.draw(st, 60, 12)[-1])


# ── config: what always travels ──

def test_config_lists_knowledge_as_always_syncing():
    reales = (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin,
              ui.knowledge_counts)
    try:
        ui.srv.get_sync_prefs = lambda: []
        ui.srv.CONFIG_MODULES = {"skills": ()}
        ui._origin = lambda: ""
        ui.knowledge_counts = lambda: {"memories": 56, "sessions": 118, "vault": 13}
        rows = ui.load_config(ui.new_state())
        txt = "\n".join(ui.strip_ansi(ui.fmt_config(r, 100)) for r in rows)
        assert "Siempre sincronizan" in txt
        for nombre, n in (("memorias", 56), ("sesiones", 118), ("vault", 13)):
            assert nombre in txt and f"{n:>4} en repo" in txt
        assert "siempre sincroniza" in txt
        # and they are not checkboxes: they cannot be mistaken for a toggle
        assert "[ ] memorias" not in txt and "[x] memorias" not in txt
    finally:
        (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin,
         ui.knowledge_counts) = reales


def test_enter_on_an_always_syncing_row_explains_instead_of_toggling():
    guardado = []
    real = ui.srv.set_sync_prefs
    try:
        ui.srv.set_sync_prefs = lambda mods: guardado.append(mods)
        st = ui.new_state()
        st["tab"] = CFG
        st["rows"] = [{"kind": "fixed", "id": "memorias", "n": 56}]
        st = ui.handle(st, "\r")
        assert guardado == []                       # it did not touch the prefs
        assert "siempre" in st["flash"]
    finally:
        ui.srv.set_sync_prefs = real


def test_diff_pair_paints_the_bigger_side_when_they_disagree():
    igual = ui._diff_pair(148, 148)
    assert f"\033[{ui.cli.YELLOW}m" not in igual
    assert ui.strip_ansi(igual) == "148 local · 148 en repo"

    falta_local = ui._diff_pair(148, 149)
    assert ui.strip_ansi(falta_local) == "148 local · 149 en repo"
    # the 149 gets marked; the 148 stays as it is
    assert f"\033[{ui.cli.YELLOW}m149" in falta_local
    assert f"\033[{ui.cli.YELLOW}m148" not in falta_local

    sobra_local = ui._diff_pair(149, 148)
    assert f"\033[{ui.cli.YELLOW}m149" in sobra_local
    assert f"\033[{ui.cli.YELLOW}m148" not in sobra_local


def test_keys_change_with_the_level_you_are_at():
    st = ui.new_state()
    assert "p push" in ui.keys_for(st)              # home
    st["tab"] = SES
    assert "entrar" in ui.keys_for(st)               # lista de proyectos
    st["proj"] = "projA"
    assert "abrir" in ui.keys_for(st) and "agentes" in ui.keys_for(st)
    st["tab"], st["proj"] = MEM, None
    st["flat"] = True
    assert "abrir" in ui.keys_for(st) and "agentes" not in ui.keys_for(st)
    st["tab"] = CFG
    assert "cambiar" in ui.keys_for(st)


# ── keyboard bursts ──

def test_drain_applies_a_whole_burst_before_redrawing():
    # the wheel sends ~3 arrows per notch: if each cost a frame, scrolling would
    # be jumpy. drain() applies them all at once.
    st = _st(n=50)
    st = ui.drain(st, ["down"] * 12)
    assert st["sel"] == 12


def test_drain_stops_at_quit_and_ignores_the_rest_of_the_burst():
    st = _st(n=50)
    st = ui.drain(st, ["down", "down", "q", "down", "down"])
    assert st["quit"] is True and st["sel"] == 2


def test_drain_of_nothing_leaves_the_state_alone():
    st = _st()
    st["sel"] = 3
    assert ui.drain(st, [])["sel"] == 3


# ── responsive ──

def test_the_wordmark_collapses_to_one_line_on_a_narrow_terminal():
    # tres escalones, y ninguno se sale de su ancho
    entero = ui.banner(120)          # BRAINGENT STO en bloques
    medio = ui.banner(40)            # STO en bloques, el nombre en letra normal
    angosto = ui.banner(20)          # una linea
    assert len(entero) == 6, entero          # margen + 5 filas
    assert len(medio) == 7                   # margen + etiqueta + 5 filas
    assert len(angosto) == 2
    assert "braingent" == ui.strip_ansi(medio[1]).strip()
    assert "braingent STO" in ui.strip_ansi(angosto[1])
    for lineas, w in ((entero, 120), (medio, 40), (angosto, 20)):
        assert all(len(ui.strip_ansi(l)) <= w for l in lineas), (w, lineas)
    # el escalon del medio existe porque el nombre entero no entra en 80
    assert ui.FULL_W > 80 >= ui.WORDMARK_W, (ui.FULL_W, ui.WORDMARK_W)


def test_the_buttons_collapse_to_one_line_when_the_boxes_do_not_fit():
    sy = {"ahead": 3, "behind": 1, "dirty": False}
    assert len(ui.sync_buttons(sy, 100)) == 3      # dos cajas lado a lado
    angosto = ui.sync_buttons(sy, 40)
    assert len(angosto) == 1
    txt = ui.strip_ansi(angosto[0])
    assert "[p]" in txt and "[l]" in txt and len(txt) <= 40


def test_a_resize_reflows_the_home_instead_of_just_clipping_it():
    reales = _stub_home()
    try:
        st = ui.new_state()
        st["w"] = 100
        anchas = _home_txt(st)
        assert len(st["pinned"]) == 3
        st["w"] = 44
        angostas = _home_txt(st)
        assert len(st["pinned"]) == 1              # los botones colapsaron
        # the content is rebuilt, not clipped: nothing overflows the new width
        assert all(len(l) <= 44 for l in angostas)
        assert len(angostas) > 0 and anchas != angostas
    finally:
        _unstub_home(reales)


def test_wrap_items_breaks_the_counters_over_as_many_lines_as_needed():
    items = [f"{i} palabra" for i in range(6)]
    una = ui.wrap_items(items, 200)
    varias = ui.wrap_items(items, 30)
    assert len(una) == 1
    assert len(varias) > 1
    assert all(len(ui.strip_ansi(l)) <= 30 for l in varias)
    # no item is lost or duplicated
    assert " ".join(una).split() == " ".join(varias).split()


def test_wrap_items_measures_visible_width_not_ansi_bytes():
    pintado = [ui.cli.c("x" * 10, ui.ACCENT) for _ in range(3)]
    lineas = ui.wrap_items(pintado, 48)
    assert all(len(ui.strip_ansi(l)) <= 48 for l in lineas)
    assert len(lineas) == 1        # 2 sangría + 3×(10 + 3 sep) = 41, entra en 48
    assert len(ui.wrap_items(pintado, 30)) > 1   # medido en columnas, no en bytes


def test_draw_survives_a_terminal_too_small_to_be_useful():
    st = _st(n=20)
    for w, h in ((20, 5), (40, 6), (200, 60)):
        lines = ui.draw(st, w, h)
        assert len(lines) == h
        assert all(len(ui.strip_ansi(l)) == w for l in lines)


# ── sections and the tab bar ──

def test_section_fills_the_width_and_keeps_the_title_readable():
    s = ui.section("Uso", 40)
    plano = ui.strip_ansi(s)
    assert len(plano) == 40 - 1        # deja una columna de aire al final
    assert plano.startswith("── Uso ─") and plano.endswith("─")
    # a title longer than the panel must not grow the line
    assert len(ui.strip_ansi(ui.section("T" * 80, 40))) <= 84


def test_config_sections_are_titlecased_and_separated_by_blank_rows():
    reales = (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin,
              ui.knowledge_counts)
    try:
        ui.srv.get_sync_prefs = lambda: []
        ui.srv.CONFIG_MODULES = {"skills": ()}
        ui._origin = lambda: ""
        ui.knowledge_counts = lambda: {"memories": 1, "sessions": 2, "vault": 3}
        rows = ui.load_config(ui.new_state())
        titulos = [r["text"] for r in rows if r["kind"] == "head"]
        assert titulos == ["Preferencias", "Siempre sincronizan",
                           "Módulos de config", "Sincronizar en la nube (GitHub)"]
        assert all(x[0].isupper() for x in titulos)
        # every section (but the first) is preceded by a blank row
        kinds = [r["kind"] for r in rows]
        for i, k in enumerate(kinds):
            if k == "head" and i:
                assert kinds[i - 1] == "gap"
    finally:
        (ui.srv.get_sync_prefs, ui.srv.CONFIG_MODULES, ui._origin,
         ui.knowledge_counts) = reales


def test_the_active_tab_is_a_filled_rectangle_in_the_accent_colour():
    # reverse video: the block takes the accent colour and the text takes the
    # terminal's real background, so it reads the same on light and dark themes
    inverso = f"\033[7;{ui.ACCENT}m"
    activa = ui.tab_chip(" Home ", True)
    inactiva = ui.tab_chip(" Home ", False)
    assert activa.startswith(inverso) and activa.endswith("\033[0m")
    assert inverso not in inactiva
    assert "30m" not in activa                     # nada de negro hardcodeado
    # both measure the same: otherwise the tabs shift when you switch
    assert ui.strip_ansi(activa) == ui.strip_ansi(inactiva) == " Home "


# ── wrapping the detail text ──

def test_wrap_ansi_breaks_on_spaces_and_never_exceeds_the_width():
    texto = "la respuesta de claude sigue y sigue sin cortarse nunca del todo"
    partes = ui.wrap_ansi(texto, 20, "  ")
    assert len(partes) > 1
    assert all(len(ui.strip_ansi(p)) <= 20 for p in partes)
    assert not any(p.endswith(" ") for p in partes)      # no corta al medio
    # not a single word is lost
    assert " ".join(p.strip() for p in partes).split() == texto.split()
    for p in partes[1:]:
        assert p.startswith("  ")                        # continuaciones sangradas


def test_wrap_ansi_carries_the_colour_into_the_continuation():
    pintado = ui.cli.c("palabra " * 10, ui.cli.YELLOW)
    partes = ui.wrap_ansi(pintado, 20)
    assert len(partes) > 1
    for p in partes:
        assert f"\033[{ui.cli.YELLOW}m" in p and p.endswith("\033[0m")
        assert len(ui.strip_ansi(p)) <= 20


def test_wrap_ansi_survives_a_word_longer_than_the_line():
    largo = "x" * 50
    partes = ui.wrap_ansi(largo, 12)
    assert all(len(ui.strip_ansi(p)) <= 12 for p in partes)
    assert "".join(ui.strip_ansi(p).strip() for p in partes) == largo


def test_wrap_ansi_leaves_a_short_line_alone():
    assert ui.wrap_ansi("corta", 40) == ["corta"]
    assert ui.wrap_ansi("", 40) == [""]


def test_the_detail_wraps_to_the_terminal_instead_of_losing_the_end():
    largo = "palabra " * 40           # ~320 columnas de texto
    st = _st()
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], real[1], real[2], lambda row: [largo])
    try:
        st = ui.handle(st, "\r")
        assert st["mode"] == "detail"
        cuerpo = [ui.strip_ansi(l) for l in ui.draw(st, 60, 20)[2:18]]
        visible = " ".join(l.strip() for l in cuerpo).split()
        assert visible == largo.split()              # all there, not clipped
        assert all(len(l) == 60 for l in cuerpo)
    finally:
        ui.TABS[SES] = real


def test_the_detail_rewraps_when_the_terminal_changes_width():
    st = _st()
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], real[1], real[2], lambda row: ["palabra " * 40])
    try:
        st = ui.handle(st, "\r")
        ui.draw(st, 120, 20)
        anchas = len(st["dwrap"])
        ui.draw(st, 50, 20)
        assert len(st["dwrap"]) > anchas             # narrower means more lines
        assert st["dwrap_w"] == 48                   # w menos la barra de scroll
    finally:
        ui.TABS[SES] = real


def test_opening_another_detail_invalidates_the_wrapped_cache():
    st = _st()
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], real[1], real[2], lambda row: ["a " * 100])
    try:
        st = ui.handle(st, "\r")
        ui.draw(st, 60, 20)
        assert st["dwrap_w"] == 58
        st = ui.handle(st, "\x1b")
        assert st["dwrap_w"] is None                 # al salir se descarta
        ui.TABS[SES] = (real[0], real[1], real[2], lambda row: ["b"])
        st = ui.handle(st, "\r")
        assert st["dwrap_w"] is None                 # and opening another one too
        ui.draw(st, 60, 20)
        assert st["dwrap"] == ["b"]
    finally:
        ui.TABS[SES] = real


def test_detail_scroll_still_reaches_the_end_of_a_wrapped_text():
    st = _st()
    real = ui.TABS[SES]
    ui.TABS[SES] = (real[0], real[1], real[2],
                    lambda row: [f"línea {i} " + "x " * 40 for i in range(20)])
    try:
        st = ui.handle(st, "\r")
        for _ in range(60):
            st = ui.handle(st, "pgdn")
            ui.draw(st, 60, 20)
        txt = "\n".join(ui.strip_ansi(l) for l in ui.draw(st, 60, 20))
        assert "línea 19" in txt
    finally:
        ui.TABS[SES] = real


# ── Tab switches section ──

def test_tab_and_shift_tab_cycle_the_sections():
    st = ui.new_state()
    assert ui.handle(st, "\t")["tab"] == SES
    assert ui.handle(st, "\t")["tab"] == MEM
    assert ui.handle(st, "shifttab")["tab"] == SES
    st["tab"] = ui.HOME
    assert ui.handle(st, "shifttab")["tab"] == ui.HELP   # it cycles backwards
    assert ui.read_key is not None
    assert ui.SPECIAL["\x0f"] == "shifttab"             # el scancode de Shift+Tab


def test_the_poll_is_short_enough_to_keep_up_with_key_repeat():
    # Windows repeats at ~31 keys/s (one every 32 ms): sleeping longer than that
    # made every key wait, and scrolling felt heavy
    assert ui.POLL <= 0.032


def test_the_legend_says_the_key_without_saying_tab_twice():
    for lang in ui.LANGS:
        real = ui.i18n.LANG
        try:
            ui.i18n.LANG = lang
            for key in ("k_home", "k_project", "k_config", "k_module"):
                legend = ui.t(key)
                assert "Tab " in legend
                assert "tab tab" not in legend.lower()
                assert " tab " not in legend          # la vieja "←→ tab" se fue
        finally:
            ui.i18n.LANG = real


# ── help tab ──

def test_the_help_tab_is_only_the_commands():
    # shortcuts do not belong here: the bottom bar already shows the ones for
    # the level you are on, and a second list goes stale on its own
    st = ui.new_state()
    st["tab"] = AYU
    st = ui.reload_tab(st)
    txt = "\n".join(ui.strip_ansi(ui.fmt_home(r, 100)) for r in st["rows"])
    assert "Comandos de `sto`" in txt
    assert "Atajos" not in txt and "Shift+Tab" not in txt
    assert not hasattr(ui, "ATAJOS")


def test_the_help_tab_reads_the_commands_off_the_cli_registry():
    st = ui.new_state()
    st["tab"] = AYU
    txt = "\n".join(ui.strip_ansi(ui.fmt_home(r, 100)) for r in ui.help_lines(st))
    assert "Comandos de `sto`" in txt
    # the usage comes from the cmd_* docstring, arguments included
    assert "sto search <text>" in txt and "sto show <id>" in txt
    # the description comes from STRINGS, not the docstring, so it translates
    assert "busca texto en todas las sesiones" in txt
    assert "sto push" in txt and "lo sube al repo" in txt
    # and none of them is left out of the registry
    assert all(any(f"sto {n}" in l for l in txt.splitlines()) for n in ui.cli.CLI)
    # no description is blank or showing the raw key
    assert not any(que.startswith("cmd_") or not que for _, que in ui.commands())


def test_no_command_syntax_is_ever_truncated_at_any_width():
    """The bug: the usage was cut at 26 columns with an ellipsis, so the help
    read `sto memory [<project> | s…` — the one thing on that screen you cannot
    guess. Nothing is cut now; what does not fit drops to its own line."""
    for w in (120, 100, 80, 64, 46):
        st = ui.new_state()
        st["w"] = w
        lineas = [ui.strip_ansi(ui.fmt_home(r, w)) for r in ui.help_lines(st)]
        txt = "\n".join(lineas)
        for uso, _ in ui.commands():
            for palabra in uso.split():
                assert palabra in txt, (w, uso, palabra)
        assert "…" not in txt
        # and it reflows instead of running off the edge
        assert all(len(l) <= w - 1 for l in lineas), w


def test_the_description_column_is_aligned_when_the_usage_fits():
    st = ui.new_state()
    st["w"] = 100
    lineas = [ui.strip_ansi(ui.fmt_home(r, 100)) for r in ui.help_lines(st)]
    cortas = {l.index(q) for l in lineas for u, q in ui.commands()
              if l.startswith(f"    {u} ") and q in l}
    assert len(cortas) == 1                    # one column for every one-liner


def test_the_commands_are_translated_too():
    real = ui.i18n.LANG
    try:
        ui.i18n.LANG = "en"
        usos = dict(ui.commands())
        assert usos["sto search <text>"] == "search text across every session"
        assert not any("busca" in q for q in usos.values())
    finally:
        ui.i18n.LANG = real


def test_a_new_command_shows_up_without_touching_the_help():
    real = dict(ui.cli.CLI)
    try:
        def cmd_inventado(*a):
            """sto inventado <x> — hace algo nuevo."""
        ui.cli.CLI["inventado"] = cmd_inventado
        usos = dict(ui.commands())
        assert usos["sto inventado <x>"] == "hace algo nuevo"
    finally:
        ui.cli.CLI.clear()
        ui.cli.CLI.update(real)


def test_the_help_tab_never_reloads_on_a_tick():
    # it is fixed text: reloading it every 3s would reread the registry for nothing
    assert ui.CADENCE[AYU] >= 600
    assert len(ui.CADENCE) == len(ui.ROW_H) == len(ui.TABS) == len(ui.TAB_IDS)


def test_the_help_tab_loads_even_with_the_machine_just_booted():
    # monotonic() cuenta desde el arranque en Windows: con 10 s de uptime,
    # `monotonic() - 0.0 >= 3600` es falso y ayuda se quedaba en `loading…`
    real = ui.time.monotonic
    try:
        ui.time.monotonic = lambda: 10.0
        st = ui.new_state()
        st["tab"] = AYU
        assert ui.tick(st)["rows"]
    finally:
        ui.time.monotonic = real


def test_there_is_no_rule_under_the_tabs_only_air():
    st = ui.new_state()
    st["rows"] = ["contenido"]
    segunda = ui.strip_ansi(ui.draw(st, 80, 12)[1])
    assert segunda.strip() == ""                   # ni ─ ni ━: aire
    assert len(segunda) == 80


def test_every_tab_keeps_its_place_when_the_active_one_changes():
    st = ui.new_state()
    posiciones = [ui.strip_ansi(ui.header(dict(st, tab=i), 80)) for i in range(4)]
    # the header's plain text is identical for all four: only the colour changes
    assert len(set(posiciones)) == 1


def test_the_cursor_skips_the_rows_of_config_that_do_nothing():
    st = ui.new_state()
    st["tab"] = CFG
    st["rows"] = [{"kind": "head", "text": "A"}, {"kind": "accent"},
                  {"kind": "gap"}, {"kind": "head", "text": "B"},
                  {"kind": "module", "id": "skills", "on": True},
                  {"kind": "gap"}, {"kind": "text", "text": "x"}]
    st["sel"] = 0
    st = ui._snap(st, 1)
    assert st["sel"] == 1                       # it starts on the first useful one
    st = ui.handle(st, "down")
    assert st["sel"] == 4                       # saltea gap y head
    st = ui.handle(st, "up")
    assert st["sel"] == 1                       # and going up as well
    st = ui.handle(st, "down")
    st = ui.handle(st, "down")
    assert st["sel"] == 4                       # abajo de todo no cae en 'text'


def test_a_label_prefix_only_appears_on_the_first_wrapped_line():
    lineas = ui.wrap_items(["aaaa", "bbbb", "cccc"], 18,
                           indent="  Etiqueta: ", sep=" · ")
    assert len(lineas) > 1
    assert lineas[0].startswith("  Etiqueta: ")
    for l in lineas[1:]:
        assert "Etiqueta" not in l
        assert l.startswith(" " * len("  Etiqueta: "))   # alineadas debajo


def test_snap_leaves_the_other_tabs_alone():
    st = _st(n=5)
    st["sel"] = 3
    assert ui._snap(st, 1)["sel"] == 3
    vacia = ui.new_state()
    vacia["tab"] = CFG
    assert ui._snap(vacia, 1)["sel"] == 0       # sin filas no explota


def test_the_machines_label_is_a_prefix_not_a_list_item():
    reales = _stub_home()
    try:
        st = ui.new_state()
        st["w"] = 100
        linea = next(l for l in _home_txt(st) if "quinas:" in l)
        assert linea.strip().startswith("Máquinas: NB")   # no '·' dangling in front
        assert "NB · PC (esta)" in linea
    finally:
        _unstub_home(reales)


def test_switching_language_invalidates_the_cached_header_summary():
    with tempfile.TemporaryDirectory() as d:
        reales = (ui.i18n.PREFS, ui.i18n.LANG, dict(ui._SUMMARY))
        try:
            ui.i18n.PREFS = Path(d) / "sto-ui.json"
            ui._SUMMARY.update(ts=9e9, text="uso 42%")   # cache "fresco"
            ui.set_lang("en")
            assert ui._SUMMARY["ts"] == 0.0              # forzado a recalcular
        finally:
            ui.i18n.PREFS, ui.i18n.LANG = reales[0], reales[1]
            ui._SUMMARY.update(reales[2])


# ── entering a home module and deleting from inside ──

def test_enter_on_a_config_module_lists_what_it_holds_and_esc_goes_back():
    reales = _stub_home()
    items = [{"kind": "item", "what": "skill", "id": "personal:tackler",
              "label": "tackler", "desc": "hace cosas"}]
    real_items = ui.module_items
    try:
        ui.parity = lambda **k: {"local_only": [], "repo_only": [], "sync": [],
                                 "plugins": [], "modules": [
                                     {"id": "skills", "localFiles": 2,
                                      "repoFiles": 2, "enabled": True}]}
        ui.module_items = lambda mod, claude_dir=None: items
        st = ui.new_state()
        st = ui.reload_tab(st)
        i = next(i for i, r in enumerate(st["rows"]) if r["kind"] == "module")
        st["sel"] = i
        st = ui.handle(st, "\r")
        assert st["mod"] == "skills"
        txt = "\n".join(_home_txt(st))
        assert "skills · 1" in txt and "tackler" in txt and "hace cosas" in txt
        assert "borrar" in ui.keys_for(st)          # las teclas cambian de nivel

        st = ui.handle(st, "\x1b")
        assert st["mod"] is None                    # Esc vuelve al dashboard
    finally:
        ui.module_items = real_items
        _unstub_home(reales)


def test_module_items_reads_skills_plugins_and_plain_files():
    import tempfile as tmp
    with tmp.TemporaryDirectory() as d:
        cd = Path(d)
        _skill(cd, "tackler", desc="hace cosas")
        (cd / "plugins").mkdir(parents=True)
        (cd / "plugins" / "installed_plugins.json").write_text(
            '{"plugins": {"superpowers@official": []}}', encoding="utf-8")
        (cd / "agents").mkdir()
        (cd / "agents" / "uno.md").write_text("x", encoding="utf-8")

        skills = ui.module_items("skills", cd)
        assert [s["label"] for s in skills] == ["tackler"]
        assert skills[0]["id"] == "personal:tackler" and skills[0]["what"] == "skill"

        plugins = ui.module_items("plugins", cd)
        assert [p["id"] for p in plugins] == ["superpowers@official"]
        assert plugins[0]["what"] == "plugin"

        archivos = ui.module_items("agents", cd)
        assert [f["label"] for f in archivos] == ["uno.md"]
        assert archivos[0]["what"] == "file"        # y por eso no se borra


def test_d_asks_before_deleting_a_skill_and_esc_cancels():
    borrados = []
    real = ui.srv.delete_skill
    try:
        ui.srv.delete_skill = lambda sid: borrados.append(sid)
        st = ui.new_state()
        st["mod"] = "skills"
        st["rows"] = [{"kind": "item", "what": "skill", "id": "personal:tackler",
                       "label": "tackler", "desc": ""}]
        st = ui.handle(st, "d")
        assert st["confirm"]["kind"] == "delete" and borrados == []
        txt = "\n".join(ui.strip_ansi(l) for l in st["manifest"])
        assert "Borrar skill" in txt and "tackler" in txt
        assert "vuelve con un pull" in txt          # dice que es reversible

        st = ui.handle(st, "\x1b")
        assert st["confirm"] is None and borrados == []

        st = ui.handle(st, "d")
        st = ui.handle(st, "\r")
        assert borrados == ["personal:tackler"]
        assert "tackler" in st["flash"]
    finally:
        ui.srv.delete_skill = real



def test_R_asks_before_dropping_from_the_repo_and_never_touches_the_machine():
    llamadas = []
    real = ui.srv.forget

    def falso(target, apply=False):
        llamadas.append((target, apply))
        return (["knowledge/config/skills/skills/vieja/SKILL.md"], None)

    try:
        ui.srv.forget = falso
        st = ui.new_state()
        st["mod"] = "skills"
        st["rows"] = [{"kind": "item", "what": "skill", "id": "personal:vieja",
                       "label": "vieja", "desc": "", "where": "repo"}]
        st = ui.handle(st, "R")
        # la tarjeta sale de un dry run: nada se borró todavía
        assert st["confirm"]["kind"] == "forget"
        assert llamadas == [("skill:vieja", False)], llamadas
        txt = "\n".join(ui.strip_ansi(l) for l in st["manifest"])
        assert "vieja" in txt
        assert "SKILL.md" in txt                     # el manifiesto, no un resumen
        assert "no se toca" in txt or "untouched" in txt

        st = ui.handle(st, "\x1b")
        assert st["confirm"] is None
        assert all(not a for _, a in llamadas)       # cancelar no aplicó nada

        st = ui.handle(st, "R")
        st = ui.handle(st, "\r")
        assert ("skill:vieja", True) in llamadas
        assert "vieja" in st["flash"]
    finally:
        ui.srv.forget = real


def test_R_says_why_when_the_export_would_just_put_it_back():
    """El guard de `srv.forget` se muestra tal cual: es la única pista de que
    hay que desinstalarla local primero."""
    real = ui.srv.forget
    try:
        ui.srv.forget = lambda target, apply=False: ([], "still installed here")
        st = ui.new_state()
        st["mod"] = "skills"
        st["rows"] = [{"kind": "item", "what": "skill", "id": "personal:viva",
                       "label": "viva", "desc": "", "where": "both"}]
        st = ui.handle(st, "R")
        assert st["confirm"] is None                 # no pregunta lo que no puede hacer
        assert st["flash"] == "still installed here"
    finally:
        ui.srv.forget = real


def test_a_module_lists_what_only_the_repo_has_so_R_has_a_row_to_land_on():
    with tempfile.TemporaryDirectory() as d:
        claude = Path(d) / "claude"
        (claude / "skills" / "local-only").mkdir(parents=True)
        (claude / "skills" / "local-only" / "SKILL.md").write_text(
            "---\nname: local-only\ndescription: aca\n---\nx", encoding="utf-8")
        (claude / "skills" / "en-ambas").mkdir(parents=True)
        (claude / "skills" / "en-ambas" / "SKILL.md").write_text(
            "---\nname: en-ambas\ndescription: dos\n---\nx", encoding="utf-8")
        cfg = Path(d) / "config"
        for name in ("en-ambas", "repo-only"):
            (cfg / "skills" / "skills" / name).mkdir(parents=True)
            (cfg / "skills" / "skills" / name / "SKILL.md").write_text(
                "---\nname: %s\ndescription: r\n---\nx" % name, encoding="utf-8")

        items = ui.module_items("skills", claude_dir=claude, repo_config=cfg)
        estado = {i["label"]: i["where"] for i in items}
        assert estado == {"local-only": "local", "en-ambas": "both",
                          "repo-only": "repo"}, estado
        # y el marcador compacto los distingue en cualquier ancho
        pintado = {i["label"]: ui.strip_ansi(ui.fmt_home(i, 100)) for i in items}
        assert pintado["repo-only"].startswith(" [R]"), pintado["repo-only"]
        assert pintado["local-only"].startswith(" [L]"), pintado["local-only"]
        assert pintado["en-ambas"].startswith(" [=]"), pintado["en-ambas"]


def test_a_skill_dropped_in_the_repo_is_painted_apart_from_one_never_pushed():
    real = ui.srv.dropped_skills
    try:
        ui.srv.dropped_skills = lambda: {"borrada-alla"}
        with tempfile.TemporaryDirectory() as d:
            claude = Path(d) / "claude"
            for name in ("borrada-alla", "recien-escrita"):
                (claude / "skills" / name).mkdir(parents=True)
                (claude / "skills" / name / "SKILL.md").write_text(
                    "---\nname: %s\ndescription: x\n---\ny" % name, encoding="utf-8")
            cfg = Path(d) / "config"
            (cfg / "skills" / "skills").mkdir(parents=True)

            items = ui.module_items("skills", claude_dir=claude, repo_config=cfg)
            estado = {i["label"]: i["where"] for i in items}
            # misma foto en disco, dos estados distintos: solo git los separa
            assert estado == {"borrada-alla": "gone",
                              "recien-escrita": "local"}, estado
            pintado = {i["label"]: ui.strip_ansi(ui.fmt_home(i, 100)) for i in items}
            assert pintado["borrada-alla"].startswith(" [x]"), pintado["borrada-alla"]
            assert pintado["recien-escrita"].startswith(" [L]"), pintado["recien-escrita"]
    finally:
        ui.srv.dropped_skills = real


def test_the_state_legend_only_shows_up_when_something_is_out_of_parity():
    real_items, real_drop = ui.module_items, ui.srv.dropped_skills
    try:
        ui.srv.dropped_skills = lambda: set()
        st = ui.new_state()
        st["mod"] = "skills"

        ui.module_items = lambda mod, **kw: [
            {"kind": "item", "what": "skill", "id": "personal:a", "label": "a",
             "desc": "", "where": "both"}]
        limpio = "\n".join(ui.strip_ansi(ui.fmt_home(r, 100)) for r in ui.module_lines(st))
        assert "[L]" not in limpio and "[R]" not in limpio

        ui.module_items = lambda mod, **kw: [
            {"kind": "item", "what": "skill", "id": "personal:a", "label": "a",
             "desc": "", "where": "gone"}]
        sucio = "\n".join(ui.strip_ansi(ui.fmt_home(r, 100)) for r in ui.module_lines(st))
        assert "[x]" in sucio and "[L]" in sucio      # la fila y la leyenda entera
    finally:
        ui.module_items, ui.srv.dropped_skills = real_items, real_drop


def test_a_brings_a_repo_only_row_here_and_esc_cancels():
    """Cierra la simetría: `a` trae, `d` saca de acá, `R` saca del repo.
    Antes, a una fila `[R]` solo se le podía hacer una cosa: borrarla."""
    llamadas = []
    real = ui.srv.bring

    def falso(target, apply=False):
        llamadas.append((target, apply))
        return (["knowledge/config/skills/skills/traida/SKILL.md"], None)

    try:
        ui.srv.bring = falso
        st = ui.new_state()
        st["mod"] = "skills"
        st["rows"] = [{"kind": "item", "what": "skill", "id": "personal:traida",
                       "label": "traida", "desc": "", "where": "repo"}]
        st = ui.handle(st, "a")
        assert st["confirm"]["kind"] == "bring"
        assert llamadas == [("skill:traida", False)], llamadas
        txt = "\n".join(ui.strip_ansi(l) for l in st["manifest"])
        assert "traida" in txt and "SKILL.md" in txt
        assert "sto-backup" in txt              # dice dónde queda lo que pisa

        st = ui.handle(st, "\x1b")
        assert st["confirm"] is None
        assert all(not a for _, a in llamadas)

        st = ui.handle(st, "a")
        st = ui.handle(st, "\r")
        assert ("skill:traida", True) in llamadas
        assert "traida" in st["flash"]
    finally:
        ui.srv.bring = real


def test_a_says_why_when_there_is_nothing_to_bring():
    real = ui.srv.bring
    try:
        ui.srv.bring = lambda target, apply=False: ([], "already installed here")
        st = ui.new_state()
        st["mod"] = "skills"
        st["rows"] = [{"kind": "item", "what": "skill", "id": "personal:ya",
                       "label": "ya", "desc": "", "where": "both"}]
        st = ui.handle(st, "a")
        assert st["confirm"] is None
        assert st["flash"] == "already installed here"
    finally:
        ui.srv.bring = real


def test_the_three_verbs_are_all_reachable_from_a_module_and_named_in_the_legend():
    """Los tres que existen, y ninguno más: no hay tecla para 'subir esta',
    porque el push ya lleva todo lo local."""
    for lang in ui.LANGS:
        real = ui.i18n.LANG
        try:
            ui.i18n.LANG = lang
            legend = ui.t("k_module")
            assert " a " in legend and " d " in legend and " R " in legend, legend
            assert " u " not in legend, legend
        finally:
            ui.i18n.LANG = real


def test_d_uninstalls_a_plugin_through_the_claude_cli():
    llamadas = []
    real = ui.srv.plugin_cmd
    try:
        ui.srv.plugin_cmd = lambda a, p: llamadas.append((a, p)) or {"ok": True}
        st = ui.new_state()
        st["mod"] = "plugins"
        st["rows"] = [{"kind": "item", "what": "plugin", "id": "sp@official",
                       "label": "sp@official", "desc": ""}]
        st = ui.handle(st, "d")
        st = ui.handle(st, "\r")
        assert llamadas == [("uninstall", "sp@official")]
    finally:
        ui.srv.plugin_cmd = real


def test_d_refuses_on_a_plain_file_instead_of_deleting_it():
    st = ui.new_state()
    st["mod"] = "agents"
    st["rows"] = [{"kind": "item", "what": "file", "id": "/x/uno.md",
                   "label": "uno.md", "desc": ""}]
    st = ui.handle(st, "d")
    assert st["confirm"] is None                    # ni siquiera pregunta
    assert "agents" in st["flash"]


def test_d_does_nothing_outside_a_module():
    st = ui.new_state()
    st["rows"] = [{"kind": "text", "text": "x"}]
    assert ui.handle(st, "d")["confirm"] is None


def test_a_failed_delete_shows_the_error_instead_of_claiming_success():
    real = ui.srv.delete_skill
    try:
        ui.srv.delete_skill = lambda sid: "skill not found"
        st = ui.new_state()
        st["mod"] = "skills"
        st["rows"] = [{"kind": "item", "what": "skill", "id": "personal:x",
                       "label": "x", "desc": ""}]
        st = ui.handle(st, "d")
        st = ui.handle(st, "\r")
        assert st["flash"] == "skill not found"
    finally:
        ui.srv.delete_skill = real


def test_inside_a_module_the_cursor_only_lands_on_items():
    st = ui.new_state()
    st["mod"] = "skills"
    st["rows"] = [{"kind": "text", "text": ""},
                  {"kind": "text", "text": "── skills ──"},
                  {"kind": "item", "what": "skill", "id": "a", "label": "a", "desc": ""},
                  {"kind": "item", "what": "skill", "id": "b", "label": "b", "desc": ""}]
    st["sel"] = 0
    st = ui._snap(st, 1)
    assert st["sel"] == 2
    assert ui.handle(st, "down")["sel"] == 3


def test_switching_tabs_closes_the_open_module():
    st = ui.new_state()
    st["mod"] = "skills"
    assert ui.handle(st, "2")["mod"] is None
    st["mod"] = "skills"
    assert ui.handle(st, "right")["mod"] is None


def test_sync_preview_classifies_both_directions_without_touching_the_network():
    llamadas, seco = [], []
    reales = (ui.srv._git, ui.srv.sync_status, ui.srv.export_config,
              ui.srv.apply_config, ui.srv.export_memory, ui.srv.import_memory)
    try:
        ui.srv.sync_status = lambda fetch=True, **k: {"branch": "main", "ahead": 1,
                                                      "behind": 0, "dirty": True,
                                                      "remote": "x", "fetchError": None}

        def git(*args, **kw):
            llamadas.append(args)
            if args[0] == "diff" and "origin/main...HEAD" in args:
                return 0, "knowledge/sessions/PC/a.jsonl\nvault/wiki/n.md"
            if args[0] == "status":
                return 0, " M knowledge/memory/proj/PC/x.md"
            return 0, ""
        ui.srv._git = git

        def espia(nombre, n):
            def f(*a, **kw):
                seco.append((nombre, kw.get("dry")))
                return n
            return f
        ui.srv.export_config = espia("export_config", 0)
        ui.srv.apply_config = espia("apply_config", 2)
        ui.srv.export_memory = espia("export_memory", 0)
        ui.srv.import_memory = espia("import_memory", 5)

        subir, bajar = ui.sync_preview()
        assert subir["sessions"] == 1 and subir["vault"] == 1
        assert subir["memories"] == {"proj": 1}
        assert ui.count_items(subir) == 3
        # git has nothing coming down, and the preview still sees the 5
        # memories and the 2 config files this machine never took
        assert ui.count_items(bajar) == 7
        assert ui.preview_parts(bajar) == ["5 memorias", "2 activar"]
        # no fetch, and every export/apply asked for a dry run: it reads and
        # never writes, because this runs on every repaint of the home
        assert all(a[0] in ("diff", "status") for a in llamadas)
        assert seco and all(dry is True for _, dry in seco)
    finally:
        (ui.srv._git, ui.srv.sync_status, ui.srv.export_config,
         ui.srv.apply_config, ui.srv.export_memory, ui.srv.import_memory) = reales


def test_preview_parts_names_the_kinds_and_is_empty_when_nothing_travels():
    data = ui.classify(["knowledge/sessions/PC/a.jsonl",
                        "knowledge/sessions/PC/b.jsonl",
                        "knowledge/memory/p/PC/m.md"])
    assert ui.preview_parts(data) == ["2 sesiones", "1 memorias"]
    assert ui.preview_parts(ui.classify([])) == []


def test_the_language_switch_reaches_the_whole_frame():
    real = ui.i18n.LANG
    try:
        st = _st()
        ui.i18n.LANG = "en"
        marco = "\n".join(ui.strip_ansi(l) for l in ui.draw(st, 100, 12))
        assert "Sessions" in marco and "Memory" in marco
        assert "q quit" in marco and "back" in marco
        assert "Sesiones" not in marco and "salir" not in marco
    finally:
        ui.i18n.LANG = real


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"OK ({len(fns)} tests)")
    sys.exit(0)
