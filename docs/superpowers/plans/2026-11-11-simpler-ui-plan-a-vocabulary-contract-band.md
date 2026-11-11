# Simpler UI, plan A: vocabulary, JSON contract, band — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One vocabulary for every UI, a `sto data` / `sto act` JSON contract the band (now) and the Go TUI (plan B) both read, and a band with one state and one button.

**Architecture:** Strings change in `scripts/i18n.py` only. `ui_data.status_data()` computes the one sync state every UI shows. `cli.py` gains `sto data <view>` (read, one JSON object) and `sto act <verb>` (write, JSON lines: `{"step"}`... then one `{"done"}` or `{"error"}`). The band moves from `sto mod` to the new contract, then `sto mod` is deleted.

**Tech Stack:** Python 3 stdlib (engine, CLI), TypeScript/TSX Claude Code mod API (`mod/sto-band`).

**Spec:** `docs/superpowers/specs/2026-11-11-simpler-ui-design.md` (sections 1, 2 and 4). Plan B (Go TUI + distribution, spec sections 3 and 5) is written when this plan is merged, against the contract this plan fixes.

## Global Constraints

- Work in the public clone `sto-agentic-os`. Never `git add -A` there: running the tests writes `knowledge/projects/<machine>.json`. Add files by name.
- No `Co-Authored-By` or "Generated with" lines in commits.
- Every user-facing string lives in `scripts/i18n.py`, in both `es` and `en` (`test_both_languages_define_the_same_keys` enforces parity).
- No characters in U+2600-27BF or emoji anywhere (`test_no_pictographs_in_the_source`). State symbols: `●` synced, `↑` only on this machine, `↓` only in the cloud, `×` deleted in the cloud, `!` warning.
- Anything printed for a machine reader is JSON, never a traceback: catch `Exception` at the command boundary and return `{"error": "<Type>: <msg>"}`.
- Tests are plain functions run from each file's `if __name__ == "__main__":` block. A new test function must also be appended to that block or it never runs.
- Full suite: `cd scripts && python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui_data.py && python test_tui_app.py` and `uv run --no-project --with textual python scripts/test_tui_app.py`.
- The Textual TUI keeps working through this plan; it only picks up new strings.

---

### Task 1: New vocabulary in `i18n.py`

**Files:**
- Modify: `scripts/i18n.py` (the `es` block around lines 35-250 and the `en` block around 262-480)
- Test: `scripts/test_ui_data.py`

**Interfaces:**
- Produces keys: `state_uptodate`, `state_down` (`{n}`), `state_up` (`{n}`), `st_both`, `st_local`, `st_repo`, `st_gone`, `local_only`, `in_repo_not_installed`, `k_bring`, `k_delete`, `k_forget`, `k_keep`, `k_row_path`, `folder_missing`, `act_sync`, `act_retry`, `sync_failed` (`{e}`), `sync_done`, `s_chats`, `update_notice` (`{n}`), `cloud_is_repo`. Existing `mod_syncing`, `mod_auto_off`, `mod_5h`, `mod_week`, `mod_ctx`, `mod_pulled` stay.

- [ ] **Step 1: Write the failing test** (append to `scripts/test_ui_data.py`, and add the call to its `__main__` block)

```python
def test_the_vocabulary_speaks_of_this_machine_and_the_cloud():
    real = i18n.LANG
    try:
        for lang in ("en", "es"):
            i18n.LANG = lang
            # no git words where a user reads states and verbs
            for key in ("st_both", "st_local", "st_repo", "st_gone", "local_only",
                        "in_repo_not_installed", "k_bring", "k_forget",
                        "state_uptodate", "act_sync"):
                low = i18n.t(key).lower()
                assert not any(w in low for w in ("repo", "push", "pull", "fetch")), (lang, key)
        i18n.LANG = "en"
        assert i18n.t("st_repo") == "only in the cloud"
        assert i18n.t("state_down", n=3) == "3 new in the cloud"
        i18n.LANG = "es"
        assert i18n.t("st_local") == "solo en esta máquina"
        assert i18n.t("act_sync") == "Sincronizar"
    finally:
        i18n.LANG = real
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `cd scripts && python -c "import test_ui_data as t; t.test_the_vocabulary_speaks_of_this_machine_and_the_cloud()"`
Expected: AssertionError on `st_repo` (today "only in the repo").

- [ ] **Step 3: Change and add the strings**

In the `es` block, replace the values of the existing keys and add the new ones next to them:

```python
        "st_both": "sincronizado", "st_local": "solo en esta máquina",
        "st_repo": "solo en la nube", "st_gone": "borrado en la nube",
        "local_only": "solo en esta máquina, todavía no subió",
        "in_repo_not_installed": "solo en la nube, no instalado acá",
        "k_bring": "traer", "k_delete": "borrar de esta máquina",
        "k_forget": "sacar de la nube", "k_keep": "guardar chat completo",
        "k_row_path": "carpeta del proyecto",
        "state_uptodate": "al día", "state_down": "{n} nuevas en la nube",
        "state_up": "{n} para subir",
        "folder_missing": "este proyecto no tiene carpeta en esta máquina; sin ella no podés retomar sus chats",
        "act_sync": "Sincronizar", "act_retry": "reintentar",
        "sync_failed": "no se pudo sincronizar: {e}", "sync_done": "sincronizado",
        "s_chats": "moviendo chats",
        "update_notice": "hay una versión nueva de braingent ({n} cambios)",
        "cloud_is_repo": "La nube es tu repo privado de GitHub",
```

In the `en` block:

```python
        "st_both": "synced", "st_local": "only on this machine",
        "st_repo": "only in the cloud", "st_gone": "deleted in the cloud",
        "local_only": "only on this machine, not sent yet",
        "in_repo_not_installed": "only in the cloud, not installed here",
        "k_bring": "bring", "k_delete": "delete from this machine",
        "k_forget": "remove from the cloud", "k_keep": "keep full chat",
        "k_row_path": "project folder",
        "state_uptodate": "up to date", "state_down": "{n} new in the cloud",
        "state_up": "{n} to send",
        "folder_missing": "this project has no folder on this machine; without it you can't resume its chats",
        "act_sync": "Sync", "act_retry": "retry",
        "sync_failed": "couldn't sync: {e}", "sync_done": "synced",
        "s_chats": "moving chats",
        "update_notice": "a new braingent version is out ({n} changes)",
        "cloud_is_repo": "The cloud is your private GitHub repo",
```

Delete the old definitions of the keys you replaced (each key must appear once per language; grep `"st_both"` etc. to find them). Also reword the progress steps so no git word reaches a user: `s_fetch` -> "checking the cloud" / "revisando la nube", `s_merge` -> "bringing changes" / "trayendo cambios", `s_push` -> "sending to the cloud" / "subiendo a la nube", `s_commit` -> "saving changes" / "guardando cambios".

- [ ] **Step 4: Run the test, expect PASS; then the full suite**

Run: `cd scripts && python test_ui_data.py && python test_cli.py && python test_tui_app.py && cd .. && uv run --no-project --with textual python scripts/test_tui_app.py`
Expected: all pass. If a test pins an old phrase (e.g. "solo en el repo", "sin ruta"), update its expected string to the new one; do not change test logic.

- [ ] **Step 5: Commit**

```bash
git add scripts/i18n.py scripts/test_ui_data.py   # plus any test whose expected string changed, by name
git commit -m "feat(i18n): one vocabulary: this machine and the cloud"
```

---

### Task 2: `ui_data.status_data()` — the one sync state

**Files:**
- Modify: `scripts/ui_data.py` (new functions after `preview_parts`, around line 173)
- Test: `scripts/test_ui_data.py`

**Interfaces:**
- Consumes: `srv.sync_status(fetch)`, `sync_preview(sy)`, `count_items`, `preview_parts`, `update_state()`, `srv.usage_snapshot(detail=False)`, `cli.project_todo(project)`, `srv.project_of_cwd`, `srv.local_project_path`, `srv.set_project_path`, `i18n` keys from Task 1.
- Produces:
  - `state_phrase(down: int, up: int) -> str`
  - `status_data(cwd: str | None = None, fetch: bool = False) -> dict` with exactly these keys:
    `state` (`"uptodate"` | `"pending"`), `down` (int), `up` (int), `phrase` (str),
    `parts` (`{"down": [str], "up": [str]}`), `chats` (`{"down": int, "up": int}`),
    `project` (str | None), `fetchError` (str | None), `update` (int),
    `limits` (list of `{"kind", "label", "percent", "resetsAt"}` or `[]`),
    `machine` (str), `accent` (str ANSI code), `labels` (dict of `DATA_LABELS`).
  - `DATA_LABELS: tuple[str, ...]`

- [ ] **Step 1: Write the failing test** (append; add both to `__main__`)

```python
def test_state_phrase_names_only_the_sides_that_have_something():
    real = i18n.LANG
    try:
        i18n.LANG = "en"
        assert ui.state_phrase(0, 0) == "up to date"
        assert ui.state_phrase(51, 2) == "51 new in the cloud · 2 to send"
        assert ui.state_phrase(0, 2) == "2 to send"
    finally:
        i18n.LANG = real


def test_status_data_sums_the_cloud_and_this_projects_chats_and_saves_the_folder():
    reales = _stub_home()
    real_upd, real_todo = ui.update_state, ui.cli.project_todo
    real_paths = (ui.srv.project_of_cwd, ui.srv.local_project_path, ui.srv.set_project_path)
    saved = {}
    try:
        ui.update_state = lambda force=False: {"available": 2}
        ui.cli.project_todo = lambda p: (["k1"], ["b1", "b2"])
        ui.srv.project_of_cwd = lambda cwd, fallback="": "proj"
        ui.srv.local_project_path = lambda p: None
        ui.srv.set_project_path = lambda p, path: saved.update({p: path}) or {}

        s = ui.status_data()
        assert s["state"] == "pending" and s["down"] == 0 and s["up"] == 3
        assert s["chats"] == {"down": 0, "up": 0} and s["project"] is None
        assert s["update"] == 2 and "act_sync" in s["labels"]

        s = ui.status_data(cwd="/work/proj")
        assert s["up"] == 4 and s["down"] == 2
        assert s["chats"] == {"down": 2, "up": 1}
        assert saved == {"proj": "/work/proj"}
        json.dumps(s)                       # the contract is JSON, all of it
    finally:
        _unstub_home(reales)
        ui.update_state, ui.cli.project_todo = real_upd, real_todo
        (ui.srv.project_of_cwd, ui.srv.local_project_path,
         ui.srv.set_project_path) = real_paths
```

(`_stub_home` makes `sync_preview` return 3 items going up — a session, a memory, a skill — and nothing coming down.)

- [ ] **Step 2: Run, expect FAIL**

Run: `cd scripts && python -c "import test_ui_data as t; t.test_state_phrase_names_only_the_sides_that_have_something()"`
Expected: `AttributeError: module 'ui_data' has no attribute 'state_phrase'`

- [ ] **Step 3: Implement** (in `ui_data.py`, after `preview_parts`)

```python
# what every UI that reads `status_data` paints, in the language `sto ui` picked
DATA_LABELS = ("act_sync", "act_retry", "mod_syncing", "mod_auto_off", "mod_5h",
               "mod_week", "mod_ctx", "st_both", "st_local", "st_repo", "st_gone",
               "k_bring", "k_delete", "k_forget", "k_keep", "k_row_path",
               "folder_missing", "cloud_is_repo")


def state_phrase(down, up):
    """'51 new in the cloud · 2 to send', or 'up to date'. Only the sides that
    have something are named: '0 to send' is a number nobody needs to read."""
    parts = ([t("state_down", n=down)] if down else []) + ([t("state_up", n=up)] if up else [])
    return " · ".join(parts) or t("state_uptodate")


def status_data(cwd=None, fetch=False):
    """The one sync state every UI shows: the TUI header and the band read this
    and nothing else, so they cannot disagree about a number.

    With `cwd` it also counts that project's chats waiting to be kept or
    brought (what `sto act sync --cwd` moves), and records `cwd` as the
    project's folder on this machine when none was saved: the band runs inside
    the project, so asking the user for it would be asking what we know.
    """
    sy = srv.sync_status(fetch=fetch)
    up, down = sync_preview(sy)
    chats, project = {"down": 0, "up": 0}, None
    if cwd:
        project = srv.project_of_cwd(cwd)
        if srv.local_project_path(project) is None:
            srv.set_project_path(project, cwd)
        keep, bring = cli.project_todo(project)
        chats = {"down": len(bring), "up": len(keep)}
    n_up = count_items(up) + chats["up"]
    n_down = count_items(down) + chats["down"]
    return {"state": "pending" if n_up or n_down else "uptodate",
            "down": n_down, "up": n_up, "phrase": state_phrase(n_down, n_up),
            "parts": {"down": preview_parts(down), "up": preview_parts(up)},
            "chats": chats, "project": project,
            "fetchError": sy.get("fetchError"),
            "update": update_state().get("available", 0),
            "limits": srv.usage_snapshot(detail=False).get("limits") or [],
            "machine": srv.LOCAL_MACHINE, "accent": accent_code(),
            "labels": {k: t(k) for k in DATA_LABELS}}
```

Also add `accent_code()` to `ui_data.py`, the accent the user picked (same body as `cli._accent`, which Task 6 deletes):

```python
def accent_code():
    """The ANSI code `sto ui` picked, so every UI paints the same accent."""
    try:
        return json.loads(i18n.PREFS.read_text(encoding="utf-8")).get("accent", "36")
    except (OSError, ValueError, AttributeError):
        return "36"
```

`ui_data.py` already imports `json`, `cli`, `i18n` and `srv`.

- [ ] **Step 4: Run, expect PASS; full suite**

Run: `cd scripts && python test_ui_data.py && python test_cli.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/ui_data.py scripts/test_ui_data.py
git commit -m "feat(ui): status_data, the one sync state every UI reads"
```

---

### Task 3: `sto data <view>` — reads, one JSON object

**Files:**
- Modify: `scripts/cli.py` (new `cmd_data` before `CLI = {`, register `"data": cmd_data`)
- Test: `scripts/test_cli.py`

**Interfaces:**
- Consumes: `ui.status_data`, `ui.module_items`, `ui.search_all`, `cached_sessions`, `mark_synced`, `session_todo`, `srv.list_memory`, `srv.config_status`, `srv.project_paths`.
- Produces: `sto data status [--cwd DIR] [--fetch]`, `sto data chats`, `sto data memories`, `sto data tools`, `sto data search --q TEXT`. Each prints one JSON object. Shapes:
  - `status`: `status_data()` (Task 2).
  - `chats`: `{"rows": [{"id", "title", "project", "machine", "mtime", "state"}], "folders": {project: path | null}}` where `state` is `"both"` | `"local"` (would be kept) | `"repo"` (would be brought), and `machine` is the recording machine's name (this machine's name for local rows).
  - `memories`: `{"projects": srv.list_memory()}`.
  - `tools`: `{"skills": [...], "plugins": [...], "modules": srv.config_status()}`; skill/plugin items are `module_items` rows (`what`, `id`, `label`, `desc`, `where` in `both|local|repo|gone`).
  - `search`: `{"hits": [{"kind", "label", "sub", "ref"}]}`.
  - Any failure: `{"error": "..."}`.

- [ ] **Step 1: Write the failing test** (append; add to `__main__`)

```python
def test_data_views_print_json_and_never_a_traceback():
    import ui_data as ui
    real = (ui.status_data, cli.cached_sessions, cli.mark_synced, cli.srv.list_memory,
            cli.srv.project_paths)
    try:
        ui.status_data = lambda cwd=None, fetch=False: {"state": "uptodate", "cwd": cwd,
                                                       "fetch": fetch}
        cli.cached_sessions = lambda **k: ([{"id": "a", "title": "t", "project": "p",
                                             "mtime": 1.0, "machine": None, "path": "/x"}], {})
        cli.mark_synced = lambda rows: [r.update(synced=False) or r for r in rows]
        cli.srv.list_memory = lambda: [{"project": "p", "memories": []}]
        cli.srv.project_paths = lambda: {"p": {cli.srv.LOCAL_MACHINE: "/work/p"}}

        s = json.loads(cli.main(["data", "status", "--cwd", "/w", "--fetch"])["message"])
        assert s == {"state": "uptodate", "cwd": "/w", "fetch": True}
        c = json.loads(cli.main(["data", "chats"])["message"])
        assert c["rows"][0]["state"] == "local"
        assert c["rows"][0]["machine"] == cli.srv.LOCAL_MACHINE
        assert c["folders"] == {"p": "/work/p"}
        m = json.loads(cli.main(["data", "memories"])["message"])
        assert m["projects"][0]["project"] == "p"

        ui.status_data = lambda **k: 1 / 0
        assert "ZeroDivisionError" in json.loads(cli.main(["data", "status"])["message"])["error"]
        assert "error" in json.loads(cli.main(["data", "bogus"])["message"])
    finally:
        (ui.status_data, cli.cached_sessions, cli.mark_synced, cli.srv.list_memory,
         cli.srv.project_paths) = real
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd scripts && python -c "import test_cli as t; t.test_data_views_print_json_and_never_a_traceback()"`
Expected: `KeyError: 'message'` (main returns `cli_commands` error for unknown `data`).

- [ ] **Step 3: Implement** (in `cli.py`, before `CLI = {`)

```python
def _opts(args, *names):
    """(positional, {name: value}) for `--name value` flags; a flag in `names`
    with no value after it (like `--fetch`) is True."""
    args, opts = list(args), {}
    for name in names:
        flag = "--" + name
        if flag in args:
            i = args.index(flag)
            nxt = args[i + 1] if i + 1 < len(args) else None
            if nxt is None or nxt.startswith("--"):
                opts[name] = True
                del args[i]
            else:
                opts[name] = nxt
                del args[i:i + 2]
    return args, opts


def _data_chats():
    rows, _ = cached_sessions()
    mark_synced(rows)
    state = {"keep": "local", "bring": "repo", None: "both"}
    here = srv.LOCAL_MACHINE
    paths = srv.project_paths()
    return {"rows": [{"id": r["id"], "title": r["title"], "project": r["project"],
                      "machine": r.get("machine") or here, "mtime": r["mtime"],
                      "state": state[session_todo(r)]} for r in rows],
            "folders": {p: (paths.get(p) or {}).get(here)
                        for p in sorted({r["project"] for r in rows})}}


def _ui():
    """`ui_data`, imported on first use: it imports this module at its top,
    so importing it back at ours would be a cycle."""
    import ui_data
    return ui_data


def _data_search(q=""):
    return {"hits": [{k: h[k] for k in ("kind", "label", "sub", "ref")}
                     for h in _ui().search_all(q or "")]}


DATA_VIEWS = {
    "status": lambda o: _ui().status_data(cwd=o.get("cwd"), fetch=bool(o.get("fetch"))),
    "chats": lambda o: _data_chats(),
    "memories": lambda o: {"projects": srv.list_memory()},
    "tools": lambda o: {"skills": _ui().module_items("skills"),
                        "plugins": _ui().module_items("plugins"),
                        "modules": srv.config_status()},
    "search": lambda o: _data_search(o.get("q")),
}


def cmd_data(*args):
    """sto data <view> [--cwd DIR] [--fetch] [--q TEXT] — JSON for the UIs."""
    rest, opts = _opts(args, "cwd", "fetch", "q")
    view = rest[0] if rest else "status"
    try:
        out = (DATA_VIEWS[view](opts) if view in DATA_VIEWS
               else {"error": t("cli_commands", names=", ".join(DATA_VIEWS))})
    except Exception as e:  # a UI parses stdout: never a traceback
        out = {"error": f"{type(e).__name__}: {e}"}
    return {"message": json.dumps(out, ensure_ascii=False, default=str)}
```

Add `"data": cmd_data,` to the `CLI` dict.

- [ ] **Step 4: Run, expect PASS; full suite**

Run: `cd scripts && python test_cli.py && python test_ui_data.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cli.py scripts/test_cli.py
git commit -m "feat(cli): sto data, the read half of the UI contract"
```

---

### Task 4: `sto act <verb>` — writes, JSON lines

**Files:**
- Modify: `scripts/cli.py` (new `cmd_act` after `cmd_data`, register `"act": cmd_act`)
- Test: `scripts/test_cli.py`

**Interfaces:**
- Consumes: `srv.sync_pull(progress)`, `srv.sync_push(progress)`, `project_todo`, `srv.keep_session`, `srv.resume_session`, `srv.bring(target, apply)`, `srv.forget(target, apply)`, `srv.delete_skill`, `srv.plugin_cmd`, `srv.set_project_path`, `srv.project_of_cwd`, `srv.local_project_path`, `_opts` (Task 3).
- Produces (each prints zero or more `{"step": "<translated text>"}` lines, then exactly one final line, `{"done": true, "message": str, ...}` or `{"error": str}`):
  - `sto act sync [--cwd DIR]`: pull, then (with `--cwd`) keep/bring that project's chats, then push. Without `--cwd` it is what `sto mod sync-memories` did.
  - `sto act pull`
  - `sto act bring <kind:name> [--dry]` and `sto act forget <kind:name> [--dry]`: final line carries `"paths": [str]`.
  - `sto act delete <skill:name | plugin:id>`
  - `sto act keep <session-id>` and `sto act resume <session-id>`
  - `sto act set-folder <project> <path>`

- [ ] **Step 1: Write the failing test** (append; add to `__main__`)

```python
def test_act_streams_steps_and_ends_in_exactly_one_final_line():
    import contextlib, io
    real = (cli.srv.sync_pull, cli.srv.sync_push, cli.project_todo,
            cli.srv.keep_session, cli.srv.resume_session, cli.srv.project_of_cwd,
            cli.srv.local_project_path, cli.srv.forget)

    def run(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            final = cli.main(["act", *argv])["message"]
        return [json.loads(l) for l in buf.getvalue().splitlines()], json.loads(final)

    try:
        def pull(progress=None):
            progress("s_fetch")
            return {"ok": True}
        cli.srv.sync_pull = pull
        cli.srv.sync_push = lambda progress=None: {"ok": True}
        cli.project_todo = lambda p: (["k1"], ["b1"])
        cli.srv.keep_session = lambda sid: {"ok": True}
        cli.srv.resume_session = lambda sid: {"ok": True}
        cli.srv.project_of_cwd = lambda cwd, fallback="": "p"
        cli.srv.local_project_path = lambda p: "/work/p"

        steps, final = run("sync", "--cwd", "/work/p")
        assert [s["step"] for s in steps] == [i18n.t("s_fetch"), i18n.t("s_chats")]
        assert final["done"] is True

        cli.srv.sync_push = lambda progress=None: {"error": "no network"}
        _, final = run("sync")
        assert final == {"error": "no network"}

        cli.srv.forget = lambda target, apply=False: (["knowledge/config/skills/skills/x"], None)
        _, final = run("forget", "skill:x", "--dry")
        assert final["paths"] == ["knowledge/config/skills/skills/x"]

        _, final = run("bogus")
        assert "error" in final
        cli.srv.sync_pull = lambda progress=None: 1 / 0
        _, final = run("pull")
        assert "ZeroDivisionError" in final["error"]
    finally:
        (cli.srv.sync_pull, cli.srv.sync_push, cli.project_todo,
         cli.srv.keep_session, cli.srv.resume_session, cli.srv.project_of_cwd,
         cli.srv.local_project_path, cli.srv.forget) = real
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd scripts && python -c "import test_cli as t; t.test_act_streams_steps_and_ends_in_exactly_one_final_line()"`
Expected: `KeyError: 'message'`.

- [ ] **Step 3: Implement** (in `cli.py`, after `cmd_data`)

```python
def _emit(obj):
    """One progress line for whoever reads `sto act` as it runs."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _step(key):
    _emit({"step": t(key)})


def _act_sync(cwd=None):
    res = srv.sync_pull(_step)
    if res.get("error"):
        return {"error": res["error"]}
    note = ""
    if cwd:
        project = srv.project_of_cwd(cwd)
        if srv.local_project_path(project) is None:
            srv.set_project_path(project, cwd)
        keep, bring = project_todo(project)
        if keep or bring:
            _step("s_chats")
        fail = sum("error" in srv.keep_session(s) for s in keep)
        fail += sum("error" in srv.resume_session(s) for s in bring)
        n = len(keep) + len(bring)
        if n:
            note = " · " + t("sync_project_done", ok=n - fail, fail=fail)
    res = srv.sync_push(_step)
    if res.get("error"):
        return {"error": res["error"]}
    return {"done": True, "message": t("sync_done") + note}


def _act_files(fn, target, dry=False):
    paths, err = fn(target, apply=not dry)
    return {"error": err} if err else {"done": True, "message": "", "paths": list(paths)}


def _act_delete(target):
    kind, _, name = target.partition(":")
    if kind == "skill":
        err = srv.delete_skill("personal:" + name)
    elif kind == "plugin":
        err = srv.plugin_cmd("uninstall", name).get("error")
    else:
        err = t("not_deletable", id=kind)
    return {"error": err} if err else {"done": True, "message": t("deleted", id=name)}


def _act_result(res):
    return {"error": res["error"]} if res.get("error") else {"done": True, "message": ""}


ACTS = {
    "sync": lambda a, o: _act_sync(o.get("cwd")),
    "pull": lambda a, o: (lambda r: {"error": r["error"]} if r.get("error")
                          else {"done": True, "message": t("mod_pulled")})(srv.sync_pull(_step)),
    "bring": lambda a, o: _act_files(srv.bring, a[0], bool(o.get("dry"))),
    "forget": lambda a, o: _act_files(srv.forget, a[0], bool(o.get("dry"))),
    "delete": lambda a, o: _act_delete(a[0]),
    "keep": lambda a, o: _act_result(srv.keep_session(a[0])),
    "resume": lambda a, o: _act_result(srv.resume_session(a[0])),
    "set-folder": lambda a, o: _act_result(srv.set_project_path(a[0], a[1])),
}


def cmd_act(*args):
    """sto act <verb> [args] [--cwd DIR] [--dry] — JSON lines for the UIs: steps,
    then exactly one final `done` or `error` line."""
    rest, opts = _opts(args, "cwd", "dry")
    verb = rest[0] if rest else ""
    try:
        out = (ACTS[verb](rest[1:], opts) if verb in ACTS
               else {"error": t("cli_commands", names=", ".join(ACTS))})
    except Exception as e:  # a UI parses stdout: never a traceback
        out = {"error": f"{type(e).__name__}: {e}"}
    return {"message": json.dumps(out, ensure_ascii=False, default=str)}
```

Register `"act": cmd_act,` in `CLI`. `sync_project_done`, `not_deletable` and `deleted` already exist in `i18n.py`; confirm with `grep -n '"sync_project_done"\|"not_deletable"\|"deleted"' scripts/i18n.py`. A missing positional (`sto act keep` with no id) raises `IndexError`, which the `except` turns into `{"error": "IndexError: ..."}` — that is the intended behavior.

- [ ] **Step 4: Run, expect PASS; full suite**

Run: `cd scripts && python test_cli.py && python test_ui_data.py && python test_sessions_server.py`
Expected: pass.

- [ ] **Step 5: Smoke test on the real repo (read-only verbs only)**

Run: `cd scripts && python cli.py data status --cwd "$PWD/.." | python -m json.tool | head -20` and `python cli.py act forget skill:does-not-exist --dry`
Expected: a status object with `phrase`; a final `{"error": ...}` line for the missing skill.

- [ ] **Step 6: Commit**

```bash
git add scripts/cli.py scripts/test_cli.py
git commit -m "feat(cli): sto act, the write half of the UI contract"
```

---

### Task 5: The band on the new contract

**Files:**
- Modify: `mod/sto-band/hooks/register.tsx` (rewrite)
- Modify: `mod/sto-band/types/index.d.ts`
- Modify: `mod/sto-band/tests/band.test.tsx` (rewrite)
- Modify: `mod/sto-band/.claude-plugin/plugin.json` (version `0.3.0`, new description)

**Interfaces:**
- Consumes: `sto data status --cwd DIR --fetch` (Task 2/3 shape), `sto act sync --cwd DIR`, `sto act sync`, `sto act pull` (Task 4).
- Produces: commands `/sto`, `/sto sync`, `/sto auto`; buttons with keys `sync` (shown only when pending), `retry` (shown only on error), `auto` (shown only when auto is off).

- [ ] **Step 1: Check whether the mod API can stream a process**

Run: `grep -rn "process" "$(dirname "$(readlink -f "$(which claude)")")"/../**/*.d.ts 2>/dev/null | grep -i "stream\|onStdout\|spawn" | head` (or ask the `plugin-authoring` skill). If there is no streaming API, the band shows `syncing…` with no step text and reads only the last stdout line; that is the plan's default and what the code below does. If streaming exists, it is a follow-up, not part of this task.

- [ ] **Step 2: Write the failing tests** (replace `tests/band.test.tsx`)

```tsx
import { expect, mock, test } from 'claude-code/testing'

const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 3, bodyColumns: 120,
           scroll: { offset: 0, bodyRows: 1 }, view: {} },
} as const

const LABELS = { act_sync: 'Sincronizar', act_retry: 'reintentar', mod_syncing: 'sincronizando…',
                 mod_auto_off: 'auto: no', mod_5h: '5h', mod_week: 'sem', mod_ctx: 'ctx' }
const PENDING = { state: 'pending', down: 51, up: 2, phrase: '51 nuevas en la nube · 2 para subir',
                  fetchError: null, accent: '36', labels: LABELS }
const UPTODATE = { ...PENDING, state: 'uptodate', down: 0, up: 0, phrase: 'al día' }

function fake(on: any, status: object, calls: string[][] = []) {
  on('session.cwd', async () => ({ value: '/work/p' }))
  on('session.usage', async () => ({ value: {
    startedAt: 0, context: { window: 200_000, percent: 22 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 34 }, { kind: 'seven_day', percentUsed: 61.4 }],
  } }))
  on('process.run', async (_$: unknown, e: any) => {
    calls.push([...e.argv])
    const out = e.argv[1] === 'data' ? status
      : JSON.stringify({ step: 'x' }) + '\n' + JSON.stringify({ done: true, message: 'sincronizado' })
    return { value: { exitCode: 0, stdout: typeof out === 'string' ? out : JSON.stringify(out),
                      stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
}

test('pending: arrows, one Sync button, the plan windows', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const calls: string[][] = []
  fake(on, PENDING, calls)
  const res = await $.command.run({ command: 'sto' } as never)
  expect(calls[0]).toEqual(['sto', 'data', 'status', '--cwd', '/work/p', '--fetch'])
  expect(res.text).toBe(PENDING.phrase)

  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  const text = (await ui.find({ type: 'Box' }))?.text ?? ''
  expect(text).toContain('braingent')
  expect(text).toContain('↓51 ↑2')
  expect(text).not.toContain('repo')
  expect(text).toContain('5h 34%')
  expect(text).toContain('ctx 22%')
  expect(!!(await ui.find({ key: 'auto' }))).toBe(false)
  await ui.press({ key: 'sync' })
  expect(calls.some(c => c.join(' ') === 'sto act sync --cwd /work/p')).toBe(true)
  await ui.unmount()
})

test('up to date: the phrase and no button; auto off shows and is remembered', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const saved: unknown[] = []
  on('store.set', async (_$, e) => (saved.push(e), { value: undefined }))
  fake(on, UPTODATE)
  await $.command.run({ command: 'sto' } as never)
  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  expect((await ui.find({ type: 'Box' }))?.text).toContain('al día')
  expect(!!(await ui.find({ key: 'sync' }))).toBe(false)
  await ui.unmount()

  const off = await $.command.run({ command: 'sto', args: 'auto' } as never)
  expect(off.text).toContain('off')
  expect(JSON.stringify(saved)).toContain('false')
  const ui2 = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  expect((await ui2.find({ key: 'auto' }))?.text).toContain('auto: no')
  await ui2.unmount()
})

test('a failed sync says why and offers retry', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  on('session.cwd', async () => ({ value: '/work/p' }))
  on('session.usage', async () => ({ value: { startedAt: 0, context: { window: 1 }, rateLimits: [] } }))
  on('process.run', async (_$, e) => {
    const out = e.argv[1] === 'data' ? PENDING : { error: 'sin conexión' }
    return { value: { exitCode: 0, stdout: JSON.stringify(out), stderr: '',
                      isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const res = await $.command.run({ command: 'sto', args: 'sync' } as never)
  expect(res.text).toBe('sin conexión')
  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  expect((await ui.find({ type: 'Box' }))?.text).toContain('! sin conexión')
  expect(!!(await ui.find({ key: 'retry' }))).toBe(true)
  await ui.unmount()
})
```

- [ ] **Step 3: Run, expect FAIL**

Run: `claude plugin test mod/sto-band` (if the syntax differs, `claude plugin test --help`)
Expected: failures on `data` argv and `↓51 ↑2`.

- [ ] **Step 4: Rewrite `types/index.d.ts`**

```ts
/** What `sto data status` prints (the fields the band reads). */
export type StoStatus = {
  state: 'uptodate' | 'pending'
  down: number
  up: number
  phrase: string
  fetchError: string | null
  accent: string
  labels: Record<string, string>
}

export type Usage = { fiveHour?: number; week?: number; ctx?: number }

declare module 'claude-code' {
  interface PluginState {
    'sto-band': {
      status: StoStatus | null
      error: string | null
      usage: Usage
      isBusy: boolean
      isAuto: boolean
    }
  }
}
```

- [ ] **Step 5: Rewrite `hooks/register.tsx`**

```tsx
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionContextUsage, SessionRateLimit } from 'claude-code'

import type { StoStatus, Usage } from '../types'

// The band asks `sto` for everything sync-related, so the rules stay in one
// place (scripts/cli.py, scripts/ui_data.py) and the strings in scripts/i18n.py.
// It reads the same `sto data status` the TUI header reads: one number, two UIs.
const status = atom({ plugin: 'sto-band', key: 'status' } as const, null)
const error = atom({ plugin: 'sto-band', key: 'error' } as const, null)
const usage = atom({ plugin: 'sto-band', key: 'usage' } as const, {})
const isBusy = atom({ plugin: 'sto-band', key: 'isBusy' } as const, false)
const isAuto = atom({ plugin: 'sto-band', key: 'isAuto' } as const, true)

const REFRESH_MS = 60_000
const AUTO_MS = 30 * 60_000
const ANSI: Record<string, string> = {
  '31': 'red', '32': 'green', '33': 'yellow',
  '34': 'blue', '35': 'magenta', '36': 'cyan',
}

export function toUsage(limits: readonly SessionRateLimit[], context: SessionContextUsage): Usage {
  const pct = (kind: string) => limits.find(l => l.kind === kind)?.percentUsed
  return { fiveHour: pct('five_hour'), week: pct('seven_day'), ctx: context.percent }
}

/** `sto <argv>`'s last stdout line as JSON: `sto act` prints steps before its
 *  final line, `sto data` prints one line. Or the reason, in one line. */
async function sto($: EngineInterface, argv: string[], long = false): Promise<{ data?: any; error?: string }> {
  try {
    const r = await $.process.run(['sto', ...argv], { timeoutMs: long ? 600_000 : 30_000 })
    const last = r.stdout.trim().split('\n').pop() ?? ''
    const data = JSON.parse(last)
    return data.error ? { error: data.error } : { data }
  } catch (err) {
    return { error: 'sto: ' + String((err as Error)?.message ?? err).slice(0, 80) }
  }
}

let lastAt = 0

/** Ask `sto` again, at most once a minute unless somebody pressed for it. */
async function refresh($: EngineInterface, force = false) {
  const now = await $.clock.now()
  if (!force && now - lastAt < REFRESH_MS) return
  lastAt = now
  const u = await $.session.usage()
  await update($, usage, () => toUsage(u.rateLimits, u.context))
  const cwd = await $.session.cwd()
  const r = await sto($, ['data', 'status', '--cwd', cwd, '--fetch'])
  await update($, error, () => r.error ?? r.data?.fetchError ?? null)
  if (r.data) await update($, status, () => r.data as StoStatus)
}

/** One sync at a time, whoever asked: the button, a command or the timer.
 *  `act sync --cwd` moves this project's chats too (the button and /sto sync);
 *  the timer's bare `act sync` carries memories and config. `quiet` toasts
 *  only a failure. */
async function runSync($: EngineInterface, argv: string[], quiet = false): Promise<string> {
  if (await read($, isBusy)) return (await read($, status))?.labels?.mod_syncing ?? 'syncing…'
  await update($, isBusy, () => true)
  let r: { data?: any; error?: string } = {}
  try {
    r = await sto($, argv, true)
  } finally {
    await update($, isBusy, () => false)
    await refresh($, true)
  }
  // after the refresh, or its fresh status would wipe the reason this sync failed
  if (r.error) await update($, error, () => r.error!)
  const text = r.error ?? r.data?.message ?? ''
  if (r.error || !quiet) $.ui.toast(text)
  return text
}

async function syncHere($: EngineInterface, quiet = false) {
  return runSync($, ['act', 'sync', '--cwd', await $.session.cwd()], quiet)
}

/** Auto on or off, remembered across sessions in the store. */
async function setAuto($: EngineInterface, isOn: boolean) {
  await $.store.set('auto', isOn)
  await update($, isAuto, () => isOn)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'sto',
      description: '/sto sync: sync now. /sto auto: auto sync on/off. Bare: the state in one line',
    })
    const auto = (await $.store.get('auto')) !== false
    await update($, isAuto, () => auto)
    // bring down before anything else: the memories another machine wrote land
    // before the first prompt reads them
    void (auto ? runSync($, ['act', 'pull'], true) : refresh($, true))
    $.clock.every(AUTO_MS, () => {
      void (async () => {
        if (await read($, isAuto)) await runSync($, ['act', 'sync'], true)
      })()
    })
    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    await update($, usage, () => toUsage(e.rateLimits, e.context))
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    void refresh($)
    return next(e)
  })

  on('command.run', { command: 'sto' }, async ($, e) => {
    const arg = (e.args ?? '').trim()
    if (arg === 'sync') return { text: await syncHere($) }
    if (arg === 'auto') {
      const turnOn = !(await read($, isAuto))
      await setAuto($, turnOn)
      return { text: 'braingent auto: ' + (turnOn ? 'on' : 'off') }
    }
    await refresh($, true)
    return { text: (await read($, error)) ?? (await read($, status))?.phrase ?? '' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const s = await read($, status)
    const err = await read($, error)
    const u = await read($, usage)
    const busy = await read($, isBusy)
    const auto = await read($, isAuto)
    const { Box, Button, Text } = $.ui.resolve(e)
    const L = (k: string, en: string) => s?.labels?.[k] ?? en
    const accent = ANSI[s?.accent ?? '36'] ?? 'cyan'
    const pct = (label: string, v?: number) =>
      v === undefined ? null : <Text dimColor>{label} {Math.round(v)}%  </Text>
    const arrows = s ? [s.down ? '↓' + s.down : '', s.up ? '↑' + s.up : ''].filter(Boolean).join(' ') : ''

    return (
      <Box>
        <Text color={accent} bold>braingent  </Text>
        {busy && <Text color={accent}>{L('mod_syncing', 'syncing…')}  </Text>}
        {!busy && err && <Text color="warning">! {err.slice(0, 60)}  </Text>}
        {!busy && err && <Button key="retry" label={L('act_retry', 'retry')}
                                 onPress={() => void syncHere($)} />}
        {!busy && !err && s?.state === 'pending' && <Text color={accent}>{arrows}  </Text>}
        {!busy && !err && s?.state === 'pending' &&
          <Button key="sync" label={L('act_sync', 'Sync')} onPress={() => void syncHere($)} />}
        {!busy && !err && s?.state === 'uptodate' && <Text dimColor>{s.phrase}  </Text>}
        {pct(L('mod_5h', '5h'), u.fiveHour)}
        {pct(L('mod_week', 'wk'), u.week)}
        {pct(L('mod_ctx', 'ctx'), u.ctx)}
        {!auto && <Button key="auto" dimColor label={L('mod_auto_off', 'auto: off')}
                          onPress={() => void setAuto($, true)} />}
      </Box>
    )
  })
}
```

- [ ] **Step 6: Bump `plugin.json`**

```json
{ "name": "sto-band", "version": "0.3.0", "description": "braingent above the prompt: whether this machine and the cloud are in sync, one Sync button, the 5h and weekly limits, the context window", "types": "./types/index.d.ts" }
```

- [ ] **Step 7: Run, expect PASS**

Run: `claude plugin validate mod/sto-band && claude plugin test mod/sto-band`
Expected: three tests pass, validation clean.

- [ ] **Step 8: Commit**

```bash
git add mod/sto-band/hooks/register.tsx mod/sto-band/types/index.d.ts mod/sto-band/tests/band.test.tsx mod/sto-band/.claude-plugin/plugin.json
git commit -m "feat(mod): band with one state and one Sync button, on sto data/act"
```

---

### Task 6: Delete `sto mod`

**Files:**
- Modify: `scripts/cli.py` (delete `MOD_LABELS`, `mod_status`, `_accent`, `mod_sync`, `mod_pull`, `mod_sync_memories`, `MOD_SUBS`, `cmd_mod`, the `"mod"` entry in `CLI`)
- Modify: `scripts/i18n.py` (delete keys nothing reads any more)
- Modify: `scripts/test_cli.py` (`test_session_todo_and_the_mod_json` keeps its `session_todo` half)
- Modify: `scripts/ui_data.py` (`commands()` list, if it names `mod`)

**Interfaces:**
- Consumes: nothing new. After this task `sto mod` answers the "unknown command" error.

- [ ] **Step 1: Change the test first**

In `scripts/test_cli.py`, rename `test_session_todo_and_the_mod_json` to `test_session_todo` (also in `__main__`) and replace its last four lines (from `# the band parses stdout` on) with:

```python
    # the band moved to `sto data` / `sto act`
    assert "mod" not in cli.CLI
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd scripts && python -c "import test_cli as t; t.test_session_todo()"`
Expected: AssertionError.

- [ ] **Step 3: Delete the code**

Delete the functions and constants listed under **Files** from `cli.py`. Then find keys nobody reads:

Run: `cd scripts && for k in mod_chats mod_uptodate mod_no_path mod_repo mod_btn_chats mod_btn_memories mod_auto_on mod_memories_done; do echo "$k $(grep -rn "\"$k\"\|'$k'" --include=*.py --include=*.tsx .. | grep -v 'i18n.py' | wc -l)"; done`

Delete from both languages in `i18n.py` every key whose count is 0. Check `grep -n '"mod"' ui_data.py` and drop a `sto mod` entry from `commands()` if there is one.

- [ ] **Step 4: Full suite, expect PASS**

Run: `cd scripts && python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui_data.py && python test_tui_app.py && cd .. && uv run --no-project --with textual python scripts/test_tui_app.py && claude plugin test mod/sto-band`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cli.py scripts/i18n.py scripts/test_cli.py scripts/ui_data.py
git commit -m "refactor(cli): drop sto mod, the band reads sto data/act"
```

---

### Task 7: Ship and record

**Files:**
- Modify (private clone `my-agentic-os`): `vault/wiki/sto-band-mod-claude-code.md`, new `vault/wiki/sto-ui-contrato-data-act.md`, `vault/wiki/index.md`

- [ ] **Step 1: Push the public clone** (ask the user before pushing)

```bash
cd ../sto-agentic-os && git push
```

- [ ] **Step 2: Update the private clone and reload the band**

```bash
cd ../my-agentic-os && sto update --apply
```

Then in Claude Code: `/reload-plugins`. Check by eye: band reads `braingent  ↓N ↑M  [Sincronizar]` or `braingent  al día`; pressing Sincronizar ends in a `sincronizado` toast; no `repo` or `sin ruta` anywhere.

- [ ] **Step 3: Wiki notes** (Spanish, one idea per file, linked)

- `vault/wiki/sto-ui-contrato-data-act.md`: what `sto data` / `sto act` are, the JSON line protocol (steps, then one final `done`/`error`), why subprocess and not HTTP (spec section 2), and that the Go TUI of plan B is its second reader. Link `[[sto-band-mod-claude-code]]`, `[[sto-sync-como-funciona]]`.
- `vault/wiki/sto-band-mod-claude-code.md`: replace the v0.2.0 description (two buttons, `sto mod`) with v0.3.0 (one state, one button, auto without a button, `/sto mem` gone) and link the new note.
- `vault/wiki/index.md`: one line for the new note.

- [ ] **Step 4: Commit in the private clone**

```bash
git add vault/wiki/sto-ui-contrato-data-act.md vault/wiki/sto-band-mod-claude-code.md vault/wiki/index.md
git commit -m "knowledge: contrato sto data/act y band 0.3.0"
```

---

## Not in this plan

- Go TUI, `sto ui` launcher, release Action, deleting Textual: plan B, written against the contract above once it is merged. Plan B adds `sto data settings` and `sto data detail <kind> <id>` when it builds those screens.
- Renaming the human CLI verbs (`sto push` / `sto pull` -> `sto sync`): not asked for; add when the Go TUI ships and the CLI is the last place that says push.
- Step text inside the band during a sync: needs a streaming process API (Task 5, Step 1).
