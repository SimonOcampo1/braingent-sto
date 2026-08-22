import json
import os
import shutil
import tempfile
from pathlib import Path

import agents
import sessions_server as srv
from sessions_server import (
    session_meta, session_timeline, list_sessions, find_path_by_id,
    list_skills, get_skill, export_sessions, search_sessions,
    delete_skill, export_skill_zip, export_config, apply_config, config_status,
    export_plugins, plugins_to_apply, apply_plugins, list_machines, machine_type,
    _memory_meta, _memory_dirs, _newest, export_memory, LOCAL_MACHINE,
    import_memory, rebuild_index, list_memory, _slug_project,
    memory_graph, forget, bring,
)

SAMPLE = [
    {"type": "user", "message": {"role": "user", "content": "First real prompt"}},
    {"type": "user", "message": {"role": "user", "content": "<caveat>noise</caveat>"}},
    {"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "x.py"}},
                    {"type": "text", "text": "ok"}]}},
    {"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "tool_use", "name": "Bash",
                     "input": {"command": "ls -la", "description": "List"}}]}},
    {"type": "user", "message": {"role": "user",
        "content": [{"type": "tool_result", "is_error": True, "content": "boom"}]}},
    {"type": "user", "message": {"role": "user", "content": "leak sk-abcdefghijklmnopqrstuvwxyz123"}},
    "{not valid json",
]


def _write_session(dirpath, name="11111111-2222-3333-4444-555555555555.jsonl"):
    p = Path(dirpath) / name
    p.write_text("\n".join(json.dumps(x) if isinstance(x, dict) else x for x in SAMPLE),
                 encoding="utf-8")
    return p


def _settled(path, age=1000):
    """Backdate a session so `export_sessions` does not read it as still being
    written. Every export test needs it: files created now are `age` 0."""
    import time
    os.utime(path, (time.time() - age, time.time() - age))
    return path


def test_session_meta():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projX"
        proj.mkdir()
        p = _write_session(proj)
        m = session_meta(p)
        assert m["id"] == p.stem, m["id"]
        assert m["project"] == "projX", m["project"]
        assert m["title"] == "First real prompt", m["title"]
        assert m["n_prompts"] == 2, m["n_prompts"]   # 2 real prompts (caveat filtered)
        assert m["n_tools"] == 2, m["n_tools"]
        assert m["errors"] == 1, m["errors"]
        assert isinstance(m["mtime"], float), m["mtime"]


def test_session_meta_redacts_title():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projX"
        proj.mkdir()
        p = proj / "s.jsonl"
        p.write_text(json.dumps(
            {"type": "user", "message": {"role": "user",
             "content": "key sk-abcdefghijklmnopqrstuvwxyz123"}}), encoding="utf-8")
        assert "sk-abcdefghij" not in session_meta(p)["title"]


def test_session_meta_no_prompt():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projX"
        proj.mkdir()
        p = proj / "s.jsonl"
        p.write_text(json.dumps(
            {"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "tool_use", "name": "Read"}]}}), encoding="utf-8")
        assert session_meta(p)["title"] == "(no prompt)"


def test_session_timeline_order_and_redaction():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projX"
        proj.mkdir()
        p = _write_session(proj)
        t = session_timeline(p)["timeline"]
        roles = [it["role"] for it in t]
        assert roles == ["user", "tool", "assistant", "tool", "error", "user"], roles
        assert t[0]["text"] == "First real prompt", t[0]
        assert t[1] == {"role": "tool", "tool": "Edit", "detail": "x.py",
                        "input": {"file_path": "x.py"}}, t[1]
        assert t[2] == {"role": "assistant", "text": "ok"}, t[2]
        assert t[3]["detail"] == "ls -la", t[3]
        assert t[3]["input"] == {"command": "ls -la", "description": "List"}, t[3]
        assert t[4] == {"role": "error", "text": "boom"}, t[4]
        assert "sk-abcdefghij" not in t[5]["text"], t[5]


def test_session_timeline_rich_blocks():
    rows = [
        # user message as content list: text + image
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "look at this"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": "iVBORsmall"}},
        ]}},
        # oversized image → skipped
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": "x" * 400_000}},
        ]}},
        # error with structured content list
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "is_error": True,
             "content": [{"type": "text", "text": "Trace: " + "y" * 500}]},
        ]}},
    ]
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projX"
        proj.mkdir()
        p = proj / "s.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        t = session_timeline(p)["timeline"]
        roles = [it["role"] for it in t]
        assert roles == ["user", "image", "error"], roles
        assert t[0]["text"] == "look at this", t[0]
        assert t[1]["media_type"] == "image/png" and t[1]["data"] == "iVBORsmall", t[1]
        assert t[2]["text"].startswith("Trace:"), t[2]
        assert len(t[2]["text"]) <= 320, len(t[2]["text"])  # capped snippet


def test_list_and_find_by_id():
    import platform
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as k:
        proj = Path(d) / "projX"
        proj.mkdir()
        p = _write_session(proj)
        # session with zero prompts → filtered out of the list
        empty = proj / "empty.jsonl"
        empty.write_text(json.dumps(
            {"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "tool_use", "name": "Read"}]}}), encoding="utf-8")
        # synced session from another machine (knowledge/sessions/<machine>/<project>/)
        other = Path(k) / "OtherPC" / "projZ"
        other.mkdir(parents=True)
        p2 = _write_session(other, name="22222222-2222-3333-4444-555555555555.jsonl")
        # own machine's export of a session Claude Code already pruned locally:
        # it is still ours (machine → null) and still listed
        own = Path(k) / (platform.node() or "local") / "projX"
        own.mkdir(parents=True)
        pruned = _write_session(own, name="33333333-2222-3333-4444-555555555555.jsonl")
        # and an export whose local copy is alive: the live file wins
        _write_session(own, name=p.name)

        rows = list_sessions(projects_dir=Path(d), knowledge_dir=Path(k))
        ids = {r["id"] for r in rows}
        assert p.stem in ids and p2.stem in ids, ids
        assert empty.stem not in ids, ids           # no-prompt filtered
        assert pruned.stem in ids, ids
        assert len([r for r in rows if r["id"] == p.stem]) == 1, rows
        by_id = {r["id"]: r for r in rows}
        assert by_id[p2.stem]["machine"] == "OtherPC", by_id[p2.stem]
        assert by_id[p.stem]["machine"] is None, by_id[p.stem]  # local → null
        assert by_id[p2.stem]["project"] == "projZ", by_id[p2.stem]
        assert by_id[pruned.stem]["machine"] is None, by_id[pruned.stem]
        assert find_path_by_id(p.stem, projects_dir=Path(d), knowledge_dir=Path(k)) == p
        assert find_path_by_id(pruned.stem, projects_dir=Path(d),
                               knowledge_dir=Path(k)) == pruned
        assert find_path_by_id(p2.stem, projects_dir=Path(d), knowledge_dir=Path(k)) == p2
        assert find_path_by_id("nope", projects_dir=Path(d), knowledge_dir=Path(k)) is None


SKILL_MD = """---
name: my-skill
description: Does a thing
---

Body here.
"""


def _make_claude_dir(d):
    """Fake ~/.claude with one personal skill and one plugin skill."""
    claude = Path(d) / "claude"
    (claude / "skills" / "my-skill").mkdir(parents=True)
    (claude / "skills" / "my-skill" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (claude / "skills" / "empty-dir").mkdir()  # no SKILL.md → skipped

    plug = claude / "plugins" / "cache" / "market" / "myplugin" / "1.0"
    (plug / "skills" / "pskill").mkdir(parents=True)
    (plug / "skills" / "pskill" / "SKILL.md").write_text(
        "---\nname: pskill\ndescription: Plugin skill\n---\nbody", encoding="utf-8")
    (claude / "plugins").mkdir(exist_ok=True)
    (claude / "plugins" / "installed_plugins.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"myplugin@market": [{"installPath": str(plug)}]},
    }), encoding="utf-8")
    return claude


def test_list_skills():
    with tempfile.TemporaryDirectory() as d:
        claude = _make_claude_dir(d)
        rows = list_skills(claude_dir=claude)
        ids = {r["id"] for r in rows}
        assert "personal:my-skill" in ids, ids
        assert "myplugin:pskill" in ids, ids
        assert len(rows) == 2, rows  # empty-dir skipped
        mine = next(r for r in rows if r["id"] == "personal:my-skill")
        assert mine["name"] == "my-skill", mine
        assert mine["description"] == "Does a thing", mine
        assert mine["source"] == "personal", mine


def test_get_skill():
    with tempfile.TemporaryDirectory() as d:
        claude = _make_claude_dir(d)
        s = get_skill("personal:my-skill", claude_dir=claude)
        assert s is not None
        assert "Body here." in s["content"], s
        assert s["body"].startswith("Body here."), s["body"]  # frontmatter stripped
        assert s["description"] == "Does a thing", s
        assert get_skill("personal:nope", claude_dir=claude) is None
        assert get_skill("garbage", claude_dir=claude) is None


def test_delete_and_export_skill():
    import io
    import zipfile
    with tempfile.TemporaryDirectory() as d:
        claude = _make_claude_dir(d)
        # export produces a valid zip containing SKILL.md
        blob = export_skill_zip("personal:my-skill", claude_dir=claude)
        assert blob is not None
        names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
        assert any(n.endswith("SKILL.md") for n in names), names
        assert export_skill_zip("personal:nope", claude_dir=claude) is None
        # delete: only personal, no traversal, must exist
        assert delete_skill("myplugin:pskill", claude_dir=claude) is not None
        assert delete_skill("personal:../secret", claude_dir=claude) is not None
        assert delete_skill("personal:nope", claude_dir=claude) is not None
        assert delete_skill("personal:my-skill", claude_dir=claude) is None
        assert not (claude / "skills" / "my-skill").exists()


def test_forget_removes_from_the_repo_and_never_from_the_machine():
    """`forget` is the repo half of a deletion: chezmoi's split between
    `forget` (source state) and `destroy` (source state + disk)."""
    with tempfile.TemporaryDirectory() as d:
        claude = _make_claude_dir(d)
        cfg = Path(d) / "knowledge" / "config"
        (cfg / "skills" / "skills" / "gone").mkdir(parents=True)
        (cfg / "skills" / "skills" / "gone" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        (cfg / "skills" / "skills" / "gone" / "ref.md").write_text("x", encoding="utf-8")
        # a skill this machine still has: forgetting it would be undone by the
        # export inside the very next push, so it is refused instead
        (cfg / "skills" / "skills" / "my-skill").mkdir(parents=True)
        (cfg / "skills" / "skills" / "my-skill" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")

        paths, err = forget("skill:gone", claude_dir=claude, repo_config=cfg)
        assert err is None, err
        assert len(paths) == 2, paths                      # dry run lists the insides
        assert (cfg / "skills" / "skills" / "gone").is_dir()  # and removes nothing

        assert forget("skill:my-skill", claude_dir=claude, repo_config=cfg)[1] is not None
        assert forget("skill:../secret", claude_dir=claude, repo_config=cfg)[1] is not None
        assert forget("skill:nope", claude_dir=claude, repo_config=cfg)[1] is not None
        assert forget("garbage", claude_dir=claude, repo_config=cfg)[1] is not None

        _, err = forget("skill:gone", apply=True, claude_dir=claude, repo_config=cfg)
        assert err is None, err
        assert not (cfg / "skills" / "skills" / "gone").exists()
        assert (claude / "skills" / "my-skill" / "SKILL.md").is_file()  # local untouched


def test_forget_drops_a_plugin_from_the_manifest_without_touching_the_others():
    with tempfile.TemporaryDirectory() as d:
        claude = _make_claude_dir(d)
        cfg = Path(d) / "knowledge" / "config"
        (cfg / "plugins").mkdir(parents=True)
        (cfg / "plugins" / "plugins.json").write_text(json.dumps({
            "marketplaces": {"market": "someone/repo"},
            "plugins": ["myplugin@market", "stale@market"],
        }), encoding="utf-8")

        # still installed here → refused, the export would list it again
        assert forget("plugin:myplugin@market", claude_dir=claude, repo_config=cfg)[1] is not None
        assert forget("plugin:absent@market", claude_dir=claude, repo_config=cfg)[1] is not None

        _, err = forget("plugin:stale@market", apply=True, claude_dir=claude, repo_config=cfg)
        assert err is None, err
        left = json.loads((cfg / "plugins" / "plugins.json").read_text(encoding="utf-8"))
        assert left["plugins"] == ["myplugin@market"], left
        assert left["marketplaces"] == {"market": "someone/repo"}, left


def test_forget_takes_another_machines_memory_which_no_export_of_ours_reaches():
    """The documented ceiling in the wiki: deleting a memory that belongs to
    another machine never propagated, because `export_memory` only mirrors this
    machine's folder. This is the supported way to do it."""
    with tempfile.TemporaryDirectory() as d:
        claude = _make_claude_dir(d)
        mem = Path(d) / "knowledge" / "memory"
        other = mem / "proj" / "OtherBox"
        other.mkdir(parents=True)
        (other / "old-lesson.md").write_text("---\nname: old\n---\nbody", encoding="utf-8")

        assert forget("memory:proj/OtherBox", claude_dir=claude, repo_memory=mem)[1] is not None
        assert forget("memory:proj/OtherBox/nope", claude_dir=claude, repo_memory=mem)[1] is not None

        paths, err = forget("memory:proj/OtherBox/old-lesson", apply=True,
                            claude_dir=claude, repo_memory=mem)
        assert err is None, err
        assert len(paths) == 1, paths
        assert not (other / "old-lesson.md").exists()


def test_a_skill_the_other_machine_dropped_reads_apart_from_one_never_pushed():
    """El cuarto estado. Las dos situaciones dejan la misma foto en disco
    —local sí, repo no— y solo el historial de git las distingue, que es
    justo lo que ahorra inventar un archivo de tombstones."""
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        skills = repo / "knowledge" / "config" / "skills" / "skills"
        skills.mkdir(parents=True)

        def git(*args):
            subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, check=True)

        git("init", "-q", "-b", "main")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        for name in ("borrada-alla", "sigue"):
            (skills / name).mkdir()
            (skills / name / "SKILL.md").write_text("x", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "las dos")
        # la otra máquina la saca del repo y vos pulleás ese borrado
        shutil.rmtree(skills / "borrada-alla")
        git("add", "-A")
        git("commit", "-qm", "forget borrada-alla")

        real_root, real_cache = srv.REPO_ROOT, dict(srv._DROPPED)
        try:
            srv.REPO_ROOT = repo
            srv._DROPPED.update({"ts": 0.0, "data": None})
            assert srv.dropped_skills(force=True) == {"borrada-alla"}
        finally:
            srv.REPO_ROOT = real_root
            srv._DROPPED.update(real_cache)


def test_the_dropped_lookup_survives_a_repo_git_never_saw():
    """Sin git, o sin historia, la vista tiene que seguir pintándose: el
    cuarto estado es información de más, nunca un requisito."""
    with tempfile.TemporaryDirectory() as d:
        real_root, real_cache = srv.REPO_ROOT, dict(srv._DROPPED)
        try:
            srv.REPO_ROOT = Path(d)
            srv._DROPPED.update({"ts": 0.0, "data": None})
            assert srv.dropped_skills(force=True) == set()
        finally:
            srv.REPO_ROOT = real_root
            srv._DROPPED.update(real_cache)


def test_a_second_agent_is_a_table_entry_and_not_a_patch_across_the_engine():
    """La prueba del borde: un agente con OTRA carpeta y OTROS nombres de
    subdirectorio recorre `_skill_paths` sin que el motor sepa que existe.

    Se define acá y no en `AGENTS` a propósito: declarar dónde viven los
    archivos es necesario y no suficiente — los transcripts todavía tienen que
    ser un formato que `dream_extract` sepa leer. Enviar una entrada de más
    seria prometer soporte que no hay.
    """
    with tempfile.TemporaryDirectory() as d:
        casa = Path(d) / ".otroagente"
        (casa / "habilidades" / "una").mkdir(parents=True)
        (casa / "habilidades" / "una" / "SKILL.md").write_text(
            "---\nname: una\ndescription: de otro agente\n---\ncuerpo", encoding="utf-8")

        agents.AGENTS["fake"] = {"label": "Otro Agente", "dir": ".otroagente",
                                 "skills": "habilidades", "plugins": "extensiones",
                                 "projects": "sesiones"}
        real_env = {k: os.environ.get(k) for k in (agents.AGENT_ENV, agents.HOME_ENV)}
        try:
            os.environ[agents.AGENT_ENV] = "fake"
            os.environ[agents.HOME_ENV] = str(casa)
            assert agents.active_slug() == "fake"
            assert agents.label() == "Otro Agente"
            assert agents.home() == casa
            assert agents.sub("projects") == casa / "sesiones"

            # el motor lo lee sin una sola rama por agente
            filas = srv.list_skills(claude_dir=agents.home())
            assert [r["id"] for r in filas] == ["personal:una"], filas
            assert filas[0]["description"] == "de otro agente"
        finally:
            agents.AGENTS.pop("fake", None)
            for k, v in real_env.items():
                os.environ.pop(k, None) if v is None else os.environ.update({k: v})


def test_an_unknown_agent_falls_back_instead_of_exploding():
    real = os.environ.get(agents.AGENT_ENV)
    try:
        os.environ[agents.AGENT_ENV] = "no-existe"
        assert agents.active_slug() == agents.DEFAULT
    finally:
        os.environ.pop(agents.AGENT_ENV, None) if real is None else \
            os.environ.update({agents.AGENT_ENV: real})


def test_bring_installs_one_skill_the_repo_carries_and_resolves_home():
    """El espejo de `forget`. Sin este verbo, a una fila que el repo tiene y
    esta maquina no solo se le podia hacer una cosa: borrarla del repo."""
    with tempfile.TemporaryDirectory() as d:
        claude = _make_claude_dir(d)
        cfg = Path(d) / "knowledge" / "config"
        (cfg / "skills" / "skills" / "traida").mkdir(parents=True)
        (cfg / "skills" / "skills" / "traida" / "SKILL.md").write_text(
            "---\nname: traida\ndescription: del repo\n---\ncuerpo", encoding="utf-8")
        (cfg / "skills" / "skills" / "traida" / "ref.md").write_text(
            "vive en {{HOME}}/algo", encoding="utf-8")

        paths, err = bring("skill:traida", claude_dir=claude, repo_config=cfg)
        assert err is None, err
        assert len(paths) == 2, paths                       # el seco lista, no copia
        assert not (claude / "skills" / "traida").exists()

        assert bring("skill:nope", claude_dir=claude, repo_config=cfg)[1] is not None
        assert bring("skill:../secret", claude_dir=claude, repo_config=cfg)[1] is not None
        # ya instalada: no hay nada que traer, y decirlo es mejor que copiar encima
        assert bring("skill:my-skill", claude_dir=claude, repo_config=cfg)[1] is not None

        _, err = bring("skill:traida", apply=True, claude_dir=claude,
                       repo_config=cfg, home="C:/casa")
        assert err is None, err
        assert (claude / "skills" / "traida" / "SKILL.md").is_file()
        # pasa por el mismo _apply_tree que el pull, asi que {{HOME}} se resuelve
        ref = (claude / "skills" / "traida" / "ref.md").read_text(encoding="utf-8")
        assert ref == "vive en C:/casa/algo", ref


def test_apply_config_and_bring_share_one_copy_loop():
    """Si `_apply_tree` se rompe, las dos se rompen juntas — que es el punto
    de haberlo sacado afuera en vez de copiar el loop."""
    with tempfile.TemporaryDirectory() as d:
        claude = Path(d) / "claude"
        cfg = Path(d) / "cfg"
        # knowledge/config/<modulo>/<ruta relativa al home del agente>: por eso
        # las skills viven en skills/skills/<nombre> y esto en agents/agents/
        (cfg / "agents" / "agents").mkdir(parents=True)
        (cfg / "agents" / "agents" / "uno.md").write_text("raiz {{HOME}}", encoding="utf-8")

        n = apply_config(["agents"], claude_dir=claude, repo_config=cfg,
                         home="C:/casa", dry=True)
        assert n == 1 and not (claude / "agents").exists()

        n = apply_config(["agents"], claude_dir=claude, repo_config=cfg, home="C:/casa")
        assert n == 1
        assert (claude / "agents" / "uno.md").read_text(encoding="utf-8") == "raiz C:/casa"
        # segunda pasada: identico, no se reescribe (la mtime es el detector de cambios)
        assert apply_config(["agents"], claude_dir=claude, repo_config=cfg,
                            home="C:/casa") == 0


def test_memory_neighbours_is_one_level_and_both_directions():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "memory"
        box = root / "proj" / "Box"
        box.mkdir(parents=True)
        (box / "a.md").write_text(
            "---\nname: a\n---\napunta a [[b]] y nada mas", encoding="utf-8")
        (box / "b.md").write_text(
            "---\nname: b\n---\nb apunta a [[c]]", encoding="utf-8")
        (box / "c.md").write_text("---\nname: c\n---\nhoja", encoding="utf-8")

        out, inc = srv.memory_neighbours("proj", "b", src=root, force=True)
        assert out == ["proj/c"], out
        assert inc == ["proj/a"], inc
        # un nivel: `a` no aparece como vecino de `c`
        out, inc = srv.memory_neighbours("proj", "c", src=root, force=True)
        assert out == [] and inc == ["proj/b"], (out, inc)


def test_memory_neighbours_reuses_the_graphs_own_link_resolution():
    """No re-implementa cómo resuelve un [[wikilink]]: si `memory_graph` no
    dibujó la arista, la vecindad tampoco la inventa."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "memory"
        for proj in ("uno", "dos"):
            (root / proj / "Box").mkdir(parents=True)
            (root / proj / "Box" / "choque.md").write_text(
                "---\nname: choque\n---\nx", encoding="utf-8")
        (root / "uno" / "Box" / "src.md").write_text(
            "---\nname: src\n---\nva a [[choque]]", encoding="utf-8")

        out, _ = srv.memory_neighbours("uno", "src", src=root, force=True)
        # resuelve dentro del proyecto primero, así que no es ambiguo
        assert out == ["uno/choque"], out


def test_home_data_answers_the_whole_home_in_one_payload():
    """One call, and it survives importing `ui` from inside the server.

    `ui` imports `cli` imports this module, so the import has to stay inside
    the function; up top it is a cycle and the server does not start. And the
    keys are a contract: a second front-end paints from them, so dropping one
    is not a rename, it is a blank panel on a screen no Python test opens.
    """
    d = srv.home_data(fetch=False)
    for key in ("agent", "machine", "machines", "usage", "counters", "knowledge",
                "sync", "update", "modules", "localOnly", "repoOnly", "gone",
                "lang", "accent", "strings"):
        assert key in d, key
    for key in ("toPush", "toPull", "pushParts", "pullParts", "lastSync",
                "checkedAgo", "ahead", "behind", "dirty"):
        assert key in d["sync"], key
    # the English fallback `i18n.t()` does is resolved here, not there: the
    # client looks a key up in a dict and has no second table to fall back to
    assert d["strings"]["sec_sync"], "strings did not merge English underneath"
    # the reset is worded on this side for the same reason
    assert all("resets" in l for l in d["usage"]["limits"])


def test_search_sessions():
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as k:
        proj = Path(d) / "projX"
        proj.mkdir()
        p1 = _write_session(proj)  # "First real prompt", "leak sk-…"
        p2 = proj / "s2.jsonl"
        p2.write_text(json.dumps(
            {"type": "user", "message": {"role": "user",
             "content": "arreglar el bug de autenticacion en el login"}}), encoding="utf-8")

        rows = search_sessions("autenticacion login",
                               projects_dir=Path(d), knowledge_dir=Path(k))
        assert rows and rows[0]["id"] == p2.stem, rows
        # content match, not just title
        rows = search_sessions("real prompt", projects_dir=Path(d), knowledge_dir=Path(k))
        assert rows and rows[0]["id"] == p1.stem, rows
        # fuzzy closeness: one-letter typo still finds it
        rows = search_sessions("autentificacion", projects_dir=Path(d), knowledge_dir=Path(k))
        assert rows and rows[0]["id"] == p2.stem, rows
        assert search_sessions("zzz-nothing-matches-этот",
                               projects_dir=Path(d), knowledge_dir=Path(k)) == []


def test_search_sessions_accepts_precomputed_rows():
    from sessions_server import _PROMPTS_INDEX
    rows = [{"id": "s1", "project": "p", "mtime": 2.0, "title": "arreglar el sync",
             "n_prompts": 1, "n_tools": 0, "errors": 0},
            {"id": "s2", "project": "p", "mtime": 1.0, "title": "otra cosa",
             "n_prompts": 1, "n_tools": 0, "errors": 0}]
    _PROMPTS_INDEX["s1"] = "arreglar el sync de memoria"
    _PROMPTS_INDEX["s2"] = "algo totalmente distinto"
    hits = search_sessions("sync", rows=rows)
    assert [h["id"] for h in hits] == ["s1"]


def test_the_skills_row_counts_skills_and_not_the_files_inside_them():
    """The bug: the home said `159 local · 159 in repo` for skills while opening
    that same module listed 32. One was counting every reference and script
    inside each skill folder; both are read as "how many skills"."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as repo:
        src, cfg = Path(a), Path(repo) / "config"
        for name in ("caveman", "tackler"):
            d = src / "skills" / name
            (d / "reference").mkdir(parents=True)
            (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
            (d / "reference" / "notes.md").write_text("filler", encoding="utf-8")
            (d / "run.py").write_text("print()", encoding="utf-8")
        assert srv.count_skills(src) == 2                     # 2 skills, 8 files
        assert sum(1 for _ in srv._module_files(src, "skills")) == 8

        export_config(["skills"], claude_dir=src, repo_config=cfg, home="C:\\x")
        st = {m["id"]: m for m in config_status(claude_dir=src, repo_config=cfg)}
        assert st["skills"]["localFiles"] == 2, st["skills"]
        assert st["skills"]["repoFiles"] == 2, st["skills"]
        # a folder without SKILL.md is not a skill
        (src / "skills" / "loose").mkdir()
        (src / "skills" / "loose" / "notes.md").write_text("x", encoding="utf-8")
        assert srv.count_skills(src) == 2
        # and the other modules still count their files
        (src / "CLAUDE.md").write_text("# rules", encoding="utf-8")
        st = {m["id"]: m for m in config_status(claude_dir=src, repo_config=cfg)}
        assert st["claude-md"]["localFiles"] == 1, st["claude-md"]


def test_the_conflict_error_names_the_files_that_conflicted():
    """The bug: `sto update` reported "Auto-merging scripts/i18n.py" — the head
    of git's output — and never said which file actually conflicted."""
    out = ("Auto-merging scripts/i18n.py\n"
           "Auto-merging scripts/ui.py\n"
           "CONFLICT (content): Merge conflict in scripts/test_ui.py\n"
           "Automatic merge failed; fix conflicts and then commit the result.")
    assert srv._conflict_msg(out) == "merge conflict, aborted: scripts/test_ui.py"
    assert "no pude" in srv._conflict_msg("no pude")   # no CONFLICT line: the raw output


def test_a_pulled_settings_json_still_parses():
    """The bug: export tokenized the JSON-escaped `C:\\\\Users\\\\Alice`, apply
    pasted back the raw `C:\\Users\\Bob`, and `\\U` is not a legal JSON escape —
    so every pull left ~/.claude/settings.json unparseable and Claude Code fell
    back to its defaults without saying a word."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as repo, \
         tempfile.TemporaryDirectory() as b:
        src, cfg, dst = Path(a), Path(repo) / "config", Path(b)
        home_a, home_b = "C:\\Users\\Alice", "C:\\Users\\Bob"
        ps1 = home_a + "\\.claude\\hooks\\statusline.ps1"
        (src / "settings.json").write_text(
            json.dumps({"statusLine": {"command": f'powershell -File "{ps1}"'}}),
            encoding="utf-8")
        export_config(["settings"], claude_dir=src, repo_config=cfg, home=home_a)
        assert "{{HOME}}" in (cfg / "settings" / "settings.json").read_text(encoding="utf-8")

        apply_config(["settings"], claude_dir=dst, repo_config=cfg, home=home_b)
        out = (dst / "settings.json").read_text(encoding="utf-8")
        assert json.loads(out)["statusLine"]["command"] == \
            f'powershell -File "{home_b}\\.claude\\hooks\\statusline.ps1"', out

        # and a file that writes the path raw keeps getting it raw
        (src / "CLAUDE.md").write_text(f"run {ps1} nightly\n", encoding="utf-8")
        export_config(["claude-md"], claude_dir=src, repo_config=cfg, home=home_a)
        apply_config(["claude-md"], claude_dir=dst, repo_config=cfg, home=home_b)
        md = (dst / "CLAUDE.md").read_text(encoding="utf-8")
        assert md == f"run {home_b}\\.claude\\hooks\\statusline.ps1 nightly\n", md


def test_config_sync_roundtrip():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as repo, \
         tempfile.TemporaryDirectory() as b:
        src = Path(a)
        home_a = "C:\\Users\\Alice"
        (src / "CLAUDE.md").write_text(f"# rules\npath: {home_a}\\.claude\\skills\n",
                                       encoding="utf-8")
        (src / "settings.json").write_text('{"model": "opus"}', encoding="utf-8")
        (src / "settings.local.json").write_text('{"machine": "only"}', encoding="utf-8")
        (src / ".credentials.json").write_text('{"secret": "x"}', encoding="utf-8")
        (src / "skills" / "foo").mkdir(parents=True)
        (src / "skills" / "foo" / "SKILL.md").write_text("body", encoding="utf-8")

        cfg = Path(repo) / "config"
        n = export_config(["claude-md", "settings", "skills"],
                          claude_dir=src, repo_config=cfg, home=home_a)
        assert n == 3, n
        exported = {str(p.relative_to(cfg)).replace("\\", "/") for p in cfg.rglob("*") if p.is_file()}
        assert exported == {"claude-md/CLAUDE.md", "settings/settings.json",
                            "skills/skills/foo/SKILL.md"}, exported
        text = (cfg / "claude-md" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "{{HOME}}" in text and "Alice" not in text, text  # home tokenized

        # apply onto machine B with a different home; pre-existing file gets backed up
        dst = Path(b)
        (dst / "CLAUDE.md").write_text("old content", encoding="utf-8")
        home_b = "C:\\Users\\Bob"
        applied = apply_config(["claude-md", "settings", "skills"],
                               claude_dir=dst, repo_config=cfg, home=home_b)
        assert applied == 3, applied
        out = (dst / "CLAUDE.md").read_text(encoding="utf-8")
        assert "C:\\Users\\Bob\\.claude" in out and "{{HOME}}" not in out, out
        assert (dst / "skills" / "foo" / "SKILL.md").read_text(encoding="utf-8") == "body"
        backups = list((dst / ".sto-backup").rglob("CLAUDE.md"))
        assert backups and backups[0].read_text(encoding="utf-8") == "old content", backups

        # status reflects both sides; secrets never exported
        st = {m["id"]: m for m in config_status(claude_dir=src, repo_config=cfg)}
        assert st["claude-md"]["localFiles"] == 1 and st["claude-md"]["repoFiles"] == 1, st
        assert st["settings"]["repoFiles"] == 1, st
        assert not any("credentials" in f or "local" in f for f in exported), exported


def test_plugins_sync():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as repo, \
         tempfile.TemporaryDirectory() as b:
        src = Path(a)
        (src / "plugins").mkdir()
        (src / "plugins" / "known_marketplaces.json").write_text(json.dumps({
            "official": {"source": {"source": "github", "repo": "anthropics/claude-plugins-official"}},
            "local-dir": {"source": {"source": "directory", "path": "/x"}},  # not portable → skipped
        }), encoding="utf-8")
        (src / "plugins" / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {"superpowers@official": [{"installPath": "C:\\x"}],
                        "ponytail@official": [{"installPath": "C:\\y"}]},
        }), encoding="utf-8")

        cfg = Path(repo) / "config"
        assert export_plugins(claude_dir=src, repo_config=cfg) == 1
        manifest = json.loads((cfg / "plugins" / "plugins.json").read_text(encoding="utf-8"))
        assert manifest["marketplaces"] == {"official": "anthropics/claude-plugins-official"}, manifest
        assert manifest["plugins"] == ["ponytail@official", "superpowers@official"], manifest
        assert "installPath" not in (cfg / "plugins" / "plugins.json").read_text(encoding="utf-8")

        # machine B: one plugin already there → only the missing one installs
        dst = Path(b)
        (dst / "plugins").mkdir()
        (dst / "plugins" / "installed_plugins.json").write_text(json.dumps({
            "version": 2, "plugins": {"ponytail@official": [{}]},
        }), encoding="utf-8")
        mk, pl = plugins_to_apply(claude_dir=dst, repo_config=cfg)
        assert mk == {"official": "anthropics/claude-plugins-official"}, mk
        assert pl == ["superpowers@official"], pl

        calls = []
        n = apply_plugins(claude_dir=dst, repo_config=cfg,
                          runner=lambda *args: calls.append(args) or True)
        assert n == 1, n
        assert calls == [("marketplace", "add", "anthropics/claude-plugins-official"),
                         ("install", "superpowers@official")], calls

        # empty local plugins → nothing exported; empty repo → nothing to apply
        assert export_plugins(claude_dir=Path(b) / "nope",
                              repo_config=Path(repo) / "cfg2") == 0
        assert plugins_to_apply(claude_dir=dst, repo_config=Path(repo) / "cfg2") == ({}, [])

        # config_status reports plugin counts
        st = {m["id"]: m for m in config_status(claude_dir=src, repo_config=cfg)}
        assert st["plugins"]["localFiles"] == 2 and st["plugins"]["repoFiles"] == 2, st


def test_machines():
    import platform
    with tempfile.TemporaryDirectory() as k:
        other = Path(k) / "OtherPC"
        other.mkdir()
        (other / "machine.json").write_text(json.dumps({"name": "OtherPC", "type": "laptop"}),
                                            encoding="utf-8")
        (Path(k) / "NoMeta").mkdir()
        m = list_machines(knowledge_dir=Path(k))
        me = platform.node() or "local"
        assert m[me]["local"] is True and m[me]["type"] in ("laptop", "desktop"), m
        assert m["OtherPC"] == {"type": "laptop", "local": False}, m
        assert m["NoMeta"] == {"type": "unknown", "local": False}, m
        assert machine_type() in ("laptop", "desktop")


def test_export_sessions():
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as k:
        proj = Path(d) / "projX"
        proj.mkdir()
        p = _settled(_write_session(proj))  # contains an sk- secret line
        empty = proj / "empty.jsonl"
        empty.write_text(json.dumps(
            {"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "tool_use", "name": "Read"}]}}), encoding="utf-8")
        _settled(empty)
        dest = Path(k) / "MyPC"

        n = export_sessions(projects_dir=Path(d), dest=dest)
        assert n == 1, n  # empty (no prompts) not exported
        mj = json.loads((dest / "machine.json").read_text(encoding="utf-8"))
        assert mj["name"] == "MyPC" and mj["type"] in ("laptop", "desktop"), mj
        out = dest / "projX" / p.name
        assert out.exists(), list(dest.rglob("*"))
        text = out.read_text(encoding="utf-8")
        assert "sk-abcdefghij" not in text, "secret must be redacted"
        assert "First real prompt" in text, "content preserved"
        # trimmed export still renders in the chat viewer
        t = session_timeline(out)["timeline"]
        roles = [it["role"] for it in t]
        assert roles == ["user", "tool", "assistant", "tool", "error", "user"], roles
        assert t[1]["detail"] == "x.py", t[1]
        # second run: nothing new
        assert export_sessions(projects_dir=Path(d), dest=dest) == 0
        # being written right now → not exported yet, however new it is. The bug:
        # the session doing the push grew again a second later, so every push
        # left one file for the other machine to pull, forever.
        os.utime(p, None)
        assert export_sessions(projects_dir=Path(d), dest=dest) == 0
        # once it settles it travels
        _settled(p, srv.EXPORT_SETTLE + 1)
        assert export_sessions(projects_dir=Path(d), dest=dest) == 1


def test_project_identity_from_cwd():
    """Session with a cwd → project = cwd basename, and export groups by it,
    so the same project synced from any machine/path lands in one dir."""
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as k:
        proj = Path(d) / "C--repos-cool-repo"
        proj.mkdir()
        rec = dict(SAMPLE[0])
        rec["cwd"] = str(Path(d) / "not-a-git-repo" / "cool-repo")  # no .git → basename
        p = proj / "44444444-2222-3333-4444-555555555555.jsonl"
        p.write_text(json.dumps(rec), encoding="utf-8")
        _settled(p)

        assert session_meta(p)["project"] == "cool-repo", session_meta(p)
        dest = Path(k) / "MyPC"
        assert export_sessions(projects_dir=Path(d), dest=dest) == 1
        assert (dest / "cool-repo" / p.name).exists(), list(dest.rglob("*"))


def test_slug_project_writes_marker_when_resolved_from_jsonl():
    """The first successful resolution from a .jsonl is persisted to
    <slug_dir>/.sto-project, to survive the pruning of old sessions."""
    with tempfile.TemporaryDirectory() as d:
        slug_dir = Path(d) / "S1--marcado"
        slug_dir.mkdir()
        rec = dict(SAMPLE[0])
        rec["cwd"] = str(Path(d) / "not-a-git-repo" / "proyecto-x")
        (slug_dir / "s.jsonl").write_text(json.dumps(rec), encoding="utf-8")

        assert _slug_project(slug_dir) == "proyecto-x"
        marker = slug_dir / ".sto-project"
        assert marker.exists(), "the marker is written"
        assert marker.read_text(encoding="utf-8").strip() == "proyecto-x"


def test_slug_project_existing_marker_wins_over_scan():
    """An existing marker beats the scan, even when the .jsonl says otherwise:
    the marker is authoritative once resolved."""
    with tempfile.TemporaryDirectory() as d:
        slug_dir = Path(d) / "S2--con-marcador"
        slug_dir.mkdir()
        (slug_dir / ".sto-project").write_text("proyecto-fijado\n", encoding="utf-8")
        rec = dict(SAMPLE[0])
        rec["cwd"] = str(Path(d) / "not-a-git-repo" / "otro-nombre")
        (slug_dir / "s.jsonl").write_text(json.dumps(rec), encoding="utf-8")

        assert _slug_project(slug_dir) == "proyecto-fijado"


def test_slug_project_falls_back_to_raw_slug_without_marker_or_cwd():
    """With no marker and no .jsonl at all (dormant project, sessions pruned
    pero memory/ sobrevive): cae al slug crudo, y NO escribe marcador —
    nothing is known yet, so no dubious fallback should be pinned."""
    with tempfile.TemporaryDirectory() as d:
        slug_dir = Path(d) / "C--repos-dormido"
        (slug_dir / "memory").mkdir(parents=True)  # memory/ sobrevive, jsonl no

        assert _slug_project(slug_dir) == "C--repos-dormido"
        assert not (slug_dir / ".sto-project").exists(), "no se fija un fallback dudoso"


def _mkproj(root, slug, cwd, memories):
    """Create ~/.claude/projects/<slug>/ with a session carrying cwd and memories.

    memories: dict file_name -> the full text of the .md
    """
    d = Path(root) / slug
    (d / "memory").mkdir(parents=True)
    (d / "s.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": cwd,
         "message": {"role": "user", "content": "hola"}}), encoding="utf-8")
    for name, text in memories.items():
        (d / "memory" / name).write_text(text, encoding="utf-8")
    return d / "memory"


MEM_A = """---
name: regla-a
description: No usar borde vertical dorado
metadata:
  node_type: memory
  type: feedback
---

Cuerpo de la memoria A.
"""

MEM_B = """---
name: regla-b
description: "Estado del proyecto: en curso"
metadata:
  node_type: memory
  type: project
---

Cuerpo de la memoria B.
"""


def test_memory_meta():
    m = _memory_meta(MEM_A)
    assert m["name"] == "regla-a", m
    assert m["description"] == "No usar borde vertical dorado", m
    assert m["type"] == "feedback", m
    q = _memory_meta(MEM_B)
    assert q["description"] == "Estado del proyecto: en curso", q  # quotes stripped
    assert q["type"] == "project", q
    assert _memory_meta("sin frontmatter") == {"name": "", "description": "", "type": ""}


def test_memory_dirs_groups_by_project():
    with tempfile.TemporaryDirectory() as d:
        # two different slugs landing in the same repo -> a single project
        repo = Path(d) / "repo-x"
        (repo / "app").mkdir(parents=True)
        import subprocess as sp
        sp.run(["git", "init", "-q", str(repo)], capture_output=True)
        sp.run(["git", "-C", str(repo), "remote", "add", "origin",
                "https://github.com/u/cool-repo.git"], capture_output=True)

        pd = Path(d) / "projects"
        pd.mkdir()
        _mkproj(pd, "T1--repo-x", str(repo), {"regla-a.md": MEM_A})
        _mkproj(pd, "T1--repo-x-app", str(repo / "app"), {"regla-b.md": MEM_B})
        _mkproj(pd, "T1--suelto", str(Path(d) / "suelto"), {"regla-a.md": MEM_A})

        dirs = _memory_dirs(projects_dir=pd)
        assert set(dirs) == {"cool-repo", "suelto"}, dirs
        assert len(dirs["cool-repo"]) == 2, dirs["cool-repo"]
        assert len(dirs["suelto"]) == 1, dirs["suelto"]


def test_memory_dirs_ignores_projects_without_memory():
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        (pd / "T2--sinmem").mkdir(parents=True)
        (pd / "T2--sinmem" / "s.jsonl").write_text("{}", encoding="utf-8")
        assert _memory_dirs(projects_dir=pd) == {}


def test_export_memory_mirrors_union():
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        _mkproj(pd, "T3--uno", str(Path(d) / "uno"), {"regla-a.md": MEM_A})
        _mkproj(pd, "T3--uno-sub", str(Path(d) / "uno"), {"regla-b.md": MEM_B})
        dest = Path(d) / "knowledge-memory"

        assert export_memory(projects_dir=pd, dest=dest) == 2
        out = dest / "uno" / LOCAL_MACHINE
        assert {f.name for f in out.glob("*.md")} == {"regla-a.md", "regla-b.md"}, list(out.iterdir())
        # idempotente: segunda pasada no reescribe nada
        assert export_memory(projects_dir=pd, dest=dest) == 0


def test_export_memory_skips_index_and_redacts():
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        mem = _mkproj(pd, "T4--dos", str(Path(d) / "dos"), {
            "regla-a.md": MEM_A + "\ntoken sk-abcdefghijklmnopqrstuvwxyz123\n",
            "MEMORY.md": "# Memory Index\n\n- [regla-a](regla-a.md) — x\n"})
        dest = Path(d) / "km"

        export_memory(projects_dir=pd, dest=dest)
        out = dest / "dos" / LOCAL_MACHINE
        assert not (out / "MEMORY.md").exists(), "the index does not travel"
        assert "sk-abcdefghij" not in (out / "regla-a.md").read_text(encoding="utf-8")
        assert mem.exists()  # the source is left alone


def test_export_memory_deletes_stale_only_in_own_machine():
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        _mkproj(pd, "T5--tres", str(Path(d) / "tres"), {"regla-a.md": MEM_A})
        dest = Path(d) / "km"
        mia = dest / "tres" / LOCAL_MACHINE
        ajena = dest / "tres" / "OtraMaquina"
        ajena.mkdir(parents=True)
        (ajena / "regla-vieja.md").write_text(MEM_B, encoding="utf-8")
        mia.mkdir(parents=True)
        (mia / "borrada.md").write_text(MEM_B, encoding="utf-8")

        export_memory(projects_dir=pd, dest=dest)
        assert not (mia / "borrada.md").exists(), "mine that is no longer local gets deleted"
        assert (ajena / "regla-vieja.md").exists(), "another machine's files are untouched"


def test_import_memory_unions_machines_newest_wins():
    """Between copies from remote machines (none is LOCAL_MACHINE) _newest still
    decides by mtime — no local work is at stake there, and the worst that can
    happen is preferring the other remote. Local starts empty (never published
    anything), so everything arriving is "new from another machine"."""
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        mem = _mkproj(pd, "T6--cuatro", str(Path(d) / "cuatro"), {})
        src = Path(d) / "km" / "cuatro"
        for maquina, texto, mtime in (("PC", MEM_A, 1000), ("Note", MEM_A + "\nnueva\n", 2000)):
            (src / maquina).mkdir(parents=True)
            f = src / maquina / "regla-a.md"
            f.write_text(texto, encoding="utf-8")
            os.utime(f, (mtime, mtime))
        (src / "Note" / "solo-note.md").write_text(MEM_B, encoding="utf-8")

        assert import_memory(projects_dir=pd, src=Path(d) / "km") == 2
        assert "nueva" in (mem / "regla-a.md").read_text(encoding="utf-8"), "between remotes, newest mtime wins"
        assert (mem / "solo-note.md").exists(), "what only another machine has still arrives"


def test_import_memory_does_not_clobber_newer_local():
    """Local work this machine never published (there is no LOCAL_MACHINE folder
    in the repo for that project) is not overwritten, whatever the remote's
    mtime says — mtime is no authorship clock across git."""
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        mem = _mkproj(pd, "T7--cinco", str(Path(d) / "cinco"), {"regla-a.md": MEM_A + "\nLOCAL\n"})
        os.utime(mem / "regla-a.md", (1000, 1000))  # deliberately old local mtime
        src = Path(d) / "km" / "cinco" / "PC"  # PC != LOCAL_MACHINE: I never published this
        src.mkdir(parents=True)
        f = src / "regla-a.md"
        f.write_text(MEM_A + "\nVIEJA\n", encoding="utf-8")
        os.utime(f, (9999999, 9999999))  # mtime "fresco de checkout", igual no gana

        assert import_memory(projects_dir=pd, src=Path(d) / "km") == 0
        assert "LOCAL" in (mem / "regla-a.md").read_text(encoding="utf-8")


def test_import_memory_fresh_checkout_mtime_does_not_clobber_diverged_local():
    """The case that broke the old rule: git does not preserve mtimes, so a
    checkout can leave the remote with a newer mtime than a local change from an
    hour ago. The comparison base is what THIS machine published last (mine),
    not the filesystem clock."""
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        mem = _mkproj(pd, "T14--doce", str(Path(d) / "doce"),
                       {"regla-a.md": MEM_A + "\nCLAUDE-ACABA-DE-ESCRIBIR-ESTO\n"})
        os.utime(mem / "regla-a.md", (1000, 1000))  # mtime local viejo
        km = Path(d) / "km" / "doce"
        # mine: the last thing this machine published, before the local change above
        mine = km / LOCAL_MACHINE
        mine.mkdir(parents=True)
        (mine / "regla-a.md").write_text(MEM_A, encoding="utf-8")
        os.utime(mine / "regla-a.md", (500, 500))
        # remote: old content, but with a freshly stamped "checkout" mtime
        otra = km / "OtraMaquina"
        otra.mkdir(parents=True)
        f = otra / "regla-a.md"
        f.write_text(MEM_A + "\nVIEJA-REMOTA\n", encoding="utf-8")
        os.utime(f, (9999999, 9999999))

        assert import_memory(projects_dir=pd, src=Path(d) / "km") == 0
        assert "CLAUDE-ACABA-DE-ESCRIBIR-ESTO" in (mem / "regla-a.md").read_text(encoding="utf-8")


def test_import_memory_local_delete_is_not_resurrected():
    """A deleted local memory cannot be resurrected: if mine (what this machine
    published) still has it but the local copy does not, the delete simply has
    not been pushed yet — it must not be recreated."""
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        mem = _mkproj(pd, "T15--trece", str(Path(d) / "trece"), {})  # borrada localmente
        km = Path(d) / "km" / "trece"
        mine = km / LOCAL_MACHINE
        mine.mkdir(parents=True)
        (mine / "regla-a.md").write_text(MEM_A, encoding="utf-8")

        assert import_memory(projects_dir=pd, src=Path(d) / "km") == 0
        assert not (mem / "regla-a.md").exists(), "a local delete is not resurrected"


def test_import_memory_identical_local_is_not_rewritten():
    """A local file byte-identical (after redaction) to the remote winner is not
    rewritten, to avoid churn and a false counter after every pull."""
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        mem = _mkproj(pd, "T16--catorce", str(Path(d) / "catorce"), {"regla-a.md": MEM_A})
        km = Path(d) / "km"
        otra = km / "catorce" / "OtraMaquina"
        otra.mkdir(parents=True)
        (otra / "regla-a.md").write_text(MEM_A, encoding="utf-8")  # mismo contenido

        assert import_memory(projects_dir=pd, src=km) == 0
        assert (mem / "regla-a.md").read_text(encoding="utf-8") == MEM_A


def test_import_memory_new_from_other_machine_arrives_when_never_published():
    """I never published anything of this project (no LOCAL_MACHINE folder in the
    repo) and do not have it locally: what another machine brings must arrive."""
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        mem = _mkproj(pd, "T17--quince", str(Path(d) / "quince"), {})
        km = Path(d) / "km"
        otra = km / "quince" / "OtraMaquina"
        otra.mkdir(parents=True)
        (otra / "regla-nueva.md").write_text(MEM_B, encoding="utf-8")

        assert import_memory(projects_dir=pd, src=km) == 1
        assert (mem / "regla-nueva.md").read_text(encoding="utf-8") == MEM_B


def test_import_memory_writes_every_local_slug():
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        a = _mkproj(pd, "T8--seis", str(Path(d) / "seis"), {})
        b = _mkproj(pd, "T8--seis-sub", str(Path(d) / "seis"), {})
        src = Path(d) / "km" / "seis" / "PC"
        src.mkdir(parents=True)
        (src / "regla-a.md").write_text(MEM_A, encoding="utf-8")

        assert import_memory(projects_dir=pd, src=Path(d) / "km") == 2
        assert (a / "regla-a.md").exists() and (b / "regla-a.md").exists()


def test_import_memory_skips_project_without_local_slug():
    with tempfile.TemporaryDirectory() as d:
        pd = Path(d) / "projects"
        pd.mkdir()
        src = Path(d) / "km" / "proyecto-jamas-abierto-aca" / "PC"
        src.mkdir(parents=True)
        (src / "regla-a.md").write_text(MEM_A, encoding="utf-8")

        assert import_memory(projects_dir=pd, src=Path(d) / "km") == 0  # no explota


def test_memory_roundtrip_to_second_machine():
    """Machine A exports to the repo; machine B (its own LOCAL_MACHINE, which
    never published anything of this project) imports and ends with the same set.

    LOCAL_MACHINE is a real process constant (`platform.node()`), so simulating
    a second machine properly means patching the module global during the
    import — otherwise "mine" would resolve to the same folder the export above
    just wrote and the import would skip everything as a "deliberate local
    delete"."""
    import sessions_server as ss
    with tempfile.TemporaryDirectory() as d:
        km = Path(d) / "km"
        pa = Path(d) / "projects-a"
        pa.mkdir()
        _mkproj(pa, "T9--siete", str(Path(d) / "siete"),
                {"regla-a.md": MEM_A, "regla-b.md": MEM_B})
        assert export_memory(projects_dir=pa, dest=km) == 2

        pb = Path(d) / "projects-b"
        pb.mkdir()
        # same project, another slug (another machine would mount another path)
        mb = _mkproj(pb, "T9--siete-en-otra-maquina", str(Path(d) / "siete"), {})
        original_machine = ss.LOCAL_MACHINE
        ss.LOCAL_MACHINE = "T9-MaquinaB-nunca-publico"
        try:
            assert import_memory(projects_dir=pb, src=km) == 2
        finally:
            ss.LOCAL_MACHINE = original_machine
        assert {f.name for f in mb.glob("*.md")} == {"regla-a.md", "regla-b.md"}, list(mb.iterdir())


def test_rebuild_index_keeps_existing_adds_new_drops_gone():
    with tempfile.TemporaryDirectory() as d:
        mem = Path(d) / "memory"
        mem.mkdir()
        (mem / "regla-a.md").write_text(MEM_A, encoding="utf-8")
        (mem / "regla-b.md").write_text(MEM_B, encoding="utf-8")
        (mem / "MEMORY.md").write_text(
            "# Memory Index\n\n"
            "- [Hand-written title](regla-a.md) — original wording from Claude\n"
            "- [Gone](se-fue.md) — not there any more\n", encoding="utf-8")

        rebuild_index(mem)
        out = (mem / "MEMORY.md").read_text(encoding="utf-8")
        assert "# Memory Index" in out, out
        assert "Hand-written title" in out, "what Claude wrote is not overwritten"
        assert "original wording" in out, out
        assert "se-fue.md" not in out, "the line of a deleted file goes away"
        assert "regla-b.md" in out, "the new file enters the index"
        assert "Estado del proyecto: en curso" in out, "it uses the frontmatter description"


def test_rebuild_index_creates_when_missing():
    with tempfile.TemporaryDirectory() as d:
        mem = Path(d) / "memory"
        mem.mkdir()
        (mem / "regla-a.md").write_text(MEM_A, encoding="utf-8")

        rebuild_index(mem)
        out = (mem / "MEMORY.md").read_text(encoding="utf-8")
        assert out.startswith("# Memory Index"), out
        assert "- [regla-a](regla-a.md) — No usar borde vertical dorado" in out, out


def test_rebuild_index_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        mem = Path(d) / "memory"
        mem.mkdir()
        (mem / "regla-a.md").write_text(MEM_A, encoding="utf-8")
        rebuild_index(mem)
        once = (mem / "MEMORY.md").read_text(encoding="utf-8")
        rebuild_index(mem)
        assert (mem / "MEMORY.md").read_text(encoding="utf-8") == once


def test_rebuild_index_keeps_lf_endings():
    """Without newline='\\n', Windows rewrites the bytes of every MEMORY.md on
    every pull by translating to CRLF, even when the content did not change."""
    with tempfile.TemporaryDirectory() as d:
        mem = Path(d) / "memory"
        mem.mkdir()
        (mem / "regla-a.md").write_text(MEM_A, encoding="utf-8")
        (mem / "MEMORY.md").write_bytes(
            b"# Memory Index\n\n- [regla-a](regla-a.md) - x\n")
        before = (mem / "MEMORY.md").read_bytes()

        rebuild_index(mem)
        after = (mem / "MEMORY.md").read_bytes()
        assert b"\r\n" not in after, after
        assert after == before, (before, after)


def test_rebuild_index_skips_empty_memory_dir():
    with tempfile.TemporaryDirectory() as d:
        mem = Path(d) / "memory"
        mem.mkdir()
        rebuild_index(mem)
        assert not (mem / "MEMORY.md").exists(), "do not seed an index in an empty folder"


def test_list_memory():
    with tempfile.TemporaryDirectory() as d:
        km = Path(d) / "km"
        (km / "proyA" / "PC").mkdir(parents=True)
        (km / "proyA" / "Note").mkdir(parents=True)
        (km / "proyA" / "PC" / "regla-a.md").write_text(MEM_A, encoding="utf-8")
        (km / "proyA" / "Note" / "regla-b.md").write_text(MEM_B, encoding="utf-8")
        (km / "proyVacio").mkdir(parents=True)

        data = list_memory(src=km)
        assert [p["project"] for p in data] == ["proyA"], data  # the empty one is absent
        p = data[0]
        assert p["count"] == 2, p
        assert p["machines"] == ["Note", "PC"], p
        slugs = {m["slug"]: m for m in p["memories"]}
        assert slugs["regla-a"]["type"] == "feedback", slugs
        assert slugs["regla-a"]["machine"] == "PC", slugs
        assert slugs["regla-b"]["description"] == "Estado del proyecto: en curso", slugs
        assert isinstance(slugs["regla-b"]["mtime"], float), slugs


def test_memory_graph_links_projects_and_wikilinks():
    with tempfile.TemporaryDirectory() as d:
        km = Path(d) / "km"
        (km / "C--x-Projects-uno" / "PC").mkdir(parents=True)
        (km / "dos" / "Note").mkdir(parents=True)
        (km / "C--x-Projects-uno" / "PC" / "regla-a.md").write_text(
            MEM_A + "\nver [[regla-b]] y [[no-existe]]\n", encoding="utf-8")
        (km / "C--x-Projects-uno" / "PC" / "regla-b.md").write_text(MEM_B, encoding="utf-8")
        (km / "dos" / "Note" / "otra.md").write_text(MEM_A, encoding="utf-8")

        g = memory_graph(src=km)
        assert g["counts"] == {"memories": 3, "projects": 2, "links": 1}, g["counts"]
        # el label del proyecto es la cola del path aplastado, no el path entero
        labels = {n["label"] for n in g["nodes"] if n["kind"] == "project"}
        assert labels == {"uno", "dos"}, labels
        assert len([l for l in g["links"] if l["kind"] == "in"]) == 3   # cada una a su proyecto
        # el [[regla-b]] resuelve adentro del proyecto; el [[no-existe]] no pinta arista
        wiki = [l for l in g["links"] if l["kind"] == "link"]
        assert wiki == [{"source": "C--x-Projects-uno/regla-a",
                         "target": "C--x-Projects-uno/regla-b", "kind": "link"}], wiki


def test_list_memory_missing_root():
    with tempfile.TemporaryDirectory() as d:
        assert list_memory(src=Path(d) / "no-existe") == []


def test_sync_stage_exports_and_returns_staged_paths():
    calls = []
    real = (srv._git, srv.export_sessions, srv.export_config, srv.export_memory)
    try:
        srv.export_sessions = lambda *a, **k: calls.append("sessions") or 12
        srv.export_config = lambda *a, **k: calls.append("config") or 1
        srv.export_memory = lambda *a, **k: calls.append("memory") or 5
        srv._git = lambda *a, **k: (
            (0, "knowledge/config/skills/skills/tackler/SKILL.md\nvault/wiki/x.md")
            if a[0] == "diff" else (0, ""))
        out = srv.sync_stage()
        assert calls == ["sessions", "config", "memory"]
        assert out["paths"] == ["knowledge/config/skills/skills/tackler/SKILL.md",
                                "vault/wiki/x.md"]
        assert (out["sessions"], out["config"], out["memory"]) == (12, 1, 5)
    finally:
        srv._git, srv.export_sessions, srv.export_config, srv.export_memory = real


def test_sync_stage_paths_stay_scoped_to_knowledge_and_vault():
    """When other work is staged (say `git add scripts/…` mid-task), sync_stage()
    must not list it: the confirmation manifest has to describe exactly what
    sync_push() is going to commit."""
    real = (srv._git, srv.export_sessions, srv.export_config, srv.export_memory)
    try:
        srv.export_sessions = lambda *a, **k: 0
        srv.export_config = lambda *a, **k: 0
        srv.export_memory = lambda *a, **k: 0
        todo_lo_stageado = ["knowledge/sessions/PC/a.jsonl", "scripts/cli.py"]

        def fake_git(*a, **k):
            if a[0] == "diff":
                if "--" in a and "knowledge" in a and "vault" in a:
                    return (0, "\n".join(p for p in todo_lo_stageado
                                         if p.startswith(("knowledge/", "vault/"))))
                return (0, "\n".join(todo_lo_stageado))  # no pathspec: the whole index
            return (0, "")
        srv._git = fake_git
        out = srv.sync_stage()
        assert out["paths"] == ["knowledge/sessions/PC/a.jsonl"]
        assert "scripts/cli.py" not in out["paths"]
    finally:
        srv._git, srv.export_sessions, srv.export_config, srv.export_memory = real


def test_sync_incoming_lists_paths_and_reports_fetch_error():
    real_git, real_status = srv._git, srv.sync_status
    try:
        srv.sync_status = lambda fetch=True: {"remote": "git@x", "branch": "main",
                                              "ahead": 0, "behind": 2, "dirty": False,
                                              "machine": "PC", "fetchError": None}
        srv._git = lambda *a, **k: (0, "knowledge/memory/proj/PC/nota.md")
        out = srv.sync_incoming()
        assert out["paths"] == ["knowledge/memory/proj/PC/nota.md"]
        assert out["error"] is None
        # a pull is not only what git carries: these two say what would land on
        # THIS machine even with the branch already up to date
        assert "activate" in out and "memories" in out

        srv.sync_status = lambda fetch=True: {"remote": "git@x", "branch": "main",
                                              "ahead": 0, "behind": 0, "dirty": False,
                                              "machine": "PC", "fetchError": "no network"}
        out = srv.sync_incoming()
        assert out["paths"] == [] and "no network" in out["error"]
    finally:
        srv._git, srv.sync_status = real_git, real_status


def test_sync_incoming_asks_git_for_the_remote_side_only():
    """With two dots (`HEAD..origin/x`) git diffs both whole trees, so while
    ahead it returned your own files as if they were coming down to you. Three
    dots start from the merge base and bring only what the remote has."""
    vistos, real_git, real_status = [], srv._git, srv.sync_status
    try:
        srv.sync_status = lambda fetch=True: {"remote": "git@x", "branch": "main",
                                              "ahead": 19, "behind": 0, "dirty": False,
                                              "machine": "PC", "fetchError": None}

        def git(*args, **kw):
            vistos.append(args)
            return 0, ""
        srv._git = git
        srv.sync_incoming()
        assert any("HEAD...origin/main" in a for a in vistos)
        assert not any("HEAD..origin/main" in a for a in vistos)
    finally:
        srv._git, srv.sync_status = real_git, real_status



def test_the_fetch_clock_survives_a_git_gc():
    """`git gc` runs on its own and packs the loose refs away. Reading only
    `.git/refs/remotes/...` then answered "never fetched" forever, and the
    30 min TTL became a `git fetch` on every home repaint."""
    real_git, real_root = srv._git, srv.REPO_ROOT
    try:
        with tempfile.TemporaryDirectory() as d:
            srv.REPO_ROOT = Path(d)
            (Path(d) / ".git").mkdir()
            srv._git = lambda *a: (0, "refs/remotes/upstream/main\n")
            # packed: no loose file anywhere
            assert srv._stale_fetch_ref("refs/remotes/upstream") is True   # nor packed-refs
            packed = Path(d) / ".git" / "packed-refs"
            packed.write_text("# pack-refs with: peeled\n", encoding="utf-8")
            assert srv._stale_fetch_ref("refs/remotes/upstream", ttl=600) is False
            os.utime(packed, (1000, 1000))
            assert srv._stale_fetch_ref("refs/remotes/upstream", ttl=600) is True
            # loose wins when it is there
            loose = Path(d) / ".git" / "refs" / "remotes" / "upstream"
            loose.mkdir(parents=True)
            (loose / "main").write_text("deadbeef", encoding="utf-8")
            assert srv._stale_fetch_ref("refs/remotes/upstream", ttl=600) is False
    finally:
        srv._git, srv.REPO_ROOT = real_git, real_root


def test_an_explicit_update_check_fetches_even_with_a_fresh_ref():
    """The bug: `u` five minutes after a release answered "already on the latest
    version". `update_status` skips the fetch while the upstream ref is younger
    than 30 min, and nothing could make it look — so a repo published minutes
    ago was invisible until the TTL ran out."""
    real_git, real_stale = srv._git, srv._stale_fetch_ref
    llamadas = []
    try:
        srv._stale_fetch_ref = lambda *a, **k: False      # ref recien fetcheado
        def fake(*args):
            llamadas.append(args)
            if args[0] == "remote":
                return 0, "https://x/y.git"
            if args[0] == "rev-list":
                return 0, "0"
            return 0, ""
        srv._git = fake
        srv.update_status()
        assert not any(a[0] == "fetch" for a in llamadas), llamadas
        llamadas.clear()
        srv.update_status(force=True)
        assert any(a[0] == "fetch" for a in llamadas), llamadas
    finally:
        srv._git, srv._stale_fetch_ref = real_git, real_stale


def test_update_apply_refuses_an_unrelated_repo_instead_of_forcing_a_merge():
    """A repo copied instead of forked shares no commit with upstream. Merging
    that with --allow-unrelated-histories behind the user's back is how you
    lose a working tree; `update_link` is the explicit, one-time door."""
    reales = (srv._git, srv.update_status, srv.sync_status)
    try:
        srv.update_status = lambda fetch=True, force=False: {"available": 8, "url": "u",
                                                "linked": False, "log": [], "error": None}
        srv._git = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no git"))
        out = srv.update_apply()
        assert "error" in out and "--link" in out["error"]
    finally:
        srv._git, srv.update_status, srv.sync_status = reales


def test_update_apply_never_merges_over_uncommitted_work():
    reales = (srv._git, srv.update_status, srv.sync_status)
    try:
        srv.update_status = lambda fetch=True, force=False: {"available": 2, "url": "u",
                                                "linked": True, "log": [], "error": None}
        srv.sync_status = lambda fetch=True: {"remote": "x", "branch": "main", "ahead": 0,
                                              "behind": 0, "dirty": True, "machine": "PC",
                                              "fetchError": None}
        srv._git = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no git"))
        assert "uncommitted" in srv.update_apply()["error"]
    finally:
        srv._git, srv.update_status, srv.sync_status = reales


def test_update_apply_merges_upstream_and_says_how_much():
    vistos, reales = [], (srv._git, srv.update_status, srv.sync_status)
    try:
        srv.update_status = lambda fetch=True, force=False: {"available": 3, "url": "u",
                                                "linked": True, "log": [], "error": None}
        srv.sync_status = lambda fetch=True: {"remote": "x", "branch": "main", "ahead": 0,
                                              "behind": 0, "dirty": False, "machine": "PC",
                                              "fetchError": None}

        def git(*a, **k):
            vistos.append(a)
            if a[0] == "rev-parse":
                return 0, "upstream/main"
            return 0, ""
        srv._git = git
        out = srv.update_apply()
        assert out["ok"] and "3 commit" in out["message"]
        merges = [a for a in vistos if a[0] == "merge"]
        assert len(merges) == 1 and "--allow-unrelated-histories" not in merges[0]
    finally:
        srv._git, srv.update_status, srv.sync_status = reales


def test_sync_pull_applies_config_even_with_the_branch_up_to_date():
    """The bug: `behind == 0` skipped apply_config, so a skill sitting in the
    repo stayed uninstalled on this machine and PULL had nothing to do."""
    aplicados, reales = [], (srv._git, srv.sync_status, srv.apply_config,
                             srv.import_memory, srv.get_sync_prefs)
    try:
        srv.sync_status = lambda fetch=True: {"remote": "x", "branch": "main", "ahead": 0,
                                              "behind": 0, "dirty": False, "machine": "PC",
                                              "fetchError": None}
        srv._git = lambda *a, **k: (0, "")
        srv.get_sync_prefs = lambda: ["skills"]
        srv.apply_config = lambda mods, **k: aplicados.append(mods) or 2
        srv.import_memory = lambda *a, **k: 0
        out = srv.sync_pull()
        assert aplicados == [["skills"]]
        assert out["ok"] and "2 config file" in out["message"]
    finally:
        (srv._git, srv.sync_status, srv.apply_config,
         srv.import_memory, srv.get_sync_prefs) = reales




def test_set_badge_chains_the_previous_status_line_and_gives_it_back():
    """settings.json takes one statusLine. Installing ours by overwriting is
    how a user loses the badge they already had, so the old command is kept
    aside and restored when the badge is turned off."""
    import tempfile
    reales = (srv.SETTINGS, srv.UI_PREFS)
    try:
        d = Path(tempfile.mkdtemp())
        srv.SETTINGS, srv.UI_PREFS = d / "settings.json", d / "sto-ui.json"
        otro = "powershell -File otro.ps1"
        srv.SETTINGS.write_text(json.dumps({"model": "x",
                                            "statusLine": {"type": "command",
                                                           "command": otro}}),
                                encoding="utf-8")
        assert srv.badge_status() == {"on": False, "other": otro}

        assert srv.set_badge(True)["ok"]
        st = srv.badge_status()
        assert st["on"] and st["other"] == otro
        conf = json.loads(srv.SETTINGS.read_text(encoding="utf-8"))
        assert conf["statusLine"]["command"] == srv.statusline_cmd()
        assert conf["model"] == "x"            # the rest of settings is untouched

        assert srv.set_badge(False)["ok"]
        conf = json.loads(srv.SETTINGS.read_text(encoding="utf-8"))
        assert conf["statusLine"]["command"] == otro
        assert srv.badge_status()["on"] is False
    finally:
        srv.SETTINGS, srv.UI_PREFS = reales


def test_set_badge_leaves_no_status_line_behind_when_there_was_none():
    import tempfile
    reales = (srv.SETTINGS, srv.UI_PREFS)
    try:
        d = Path(tempfile.mkdtemp())
        srv.SETTINGS, srv.UI_PREFS = d / "settings.json", d / "sto-ui.json"
        srv.SETTINGS.write_text("{}", encoding="utf-8")
        srv.set_badge(True)
        assert srv.badge_status()["on"]
        srv.set_badge(False)
        assert "statusLine" not in json.loads(srv.SETTINGS.read_text(encoding="utf-8"))
    finally:
        srv.SETTINGS, srv.UI_PREFS = reales




def test_decode_slug_walks_the_disk_back_to_the_real_path():
    """The slug collapses separators, spaces (and maybe dots) into `-`, so it
    cannot be parsed — but at each level the real children are the only
    candidates, and encoding a real name forward is exact."""
    import tempfile
    raiz = Path(tempfile.mkdtemp()).resolve()
    hondo = raiz / "OneDrive - UTN FRLP" / "mi app v1.2" / "src"
    hondo.mkdir(parents=True)
    (raiz / "OneDrive").mkdir()          # the prefix trap: shorter sibling
    for rx in (srv._SLUG_SEP, srv._SLUG_SEP_DOT):
        assert srv._decode_slug(rx.sub("-", str(hondo))) == hondo
    # a path that is not on this disk resolves to nothing, and says so
    assert srv._decode_slug("Z--no-existe-nada-de-esto") is None
    assert srv._decode_slug("no-empieza-como-un-path") is None


def test_slug_project_survives_claude_code_pruning_the_transcripts():
    """The bug: Claude Code drops .jsonl at 30 days but keeps memory/, so any
    project untouched for a month fell back to its raw slug — and the slug
    carries the machine's path, so the same project on two machines stopped
    being one project and their memories never merged."""
    import tempfile
    disco = Path(tempfile.mkdtemp()).resolve()
    proyecto = disco / "Web App Projects" / "mi-repo"
    proyecto.mkdir(parents=True)
    slug_dir = Path(tempfile.mkdtemp()) / srv._SLUG_SEP.sub("-", str(proyecto))
    (slug_dir / "memory").mkdir(parents=True)      # memories, no transcripts

    assert not list(slug_dir.glob("*.jsonl"))
    real = srv._PROJECT_NAMES
    try:
        srv._PROJECT_NAMES = {}
        assert srv._slug_project(slug_dir) == "mi-repo"     # not the raw slug
        assert (slug_dir / ".sto-project").read_text(encoding="utf-8") == "mi-repo"
        # and the walk happens once: the marker answers from here on
        proyecto.rename(proyecto.parent / "movido")
        srv._PROJECT_NAMES = {}
        assert srv._slug_project(slug_dir) == "mi-repo"
    finally:
        srv._PROJECT_NAMES = real


def test_repair_memory_refiles_slug_folders_and_never_clobbers():
    import tempfile
    disco = Path(tempfile.mkdtemp()).resolve()
    proyecto = disco / "mi-repo"
    proyecto.mkdir(parents=True)
    slug = srv._SLUG_SEP.sub("-", str(proyecto))

    root = Path(tempfile.mkdtemp()) / "memory"
    (root / slug / "PC").mkdir(parents=True)
    (root / slug / "PC" / "vieja.md").write_text("del slug", encoding="utf-8")
    (root / slug / "PC" / "choca.md").write_text("del slug", encoding="utf-8")
    (root / "mi-repo" / "PC").mkdir(parents=True)
    (root / "mi-repo" / "PC" / "choca.md").write_text("la buena", encoding="utf-8")

    vacio = Path(tempfile.mkdtemp())
    real = srv._PROJECT_NAMES
    try:
        srv._PROJECT_NAMES = {}
        seco = srv.repair_memory(projects_dir=vacio, src=root, dry=True)
        assert seco == [{"from": slug, "to": "mi-repo", "files": 2}]
        assert (root / slug).exists()          # a dry run moves nothing

        srv._PROJECT_NAMES = {}
        assert srv.repair_memory(projects_dir=vacio, src=root)
        assert not (root / slug).exists()      # the slug folder is gone
        assert (root / "mi-repo" / "PC" / "vieja.md").exists()
        # the copy already filed under the real identity wins
        assert (root / "mi-repo" / "PC" / "choca.md").read_text(encoding="utf-8") == "la buena"

        srv._PROJECT_NAMES = {}
        assert srv.repair_memory(projects_dir=vacio, src=root) == []   # idempotent
    finally:
        srv._PROJECT_NAMES = real



if __name__ == "__main__":
    test_session_meta()
    test_session_meta_redacts_title()
    test_session_meta_no_prompt()
    test_session_timeline_order_and_redaction()
    test_session_timeline_rich_blocks()
    test_list_and_find_by_id()
    test_list_skills()
    test_get_skill()
    test_delete_and_export_skill()
    test_search_sessions()
    test_search_sessions_accepts_precomputed_rows()
    test_config_sync_roundtrip()
    test_plugins_sync()
    test_machines()
    test_export_sessions()
    test_sync_stage_paths_stay_scoped_to_knowledge_and_vault()
    test_project_identity_from_cwd()
    test_slug_project_writes_marker_when_resolved_from_jsonl()
    test_slug_project_existing_marker_wins_over_scan()
    test_slug_project_falls_back_to_raw_slug_without_marker_or_cwd()
    test_memory_meta()
    test_memory_dirs_groups_by_project()
    test_memory_dirs_ignores_projects_without_memory()
    test_export_memory_mirrors_union()
    test_export_memory_skips_index_and_redacts()
    test_export_memory_deletes_stale_only_in_own_machine()
    test_import_memory_unions_machines_newest_wins()
    test_import_memory_does_not_clobber_newer_local()
    test_import_memory_fresh_checkout_mtime_does_not_clobber_diverged_local()
    test_import_memory_local_delete_is_not_resurrected()
    test_import_memory_identical_local_is_not_rewritten()
    test_import_memory_new_from_other_machine_arrives_when_never_published()
    test_import_memory_writes_every_local_slug()
    test_import_memory_skips_project_without_local_slug()
    test_memory_roundtrip_to_second_machine()
    test_rebuild_index_keeps_existing_adds_new_drops_gone()
    test_rebuild_index_creates_when_missing()
    test_rebuild_index_is_idempotent()
    test_rebuild_index_keeps_lf_endings()
    test_rebuild_index_skips_empty_memory_dir()
    test_list_memory()
    test_list_memory_missing_root()
    test_sync_stage_exports_and_returns_staged_paths()
    test_sync_incoming_lists_paths_and_reports_fetch_error()
    test_sync_incoming_asks_git_for_the_remote_side_only()
    test_the_fetch_clock_survives_a_git_gc()
    test_an_explicit_update_check_fetches_even_with_a_fresh_ref()
    test_update_apply_refuses_an_unrelated_repo_instead_of_forcing_a_merge()
    test_update_apply_never_merges_over_uncommitted_work()
    test_update_apply_merges_upstream_and_says_how_much()
    test_sync_pull_applies_config_even_with_the_branch_up_to_date()
    test_set_badge_chains_the_previous_status_line_and_gives_it_back()
    test_set_badge_leaves_no_status_line_behind_when_there_was_none()
    test_decode_slug_walks_the_disk_back_to_the_real_path()
    test_slug_project_survives_claude_code_pruning_the_transcripts()
    test_repair_memory_refiles_slug_folders_and_never_clobbers()
    test_forget_removes_from_the_repo_and_never_from_the_machine()
    test_forget_drops_a_plugin_from_the_manifest_without_touching_the_others()
    test_forget_takes_another_machines_memory_which_no_export_of_ours_reaches()
    test_a_skill_the_other_machine_dropped_reads_apart_from_one_never_pushed()
    test_the_dropped_lookup_survives_a_repo_git_never_saw()
    test_a_second_agent_is_a_table_entry_and_not_a_patch_across_the_engine()
    test_an_unknown_agent_falls_back_instead_of_exploding()
    test_bring_installs_one_skill_the_repo_carries_and_resolves_home()
    test_apply_config_and_bring_share_one_copy_loop()
    test_memory_neighbours_is_one_level_and_both_directions()
    test_memory_neighbours_reuses_the_graphs_own_link_resolution()
    test_home_data_answers_the_whole_home_in_one_payload()
    print("OK")
