import json
import os
import pathlib
import tempfile
from pathlib import Path

import cli
import i18n

# The CLI translates what it prints; these asserts are about the Spanish
# strings, so the language is pinned here instead of depending on the machine.
i18n.LANG = "es"


def _fake_session(dirpath, name, prompt="hola mundo"):
    p = Path(dirpath) / name
    p.write_text(json.dumps(
        {"type": "user", "cwd": str(dirpath),
         "message": {"role": "user", "content": prompt}}) + "\n", encoding="utf-8")
    return p


def test_cached_sessions_reuses_entry_and_reparses_on_change():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projects" / "projA"
        proj.mkdir(parents=True)
        f = _fake_session(proj, "aaaaaaaa-0000-0000-0000-000000000000.jsonl", "primer prompt")
        cache = Path(d) / "cache.json"
        kn = Path(d) / "knowledge"

        rows, prompts = cli.cached_sessions(projects_dir=Path(d) / "projects",
                                            knowledge_dir=kn, cache_path=cache)
        assert len(rows) == 1
        assert rows[0]["title"] == "primer prompt"
        assert rows[0]["path"] == str(f)
        assert rows[0]["machine"] is None
        assert "primer prompt" in prompts[rows[0]["id"]]
        assert cache.exists()

        # unchanged: the cache entry is reused (nothing is parsed again)
        calls = []
        real = cli.srv.session_meta
        try:
            cli.srv.session_meta = lambda p: calls.append(p) or real(p)
            rows2, _ = cli.cached_sessions(projects_dir=Path(d) / "projects",
                                           knowledge_dir=kn, cache_path=cache)
            assert calls == []
            assert rows2[0]["title"] == "primer prompt"

            # the file and its mtime change: it is parsed again
            f.write_text(json.dumps(
                {"type": "user", "cwd": str(proj),
                 "message": {"role": "user", "content": "prompt nuevo"}}) + "\n",
                encoding="utf-8")
            os.utime(f, (0, 0))
            rows3, _ = cli.cached_sessions(projects_dir=Path(d) / "projects",
                                           knowledge_dir=kn, cache_path=cache)
            assert calls == [f]
            assert rows3[0]["title"] == "prompt nuevo"
        finally:
            cli.srv.session_meta = real


def test_cached_sessions_drops_deleted_and_survives_corrupt_cache():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projects" / "projA"
        proj.mkdir(parents=True)
        f1 = _fake_session(proj, "aaaaaaaa-0000-0000-0000-000000000000.jsonl", "uno")
        _fake_session(proj, "bbbbbbbb-0000-0000-0000-000000000000.jsonl", "dos")
        cache = Path(d) / "cache.json"
        kn = Path(d) / "knowledge"
        args = dict(projects_dir=Path(d) / "projects", knowledge_dir=kn, cache_path=cache)

        assert len(cli.cached_sessions(**args)[0]) == 2
        f1.unlink()
        rows, _ = cli.cached_sessions(**args)
        assert len(rows) == 1
        assert str(f1) not in cache.read_text(encoding="utf-8")

        cache.write_text("{no es json", encoding="utf-8")
        assert len(cli.cached_sessions(**args)[0]) == 1  # it rebuilds itself

        cache.write_text(json.dumps({"version": 999, "entries": {"x": {}}}), encoding="utf-8")
        assert len(cli.cached_sessions(**args)[0]) == 1  # an old version is discarded


def test_search_finds_prompts_reloaded_from_cache():
    """Closes the cache -> _PROMPTS_INDEX -> search_sessions seam.

    On a warm-cache run `cached_sessions` never calls `session_meta`, so
    `_PROMPTS_INDEX` can only be refilled if `cached_sessions` re-injects what
    it persisted in the cache (scripts/cli.py, `srv._PROMPTS_INDEX.update`).
    If that line disappeared this test would fail: `_PROMPTS_INDEX` would stay
    empty after the `.clear()` and `search_sessions` would not find the rare
    word, which only lives in the second prompt (not in the title, which comes
    from the first).
    """
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projects" / "projA"
        proj.mkdir(parents=True)
        sid = "aaaaaaaa-0000-0000-0000-000000000000"
        p = proj / f"{sid}.jsonl"
        p.write_text(
            json.dumps({"type": "user", "cwd": str(proj),
                        "message": {"role": "user", "content": "primer prompt"}}) + "\n"
            + json.dumps({"type": "user", "cwd": str(proj),
                          "message": {"role": "user",
                                      "content": "segundo prompt con la palabra rarisima"}})
            + "\n",
            encoding="utf-8")
        cache = Path(d) / "cache.json"
        kn = Path(d) / "knowledge"
        args = dict(projects_dir=Path(d) / "projects", knowledge_dir=kn, cache_path=cache)

        cli.cached_sessions(**args)              # cold run: fills the on-disk cache
        cli.srv._PROMPTS_INDEX.clear()            # like starting a fresh process

        calls = []
        real = cli.srv.session_meta
        try:
            cli.srv.session_meta = lambda pp: calls.append(pp) or real(pp)
            rows, _ = cli.cached_sessions(**args)  # cache hit: must not touch session_meta
        finally:
            cli.srv.session_meta = real
        assert calls == []

        hits = cli.srv.search_sessions("rarisima", rows=rows)
        assert len(hits) == 1 and hits[0]["id"] == sid


def test_color_off_emits_no_ansi():
    old = cli.COLOR
    try:
        cli.COLOR = False
        assert cli.c("hola", cli.CYAN) == "hola"
        cli.COLOR = True
        assert cli.c("hola", cli.CYAN) == "\033[36mhola\033[0m"
    finally:
        cli.COLOR = old


def test_unknown_command_lists_valid_ones():
    res = cli.main(["noexiste"])
    assert "error" in res
    assert "status" in res["error"] and "memory" in res["error"]


def test_no_args_defaults_to_status():
    called = []
    old = cli.CLI["status"]
    try:
        cli.CLI["status"] = lambda *a: called.append(a) or {"message": "ok"}
        assert cli.main([]) == {"message": "ok"}
        assert called == [()]
    finally:
        cli.CLI["status"] = old


def test_bad_arity_is_a_usage_error():
    old = cli.CLI["status"]
    try:
        cli.CLI["status"] = lambda: {"message": "ok"}
        res = cli.main(["status", "de", "mas"])
        assert res["error"].startswith("uso: sto status")
    finally:
        cli.CLI["status"] = old


def test_ui_rejects_extra_args_instead_of_opening():
    # `sto ui junk` must not open the TUI silently: same arity error as any
    # other command. It must not really import ui.
    res = cli.main(["ui", "basura"])
    assert res["error"].startswith("uso: sto ui")


def _rows(*specs):
    """specs: (id, project, title, mtime, machine)"""
    return [{"id": i, "project": p, "title": t, "mtime": m, "machine": mc,
             "n_prompts": 3, "n_tools": 7, "errors": 0, "path": f"/tmp/{i}.jsonl"}
            for i, p, t, m, mc in specs]


def test_sessions_groups_by_project():
    rows = _rows(("aaaaaaaa-1", "projA", "hacer X", 200.0, None),
                 ("bbbbbbbb-2", "projA", "hacer Y", 100.0, "OtraPC"),
                 ("cccccccc-3", "projB", "hacer Z", 300.0, None))
    old, cli.COLOR = cli.COLOR, False
    try:
        cli.cached_sessions = lambda *a, **k: (rows, {})
        msg = cli.cmd_sessions()["message"]
        lines = msg.splitlines()
        assert "projB" in lines[0]           # most recent first
        assert "projA" in lines[1]
        assert "2 sesiones" in lines[1]
        assert "OtraPC" in lines[1]
    finally:
        cli.COLOR = old
        _restore_cached()


def test_sessions_of_one_project_and_long_name_alignment():
    largo = "un-proyecto-con-nombre-larguisimo-que-pasa-la-columna"
    rows = _rows(("aaaaaaaa-1", largo, "hacer X", 200.0, None))
    old, cli.COLOR = cli.COLOR, False
    try:
        cli.cached_sessions = lambda *a, **k: (rows, {})
        assert largo in cli.cmd_sessions()["message"]      # not clipped, does not blow up
        msg = cli.cmd_sessions(largo)["message"]
        assert "aaaaaaaa" in msg and "hacer X" in msg
        assert "error" in cli.cmd_sessions("noexiste")
        assert "sto sessions" in cli.cmd_sessions("noexiste")["error"]
    finally:
        cli.COLOR = old
        _restore_cached()


def test_sessions_empty():
    old_cached = cli.cached_sessions
    try:
        cli.cached_sessions = lambda *a, **k: ([], {})
        assert "error" in cli.cmd_sessions()
    finally:
        cli.cached_sessions = old_cached


_REAL_CACHED = cli.cached_sessions


def _restore_cached():
    cli.cached_sessions = _REAL_CACHED


def test_resolve_id_unique_missing_and_ambiguous():
    rows = _rows(("aaaaaaaa-1111", "projA", "hacer X", 200.0, None),
                 ("aaaaaaaa-2222", "projA", "hacer Y", 100.0, None),
                 ("bbbbbbbb-3333", "projB", "hacer Z", 300.0, None))
    row, err = cli.resolve_id("bbbb", rows)
    assert err is None and row["id"] == "bbbbbbbb-3333"

    row, err = cli.resolve_id("zzzz", rows)
    assert row is None and "no existe" in err and "sto sessions" in err

    row, err = cli.resolve_id("aaaa", rows)
    assert row is None and "ambiguo" in err
    assert "hacer X" in err and "hacer Y" in err


def test_show_renders_roles_and_returns_footer():
    rows = _rows(("aaaaaaaa-1111", "projA", "hacer X", 200.0, None))
    paged = []
    old_color, cli.COLOR = cli.COLOR, False
    old_page, old_tl = cli.page, cli.srv.session_timeline
    try:
        cli.cached_sessions = lambda *a, **k: (rows, {})
        cli.page = paged.append
        cli.srv.session_timeline = lambda p: {"id": "aaaaaaaa-1111", "project": "projA",
            "timeline": [{"role": "user", "text": "hola"},
                         {"role": "assistant", "text": "chau"},
                         {"role": "tool", "tool": "Bash", "detail": "ls -la"},
                         {"role": "error", "text": "boom"},
                         {"role": "image", "media_type": "image/png", "data": "x"}]}
        res = cli.cmd_show("aaaa")
        assert "aaaaaaaa" in res["message"]
        body = paged[0]
        assert "hola" in body and "chau" in body and "boom" in body
        assert "Bash" in body and "ls -la" in body
        assert "[imagen]" in body
        assert "error" not in res
        assert "error" in cli.cmd_show()          # no id
        assert "error" in cli.cmd_show("zzzz")    # id inexistente
    finally:
        cli.COLOR, cli.page, cli.srv.session_timeline = old_color, old_page, old_tl
        _restore_cached()


def test_search_snippet_highlights_and_falls_back_to_title():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.jsonl"
        largo = "x" * 100
        p.write_text(json.dumps({"type": "user", "message": {
            "role": "user", "content": f"{largo} arreglar el SYNC de memoria {largo}"}}),
            encoding="utf-8")
        row = {"id": "aaaaaaaa-1", "project": "projA", "title": "titulo",
               "mtime": 1.0, "machine": None, "n_prompts": 1, "n_tools": 0,
               "errors": 0, "path": str(p)}
        old, cli.COLOR = cli.COLOR, True
        try:
            frag = cli.snippet(row, ["sync"])
            assert "\033[33mSYNC\033[0m" in frag   # highlights, keeping the casing
            assert frag.startswith("…") and frag.endswith("…")
            assert len(frag) < 200                  # a slice, not the whole prompt
            assert cli.snippet(row, ["inexistente"]) == "titulo"

            # second term: if the first one is in no prompt, it tries the next
            frag2 = cli.snippet(row, ["inexistente", "sync"])
            assert "\033[33mSYNC\033[0m" in frag2
        finally:
            cli.COLOR = old


def test_search_splits_quoted_phrase_into_terms_for_snippet():
    """sto search "sto cli" (a single argv) must split into terms just like
    sto search sto cli (two argv), so that snippet() does not fall back to the
    title by looking for the whole literal phrase."""
    rows = _rows(("aaaaaaaa-1", "projA", "hacer algo", 1.0, None))
    captured = []
    old_color, cli.COLOR = cli.COLOR, False
    old_search, old_snip = cli.srv.search_sessions, cli.snippet
    try:
        cli.cached_sessions = lambda *a, **k: (rows, {})
        cli.srv.search_sessions = lambda q, **k: rows
        cli.snippet = lambda row, terms: captured.append(terms) or "frag"
        cli.cmd_search("sto cli")            # a single quoted argv
        assert captured[-1] == ["sto", "cli"]
        cli.cmd_search("arreglar", "sync")   # two argv, unquoted
        assert captured[-1] == ["arreglar", "sync"]
    finally:
        cli.COLOR, cli.srv.search_sessions, cli.snippet = old_color, old_search, old_snip
        _restore_cached()


def test_search_lists_hits_and_reports_extras():
    rows = _rows(*[(f"{i:08d}-1", "projA", f"hacer {i}", float(i), None)
                   for i in range(15)])
    old_color, cli.COLOR = cli.COLOR, False
    old_search, old_snip = cli.srv.search_sessions, cli.snippet
    try:
        cli.cached_sessions = lambda *a, **k: (rows, {})
        cli.srv.search_sessions = lambda q, **k: rows
        cli.snippet = lambda row, term: row["title"]
        msg = cli.cmd_search("hacer")["message"]
        assert msg.count("hacer") >= 10
        assert "y 5 más" in msg
        assert "error" in cli.cmd_search()
        cli.srv.search_sessions = lambda q, **k: []
        assert "sin resultados" in cli.cmd_search("nada")["message"]
    finally:
        cli.COLOR, cli.srv.search_sessions, cli.snippet = old_color, old_search, old_snip
        _restore_cached()


def test_skills_lists_and_shows():
    paged = []
    old_color, cli.COLOR = cli.COLOR, False
    old_list, old_get, old_page = cli.srv.list_skills, cli.srv.get_skill, cli.page
    try:
        cli.srv.list_skills = lambda: [
            {"id": "personal:brainstorming", "name": "brainstorming",
             "source": "personal", "description": "convertir ideas en specs"},
            {"id": "plugin:ponytail", "name": "ponytail",
             "source": "plugin", "description": "dev vago"}]
        msg = cli.cmd_skills()["message"]
        assert "personal:brainstorming" in msg and "dev vago" in msg

        cli.srv.get_skill = lambda sid: (
            {"id": sid, "name": "ponytail", "source": "plugin", "description": "d",
             "path": "/x/y", "body": "cuerpo del skill", "content": "---\n---\ncuerpo"}
            if sid == "plugin:ponytail" else None)
        cli.page = paged.append
        res = cli.cmd_skills("plugin:ponytail")
        assert "cuerpo del skill" in paged[0]
        assert "error" not in res

        err = cli.cmd_skills("ponytail")["error"]     # id incompleto
        assert "plugin:ponytail" in err               # suggests the one that matches
        err2 = cli.cmd_skills("noexiste")["error"]
        assert "sto skills" in err2
    finally:
        cli.COLOR, cli.srv.list_skills, cli.srv.get_skill, cli.page = (
            old_color, old_list, old_get, old_page)


def test_usage_renders_limits_and_warns_without_ccusage():
    old_color, cli.COLOR = cli.COLOR, False
    old_snap = cli.srv.usage_snapshot
    try:
        cli.srv.usage_snapshot = lambda detail=True: {
            "block": None, "daily": [],
            "limits": [{"kind": "session", "label": None, "percent": 23,
                        "resetsAt": "2026-08-14T04:30:00.318370+00:00"},
                       {"kind": "weekly_all", "label": None, "percent": 91,
                        "resetsAt": "2026-08-19T09:00:00+00:00"}],
            "error": "ccusage unavailable"}
        msg = cli.cmd_usage()["message"]
        assert "session" in msg and "23%" in msg
        assert "weekly_all" in msg and "91%" in msg
        assert "2026-08-14 04:30" in msg
        assert "ccusage unavailable" in msg      # it warns, it does not blow up

        cli.srv.usage_snapshot = lambda detail=True: {
            "block": None, "error": None, "limits": None,
            "daily": [{"date": "2026-08-12", "inputTokens": 1000,
                       "outputTokens": 500, "totalCost": 1.5}]}
        msg2 = cli.cmd_usage()["message"]
        assert "2026-08-12" in msg2 and "1,500" in msg2 and "1.50" in msg2

        cli.srv.usage_snapshot = lambda detail=True: {"block": None, "daily": [], "limits": None,
                                          "error": "ccusage unavailable"}
        assert "error" in cli.cmd_usage()        # nothing to show at all: that is an error
    finally:
        cli.COLOR, cli.srv.usage_snapshot = old_color, old_snap


def test_machines_marks_the_local_one():
    old_color, cli.COLOR = cli.COLOR, False
    old_lm = cli.srv.list_machines
    try:
        cli.srv.list_machines = lambda: {"LaptopA": {"type": "laptop", "local": True},
                                         "DeskB": {"type": "desktop", "local": False}}
        msg = cli.cmd_machines()["message"]
        assert "LaptopA" in msg and "laptop" in msg and "(esta)" in msg
        assert msg.count("(esta)") == 1
    finally:
        cli.COLOR, cli.srv.list_machines = old_color, old_lm


_GRAPH = {
    "nodes": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"},
              {"id": "cc", "label": "Gamma"}, {"id": "d", "label": "Huerfano"},
              {"id": "e", "label": "Alpina"}],
    "links": [{"source": "a", "target": "b", "relation": "contains"},
              {"source": "a", "target": "cc", "relation": "imports"},
              {"source": "b", "target": "cc", "relation": "calls"}],
}


MEM = """---
name: regla-a
description: No usar borde vertical dorado
metadata:
  type: feedback
---

Cuerpo de la memoria A. Ver [[otra]].
"""


def test_memory_lists_shows_and_searches():
    with tempfile.TemporaryDirectory() as d:
        km = Path(d) / "km"
        (km / "C--x-Projects-proyA" / "PC").mkdir(parents=True)
        (km / "C--x-Projects-proyA" / "PC" / "regla-a.md").write_text(MEM, encoding="utf-8")
        real = cli.srv.KNOWLEDGE_MEMORY
        old, cli.COLOR = cli.COLOR, False
        try:
            cli.srv.KNOWLEDGE_MEMORY = km
            # the listing uses the short name, not the flattened path
            assert "proyA" in cli.cmd_memory()["message"]
            assert "C--x" not in cli.cmd_memory()["message"]
            # …and the lookup takes both the short name and the whole slug
            assert "regla-a" in cli.cmd_memory("proyA")["message"]
            assert "regla-a" in cli.cmd_memory("C--x-Projects-proyA")["message"]
            assert "desconocido" in cli.cmd_memory("noExiste")["error"]
            assert "Cuerpo de la memoria A" in cli.cmd_memory("show", "proyA/regla-a")["message"]
            assert "no existe" in cli.cmd_memory("show", "proyA/nada")["error"]
            assert "proyA/regla-a" in cli.cmd_memory("search", "borde vertical")["message"]
            assert "sin resultados" in cli.cmd_memory("search", "zzzz")["message"]
            assert "uso:" in cli.cmd_memory("search")["error"]
        finally:
            cli.srv.KNOWLEDGE_MEMORY = real
            cli.COLOR = old


def test_status_and_config_print_text_not_json():
    reales = (cli.srv.sync_status, cli.srv.get_sync_prefs, cli.srv.CONFIG_MODULES)
    old, cli.COLOR = cli.COLOR, False
    try:
        cli.srv.sync_status = lambda *a, **k: {
            "remote": "git@github.com:yo/sto.git", "branch": "main", "ahead": 3,
            "behind": 0, "dirty": True, "machine": "PC", "fetchError": None}
        cli.srv.get_sync_prefs = lambda: ["skills"]
        cli.srv.CONFIG_MODULES = {"skills": (), "hooks": ()}
        msg = cli.cmd_status()["message"]
        assert "main" in msg and "3" in msg and "{" not in msg      # nada de JSON
        cfg = cli.cmd_config()["message"]
        assert "[x] skills" in cfg and "[ ] hooks" in cfg
        cli.srv.sync_status = lambda *a, **k: {
            "remote": None, "branch": None, "ahead": 0, "behind": 0,
            "dirty": False, "machine": "PC", "fetchError": None}
        assert "sto ui" in cli.cmd_status()["error"]
    finally:
        cli.srv.sync_status, cli.srv.get_sync_prefs, cli.srv.CONFIG_MODULES = reales
        cli.COLOR = old


def test_graph_stats_counts_orphans_and_top():
    s = cli.graph_stats(_GRAPH)
    assert s["nodes"] == 5 and s["links"] == 3
    assert s["orphans"] == 2                      # Huerfano y Alpina
    assert s["top"][0] == ("Alpha", 2) or s["top"][0] == ("Gamma", 2)
    assert len(s["top"]) == 3


def test_graph_neighbors_splits_in_and_out():
    n, err = cli.graph_neighbors(_GRAPH, "Beta")
    assert err is None
    assert n["label"] == "Beta"
    assert n["out"] == [("Gamma", "calls")]
    assert n["in"] == [("Alpha", "contains")]

    n, err = cli.graph_neighbors(_GRAPH, "zzz")
    assert n is None and "no hay nodo" in err

    n, err = cli.graph_neighbors(_GRAPH, "Alp")   # Alpha y Alpina
    assert n is None and "ambiguo" in err and "Alpina" in err

    n, err = cli.graph_neighbors(_GRAPH, "alpha")  # exacto gana aunque haya prefijos
    assert err is None and n["label"] == "Alpha"


def test_graph_command_without_file():
    old = cli.srv.GRAPH_JSON
    try:
        cli.srv.GRAPH_JSON = Path("no") / "existe" / "graph.json"
        res = cli.cmd_graph()
        assert "graphify update" in res["error"]
    finally:
        cli.srv.GRAPH_JSON = old


def _con_html(fn):
    """Run fn(html_path) with a fake graph.html in a temp dir."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        html = Path(d) / "graph.html"
        html.write_text("<html></html>", encoding="utf-8")
        viejo = cli.GRAPH_HTML
        try:
            cli.GRAPH_HTML = html
            return fn(html)
        finally:
            cli.GRAPH_HTML = viejo


def test_graph_open_launches_a_chromeless_window():
    def caso(html):
        lanzados, real = [], cli.find_app_browser
        try:
            cli.find_app_browser = lambda: r"C:\x\msedge.exe"
            res = cli.open_graph(launcher=lambda cmd, **kw: lanzados.append(cmd),
                                 fallback=lambda url: lanzados.append(("browser", url)))
            assert "ventana" in res["message"] and "error" not in res
            cmd = lanzados[0]
            assert cmd[0].endswith("msedge.exe")
            # --app is what removes tabs, address bar and menu
            assert any(a.startswith("--app=") for a in cmd)
            assert html.resolve().as_uri() in cmd[1]
            assert not any(a == ("browser", html.as_uri()) for a in lanzados)
        finally:
            cli.find_app_browser = real
    _con_html(caso)


def test_ui_ink_falls_back_to_the_stdlib_tui_when_node_is_missing():
    """The Ink flavour is a preference, not a requirement.

    A machine without Node still has to get a TUI when it asks for one, so the
    missing runtime is a printed line and the usual screen — not an error that
    leaves the user with nothing.
    """
    import sys
    import types
    abierto, real_which = [], cli.shutil.which
    fake_ui = types.ModuleType("ui")
    fake_ui.run = lambda: abierto.append("stdlib") or {"message": ""}
    sys.modules["ui"] = fake_ui
    try:
        cli.shutil.which = lambda name: None
        cli.cmd_ui("--ink")
        assert abierto == ["stdlib"], abierto
    finally:
        cli.shutil.which = real_which
        sys.modules.pop("ui", None)


def test_ui_takes_no_flag_it_does_not_know():
    """`--web` today is a typo, not a third flavour: it has to say so rather
    than silently opening the default one."""
    try:
        cli.cmd_ui("--web")
        assert False, "an unknown flag went through"
    except TypeError:
        pass


def test_graph_open_falls_back_to_the_browser_without_chromium():
    def caso(html):
        abierto, real = [], cli.find_app_browser
        try:
            cli.find_app_browser = lambda: None
            res = cli.open_graph(launcher=lambda *a, **k: abierto.append("app"),
                                 fallback=abierto.append)
            assert abierto == [html.resolve().as_uri()]
            assert "navegador" in res["message"]     # it says so, it does not hide it
        finally:
            cli.find_app_browser = real
    _con_html(caso)


def test_graph_open_without_the_html():
    viejo = cli.GRAPH_HTML
    try:
        cli.GRAPH_HTML = Path("no") / "existe" / "graph.html"
        res = cli.open_graph(launcher=lambda *a, **k: None, fallback=lambda u: None)
        assert "graphify update" in res["error"]
    finally:
        cli.GRAPH_HTML = viejo


def test_cached_sessions_hides_subagent_sessions_by_default():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projects" / "projA"
        proj.mkdir(parents=True)
        _fake_session(proj, "aaaaaaaa-0000-0000-0000-000000000000.jsonl", "prompt humano")
        _fake_session(proj, "agent-bbbbbbbb-0000-0000-0000-000000000000.jsonl", "brief de subagente")
        args = dict(projects_dir=Path(d) / "projects", knowledge_dir=Path(d) / "knowledge",
                    cache_path=Path(d) / "cache.json")

        rows, _ = cli.cached_sessions(**args)
        assert [r["title"] for r in rows] == ["prompt humano"]

        rows, _ = cli.cached_sessions(include_agents=True, **args)
        assert sorted(r["title"] for r in rows) == ["brief de subagente", "prompt humano"]


def test_timeline_lines_is_what_show_prints():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projects" / "projA"
        proj.mkdir(parents=True)
        f = _fake_session(proj, "cccccccc-0000-0000-0000-000000000000.jsonl", "hola")
        rows, _ = cli.cached_sessions(projects_dir=Path(d) / "projects",
                                      knowledge_dir=Path(d) / "knowledge",
                                      cache_path=Path(d) / "cache.json")
        lines = cli.timeline_lines(rows[0])
        assert lines[0].startswith("projA")
        assert any("hola" in l for l in lines)



def test_the_graph_window_is_painted_in_the_accent_you_picked():
    """The window is the one surface outside the TUI that carries the accent,
    and it was hardcoded turquoise however the config was set."""
    assert cli.MEMORY_TEMPLATE.read_text(encoding="utf-8").count(
        cli.TEMPLATE_ACCENT) == 1, "the template stopped declaring the accent"
    root = pathlib.Path(tempfile.mkdtemp()) / "memory" / "proj" / "PC"
    root.mkdir(parents=True)
    (root / "n.md").write_text("cuerpo", encoding="utf-8")
    real_mem, real_prefs = cli.srv.KNOWLEDGE_MEMORY, cli.i18n.get_prefs
    try:
        cli.srv.KNOWLEDGE_MEMORY = root.parent.parent
        cli.i18n.get_prefs = lambda: {"accent": "35"}
        html = cli.build_memory_graph(
            dest=pathlib.Path(tempfile.mkdtemp()) / "g.html").read_text(encoding="utf-8")
        assert f'--accent:{cli.ACCENT_HEX["35"]}' in html, "the window ignored the accent"
        assert cli.TEMPLATE_ACCENT not in html
        # the node palette is a legend, not chrome: it does not follow the accent
        assert 'project:"#2bd6c4"' in html
        cli.i18n.get_prefs = lambda: {}          # never configured → default
        html = cli.build_memory_graph(
            dest=pathlib.Path(tempfile.mkdtemp()) / "g.html").read_text(encoding="utf-8")
        assert f'--accent:{cli.ACCENT_HEX["36"]}' in html
    finally:
        cli.srv.KNOWLEDGE_MEMORY, cli.i18n.get_prefs = real_mem, real_prefs


def test_memory_graph_carries_the_body_so_the_window_can_read_it():
    """The graph window is one offline HTML file with no server behind it, so
    `read memory` only works if the text travelled inside the JSON."""
    import tempfile
    root = Path(tempfile.mkdtemp()) / "memory" / "proj" / "PC"
    root.mkdir(parents=True)
    (root / "nota.md").write_text(
        "---\nname: nota\ndescription: una\nmetadata:\n  type: user\n---\n\ncuerpo completo acá.\n",
        encoding="utf-8")
    src = root.parent.parent
    sin = cli.srv.memory_graph(src=src)
    con = cli.srv.memory_graph(src=src, bodies=True)
    mem = lambda g: [n for n in g["nodes"] if n["kind"] == "memory"][0]
    assert "body" not in mem(sin)                    # the API keeps paying nothing
    assert mem(con)["body"] == "cuerpo completo acá."  # frontmatter stripped


def test_the_graph_template_renders_markdown_and_escapes_it():
    """The reader is a markdown subset written by hand (no CDN in an offline
    file). Runs it under node when node is around; skipped otherwise."""
    import shutil as sh
    import subprocess
    import tempfile
    if not sh.which("node"):
        return
    html = cli.MEMORY_TEMPLATE.read_text(encoding="utf-8")
    part = html.split("// ── the reader ──", 1)[1].split("// ── detail panel ──", 1)[0]
    stub = """
const esc = s => String(s).replace(/[<>&]/g, ch => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[ch]));
const nodes = [{id:'p/otra', label:'otra', kind:'memory', type:'user', machine:'PC',
                mtime:0, project:'p', body:''}];
const byId = new Map(nodes.map(n => [n.id, n]));
const day = () => '';
const document = {getElementById: () => ({classList:{add(){},remove(){},contains:()=>false},
  querySelectorAll:()=>[], set innerHTML(v){}, set textContent(v){}, set onclick(v){}, scrollTop:0})};
"""
    tail = """
const html = md(['# T', '', 'a **b** `c` [[otra]] [[nadie]].', 'sigue.', '',
                 '- uno', '', '```', '<script>x</script>', '```'].join(String.fromCharCode(10)));
const must = ['<h3>T</h3>', '<b>b</b>', '<code>c</code>', 'class="wiki" data-id="p/otra"',
              'class="dead"', '<ul><li>uno</li></ul>', '&lt;script&gt;x&lt;/script&gt;',
              'sigue.</p>'];
let bad = must.filter(m => !html.includes(m));
if (html.includes('<script>')) bad.push('raw script survived');
if (bad.length) { console.error(bad.join(' | ')); process.exit(1); }
"""
    d = Path(tempfile.mkdtemp()) / "reader.js"
    d.write_text(stub + part + tail.replace("`", chr(96)), encoding="utf-8")
    r = subprocess.run(["node", str(d)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr




def test_the_graph_html_survives_a_memory_that_quotes_markup():
    """Two real bugs, both fired the day memory bodies started travelling:

    1. a memory quoting `<script` put the HTML tokenizer into double-escaped
       state, so the real closing tag stopped closing the block;
    2. the template mentioned the data placeholder in its own opening comment,
       so the substitution hit both copies — and a memory quoting an HTML
       comment terminator closed that comment early and dumped the entire
       graph into the page as text.
    """
    import tempfile
    tpl = cli.MEMORY_TEMPLATE.read_text(encoding="utf-8")
    assert tpl.count(cli.PLACEHOLDER) == 1      # bug 2: one copy, in the script

    nasty = '<script>x</script> <!-- y --> ' + repr(chr(0x2028))[1:-1]
    out = cli._embeddable(json.dumps({"body": nasty + chr(0x2028)}))
    assert "<" not in out                      # bug 1: no raw markup at all
    assert chr(0x2028) not in out               # legal JSON, a newline to JS
    assert json.loads(out)["body"].startswith(nasty)   # and it still round-trips

    root = Path(tempfile.mkdtemp()) / "memory" / "proj" / "PC"
    root.mkdir(parents=True)
    (root / "n.md").write_text("cuerpo con <script>alert(1)</script> y <!-- x -->",
                               encoding="utf-8")
    real = cli.srv.KNOWLEDGE_MEMORY
    try:
        cli.srv.KNOWLEDGE_MEMORY = root.parent.parent
        built = cli.build_memory_graph(dest=Path(tempfile.mkdtemp()) / "g.html")
    finally:
        cli.srv.KNOWLEDGE_MEMORY = real
    html = built.read_text(encoding="utf-8")
    # the page still ends where it should: one script, one canvas, and the
    # markup the memory quoted never became markup
    assert html.count("</script>") == 1
    assert html.index("<canvas") < html.index("<script>")
    assert "alert(1)" in html and "<script>alert(1)" not in html



if __name__ == "__main__":
    test_cached_sessions_reuses_entry_and_reparses_on_change()
    test_cached_sessions_drops_deleted_and_survives_corrupt_cache()
    test_search_finds_prompts_reloaded_from_cache()
    test_color_off_emits_no_ansi()
    test_unknown_command_lists_valid_ones()
    test_no_args_defaults_to_status()
    test_bad_arity_is_a_usage_error()
    test_ui_rejects_extra_args_instead_of_opening()
    test_sessions_groups_by_project()
    test_sessions_of_one_project_and_long_name_alignment()
    test_sessions_empty()
    test_resolve_id_unique_missing_and_ambiguous()
    test_show_renders_roles_and_returns_footer()
    test_search_snippet_highlights_and_falls_back_to_title()
    test_search_splits_quoted_phrase_into_terms_for_snippet()
    test_search_lists_hits_and_reports_extras()
    test_skills_lists_and_shows()
    test_usage_renders_limits_and_warns_without_ccusage()
    test_machines_marks_the_local_one()
    test_memory_lists_shows_and_searches()
    test_status_and_config_print_text_not_json()
    test_graph_stats_counts_orphans_and_top()
    test_graph_neighbors_splits_in_and_out()
    test_graph_command_without_file()
    test_graph_open_launches_a_chromeless_window()
    test_graph_open_falls_back_to_the_browser_without_chromium()
    test_ui_ink_falls_back_to_the_stdlib_tui_when_node_is_missing()
    test_ui_takes_no_flag_it_does_not_know()
    test_graph_open_without_the_html()
    test_cached_sessions_hides_subagent_sessions_by_default()
    test_timeline_lines_is_what_show_prints()
    test_the_graph_window_is_painted_in_the_accent_you_picked()
    test_memory_graph_carries_the_body_so_the_window_can_read_it()
    test_the_graph_template_renders_markdown_and_escapes_it()
    test_the_graph_html_survives_a_memory_that_quotes_markup()
    print("OK")
