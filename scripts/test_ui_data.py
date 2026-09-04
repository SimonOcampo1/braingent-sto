"""The half of the old `test_ui.py` that outlived the stdlib TUI.

`ui.py` became `ui_data.py` when the rendering half was deleted; 141 of those
163 tests drove screens that no longer exist. These 22 cover the logic that
stayed — parity, sync preview, search, module items, the i18n contract — and
they are here so removing a front-end did not quietly remove its coverage too.
"""

import json
import os
import time
import tempfile
from pathlib import Path

import cli
import i18n
import sessions_server as srv
import ui_data as ui

# cli.COLOR is False when stdout is not a tty - that is, always while the tests
# run. Forced to True to exercise the ANSI path: it is the one that runs for
# real, and the only one where strip_ansi() has anything to do.
cli.COLOR = True
i18n.LANG = "es"   # los asserts de abajo son sobre los strings en castellano


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


def _config_st(w=96):
    st = ui.new_state()
    st["tab"], st["w"] = CFG, w
    return ui.reload_tab(st)


def _wait_job(st, limite=5.0):
    """Corre `tick()` hasta que el hilo del push/pull termina."""
    fin = time.monotonic() + limite
    while st["job"] and time.monotonic() < fin:
        st = ui.tick(st)
    assert st["job"] is None, "the job never finished"
    return st


def _pictographic(code):
    """Emoji and the symbol blocks that read as emoji.

    Block Elements, Box Drawing, Geometric Shapes and arrows are deliberately
    NOT here: those draw the interface. A bar is a bar and a filled circle is a
    state. A gear, a check mark and a framed square are decoration.
    """
    return (0x1F300 <= code <= 0x1FAFF          # emoji proper
            or 0x2600 <= code <= 0x27BF         # misc symbols and dingbats
            or 0x2B00 <= code <= 0x2BFF
            or code in (0xFE0F, 0x200D))        # variation selector, ZWJ


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


def test_reset_at_converts_utc_to_local_and_survives_junk():
    from datetime import datetime, timezone
    utc = datetime(2026, 8, 14, 18, 0, tzinfo=timezone.utc)
    assert ui._reset_at("2026-08-14T18:00:00Z") == f"resetea {utc.astimezone():%H:%M}"
    assert ui._reset_at(None) == ""
    assert ui._reset_at("2026-08-14") == ""
    assert ui._reset_at("mañana") == ""


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


def test_every_term_has_to_hit_somewhere():
    """A search that returns the union of its terms returns everything. And
    where a term hits matters more than how often: a note called `textual` is
    about textual, one that mentions it once in passing is not."""
    name = ui._score(["textual"], "sto-tui-textual", "", "")
    body = ui._score(["textual"], "other-note", "", "textual appears here")
    assert name > body, (name, body)
    assert ui._score(["textual", "grid"], "sto-tui-textual", "", "") == 0.0
    assert ui._score(["textual", "grid"], "sto-tui-textual", "", "a grid here") > 0

    # more mentions is worth something, but never as much as being the title
    many = ui._score(["grid"], "note", "", "grid " * 20)
    assert body < many < name, (body, many, name)


def test_the_index_only_re_reads_what_moved():
    """0.44 s of vault scanning per keystroke is not a search box. The index is
    derived from files that stay the source of truth, so it can be wrong only
    for as long as an mtime is."""
    import os
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "note.md"
        f.write_text("first body", encoding="utf-8")
        ui._INDEX.clear()
        first = ui._indexed([f])
        assert "first body" in first[str(f)][1]

        reads = []
        real = Path.read_text
        Path.read_text = lambda self, **kw: (reads.append(self), real(self, **kw))[1]
        try:
            ui._indexed([f])
            assert reads == [], "an unchanged file was read again"
            f.write_text("second body", encoding="utf-8")
            os.utime(f, (0, time.time() + 10))
            again = ui._indexed([f])
            assert reads, "a changed file was not re-read"
            assert "second body" in again[str(f)][1]
        finally:
            Path.read_text = real


def test_search_all_labels_every_hit_with_its_kind():
    """Four corpora into one list, and the row has to say which one it came
    from -- that is the whole difference between a search and a pile."""
    hits = ui.search_all("sto")
    assert isinstance(hits, list)
    assert all({"kind", "label", "sub", "score", "mtime", "ref"} <= set(h)
               for h in hits), hits[:1]
    assert all(h["kind"] in ("session", "memory", "tool", "note") for h in hits)
    assert hits == sorted(hits, key=lambda h: (-h["score"], -h["mtime"]))
    assert ui.search_all("") == []
    assert ui.search_all("   ") == []


def test_no_pictographs_in_the_source():
    """No emoji in anything this project writes, and a test rather than a rule.

    A rule that lives only in an instructions file is a rule that gets broken
    and then argued about; this one gets broken and then fails. It caught a
    gear in front of every tool call of a transcript that had been there for
    months, and it is the reason `_pictographic` draws the line where it does
    rather than wherever the next person remembers it.

    `knowledge/` is exempt and always will be: those are captured transcripts
    and memories. What somebody typed into a session is data, and rewriting
    data to match our own house style is worse than the emoji.
    """
    import re
    import subprocess
    root = Path(ui.__file__).resolve().parent.parent
    listed = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                            text=True, encoding="utf-8")
    if listed.returncode != 0:
        return                                  # not a checkout; nothing to police
    escape = re.compile(r"\\u([0-9a-fA-F]{4})")
    bad = []
    for rel in listed.stdout.splitlines():
        if not rel.strip() or rel.startswith("knowledge/"):
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue                            # binary, or gone
        for n, line in enumerate(text.splitlines(), 1):
            hit = {ord(c) for c in line if _pictographic(ord(c))}
            hit |= {int(m.group(1), 16) for m in escape.finditer(line)
                    if _pictographic(int(m.group(1), 16))}
            for code in sorted(hit):
                bad.append(f"{rel}:{n}  U+{code:04X}")
    assert not bad, "pictographs in tracked source:\n" + "\n".join(bad[:40])


if __name__ == "__main__":
    test_memory_detail_reads_the_markdown()
    test_parity_splits_local_only_repo_only_and_synced()
    test_reset_at_converts_utc_to_local_and_survives_junk()
    test_both_languages_define_the_same_keys()
    test_t_falls_back_to_english_and_then_to_the_key_itself()
    test_last_sync_falls_back_to_question_mark_without_separator()
    test_the_relative_time_is_translated_and_rounds_down()
    test_fetch_moves_the_checked_age_and_the_sync_line_does_not()
    test_classify_groups_paths_by_meaning()
    test_count_items_counts_what_only_a_dry_run_can_see()
    test_the_legend_says_the_key_without_saying_tab_twice()
    test_the_commands_are_translated_too()
    test_a_new_command_shows_up_without_touching_the_help()
    test_switching_language_invalidates_the_cached_header_summary()
    test_module_items_reads_skills_plugins_and_plain_files()
    test_the_three_verbs_are_all_reachable_from_a_module_and_named_in_the_legend()
    test_sync_preview_classifies_both_directions_without_touching_the_network()
    test_preview_parts_names_the_kinds_and_is_empty_when_nothing_travels()
    test_every_term_has_to_hit_somewhere()
    test_the_index_only_re_reads_what_moved()
    test_search_all_labels_every_hit_with_its_kind()
    test_no_pictographs_in_the_source()
    print("OK")
