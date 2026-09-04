"""Shared UI logic: the computed state both the CLI and the TUI read.

This is what is left of `ui.py` once the stdlib TUI was removed. The rendering
half went with it — the alt screen, the `msvcrt` key loop, the diff-based
repaint — and `tui_app.py` is the only front-end now. What stayed was never
about drawing: sync parity, knowledge counts, the accent and language prefs,
transcript search, memory detail. Two callers share it, so it lives apart from
either.
"""
import json
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import cli  # noqa: E402
import i18n  # noqa: E402
import sessions_server as srv  # noqa: E402


# Strings and language live in `i18n` because the CLI uses them too; what stays
# here is the accent colour, which belongs to the screen and to nobody else.
STRINGS, LANGS, t = i18n.STRINGS, i18n.LANGS, i18n.t
ACCENTS = [("c_turquesa", "36"), ("c_verde", "32"), ("c_violeta", "35"),
           ("c_azul", "34"), ("c_amarillo", "33"), ("c_rojo", "31")]
ACCENT = "36"


def set_accent(code):
    global ACCENT
    ACCENT = code
    return i18n.set_pref("accent", code)


def set_lang(code):
    i18n.set_lang(code)
    _SUMMARY["ts"] = 0.0     # the header summary is cached, and it is text
    return code


def accent_name(code=None):
    code = ACCENT if code is None else code
    return t(next((k for k, c in ACCENTS if c == code), code))


def strip_ansi(s):
    """The text without colour codes — to measure width and for the tests."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            if j < 0:
                break
            i = j + 1
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _reset_at(iso):
    """'2026-08-14T18:00:00Z' → 'resets Fri 15:00' in local time. Without data, ''.

    The quota endpoint returns UTC; painting that hour as-is claims the quota
    resets three hours later than it actually does.

    And the hour alone answers the wrong question. The weekly limit resets four
    days out, where `resets 15:00` reads as *today* at three — the hour is the
    part you can guess, the day is the part you need. So the day shows up
    whenever it is not today, and the weekday comes from `i18n` and not from
    `strftime`, which would print English names on a Spanish UI.
    """
    if not isinstance(iso, str) or "T" not in iso:
        return ""              # a bare date has no reset time
    try:
        local = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    hora = f"{local:%H:%M}"
    dias = (local.date() - datetime.now().astimezone().date()).days
    if dias <= 0:
        return t("resets_at", h=hora)
    if dias == 1:
        return t("resets_tomorrow", h=hora)
    if dias < 7:
        return t("resets_on", d=t("dow").split(",")[local.weekday()], h=hora)
    return t("resets_on", d=f"{local:%d/%m}", h=hora)


def sync_preview(sy=None):
    """(up, down) classified: which knowledge/vault files would travel.

    Cheap on purpose — two `git diff --name-only` and one `git status`, no
    network and nothing exported. It is not the same as the confirmation
    manifest, which does run the `export_*` and can therefore see more: this is
    what is already committed but unpushed, plus what is dirty in the working
    tree.
    """
    sy = sy or srv.sync_status(fetch=False)
    branch = sy.get("branch") or "main"

    def paths(*args):
        code, out = srv._git(*args)
        return [p for p in out.splitlines() if p.strip()] if code == 0 else []

    # three dots: two diff the whole trees and each side sees itself reflected
    # in the other (while ahead, `HEAD..origin/x` returned your own files as if
    # they were coming down to you). Three start from the merge base.
    up = paths("diff", "--name-only", f"origin/{branch}...HEAD",
               "--", "knowledge", "vault")
    up += [l[3:] for l in paths("status", "--porcelain", "--", "knowledge", "vault")]
    down = paths("diff", "--name-only", f"HEAD...origin/{branch}",
                 "--", "knowledge", "vault")
    subir, bajar = classify(sorted(set(up))), classify(sorted(set(down)))

    # The half git cannot see. A memory Claude wrote a minute ago is not dirty
    # until `export_memory` has run, and a skill sitting in the repo is not
    # installed on this machine no matter how up to date the branch is. Both
    # are dry runs: they read and compare, they write nothing.
    prefs = srv.get_sync_prefs()
    subir["activate"] = srv.export_config(prefs, dry=True)
    bajar["activate"] = srv.apply_config(prefs, dry=True)
    subir["pending_memories"] = srv.export_memory(dry=True)
    bajar["pending_memories"] = srv.import_memory(dry=True)
    _write_badge(count_items(subir), count_items(bajar))
    return subir, bajar


def _write_badge(up, down):
    """Leave the two numbers where `statusline.py` can read them.

    The status line in Claude Code re-renders constantly and cannot afford to
    compute this itself, so whoever already paid for it drops the answer on
    disk. A failure here is not worth a line of error: the badge just shows up
    without counts.
    """
    try:
        path = srv.CACHE_DIR / "badge.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": time.time(), "up": up, "down": down}),
                        encoding="utf-8")
    except OSError:
        pass


def count_items(data):
    # max() and not a sum for the memories: the git diff and the dry import
    # describe the same files from two angles (commits not merged yet vs repo
    # files this machine never took), and adding them double-counts.
    return (data["sessions"] + data["vault"] + len(data["skills"])
            + len(data["config"]) + data.get("activate", 0)
            + max(sum(data["memories"].values()), data.get("pending_memories", 0)))


def preview_parts(data):
    """['12 sessions', '4 memories', '3 skills'] — empty when nothing travels."""
    out = []
    if data["sessions"]:
        out.append(f"{data['sessions']} {t('n_sessions')}")
    memories = max(sum(data["memories"].values()), data.get("pending_memories", 0))
    if memories:
        out.append(f"{memories} {t('n_memories')}")
    if data["skills"]:
        out.append(f"{len(data['skills'])} skills")
    if data["config"]:
        out.append(f"{len(data['config'])} config")
    if data["vault"]:
        out.append(f"{data['vault']} vault")
    if data.get("activate"):
        out.append(f"{data['activate']} {t('n_activate')}")
    return out


def counters():
    """The big numbers on the home: sessions, projects, memories, skills…"""
    rows, _ = cli.cached_sessions()
    return [("n_sessions", len(rows)),
            ("n_projects", len({r["project"] for r in rows})),
            ("n_memories", knowledge_counts()["memories"]),
            ("n_skills", len(_personal_skills(None))),
            ("n_machines", len(srv.list_machines()))]


def _where(name, local, repo):
    """Which side of the sync holds this item: both, only here, only in the repo."""
    return "both" if name in local and name in repo else ("local" if name in local else "repo")


def module_items(mod, claude_dir=None, repo_config=None):
    """What a config module holds on this machine.

    `skills` and `plugins` come from the server APIs and can be deleted. The
    rest are loose files under `~/.claude`: they are listed so you can look at
    them, but deleting them has no safe operation on the other side, so no.
    """
    cd = claude_dir or srv.CLAUDE_DIR
    cfg = repo_config if repo_config is not None else srv.KNOWLEDGE_CONFIG
    if mod == "skills":
        local = _personal_skills(claude_dir)
        repo = _personal_skills(cfg / "skills")
        # what the repo carries and this machine does not is listed too, and it
        # is the only reason `R` has anything to act on: the guard in
        # `srv.forget` refuses everything that is still installed here
        # the fourth state is not on disk anywhere: `local` can mean "new here,
        # never pushed" or "another machine dropped it and you pulled that".
        # git kept the answer, so no tombstone file has to exist
        gone = srv.dropped_skills()
        rows = []
        for name in sorted(set(local) | set(repo)):
            row = local.get(name) or repo[name]
            where = _where(name, local, repo)
            rows.append({"kind": "item", "what": "skill", "id": row["id"],
                         "label": name, "desc": row.get("description", ""),
                         "where": "gone" if where == "local" and name in gone else where})
        return rows
    if mod == "plugins":
        _, installed = srv._local_plugins(claude_dir)
        _, in_repo = srv._repo_plugins(cfg)
        return [{"kind": "item", "what": "plugin", "id": p, "label": p, "desc": "",
                 "where": _where(p, set(installed), set(in_repo))}
                for p in sorted(set(installed) | set(in_repo))]
    out = []
    for entry in srv.CONFIG_MODULES.get(mod, ()):
        base = cd / entry
        if base.is_file():
            out.append({"kind": "item", "what": "file", "id": str(base),
                        "label": entry, "desc": ""})
        elif base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file() and f.name not in srv.CONFIG_EXCLUDE:
                    out.append({"kind": "item", "what": "file", "id": str(f),
                                "label": str(f.relative_to(base)), "desc": ""})
    return out


_INDEX: dict[str, tuple[float, str]] = {}
_TOOLS: dict = {"stamp": None, "rows": []}


def _indexed(paths):
    """`{path: (mtime, lowercased text)}`, re-reading only what moved.

    Derived and disposable: the files stay the source of truth, so the worst a
    stale entry can be is as stale as an mtime. Entries for files that have
    since been deleted are left in the dict rather than swept -- this is called
    with one corpus at a time, so "not in the argument" does not mean "gone",
    and a few dead strings cost less than being wrong about that.
    """
    out = {}
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        key = str(path)
        hit = _INDEX.get(key)
        if hit is None or hit[0] != mtime:
            try:
                hit = (mtime, path.read_text(encoding="utf-8",
                                             errors="replace").lower())
            except OSError:
                continue
            _INDEX[key] = hit
        out[key] = hit
    return out


def _score(terms, name, desc, body):
    """How well one item answers the query. `0.0` means it does not.

    Where a term hits weighs more than how often: a note *called* `textual` is
    about textual, one that mentions it in passing is not. The count still
    counts, capped, so it can break a tie between two bodies but never outrank
    a title.

    Every term has to land somewhere or the item is out. Searching two words
    and getting back the union of both is how a search returns everything.
    """
    total = 0.0
    for term in terms:
        best = 0.0
        for text, weight in ((name, 3.0), (desc, 2.0), (body, 1.0)):
            if text and term in text:
                best = max(best, weight + min(text.count(term), 10) * 0.1)
        if not best:
            return 0.0
        total += best
    return total


def _tool_rows():
    """Every config module's items, with the module on each row.

    Cached against the mtimes of the module entries: walking them is a quarter
    of a second, which is fine once and impossible per keystroke. `plugins` has
    no entry to stat -- it is a manifest, not a directory -- so it rides on the
    others' stamp and refreshes with them.
    """
    stamp = []
    for entries in srv.CONFIG_MODULES.values():
        for entry in entries:
            try:
                stamp.append((srv.CLAUDE_DIR / entry).stat().st_mtime)
            except OSError:
                stamp.append(0.0)
    stamp = tuple(stamp)
    if _TOOLS["stamp"] != stamp:
        _TOOLS["rows"] = [dict(row, module=mod)
                          for mod in srv.CONFIG_MODULES
                          for row in module_items(mod)]
        _TOOLS["stamp"] = stamp
    return _TOOLS["rows"]


def search_all(q, limit=40):
    """Sessions, memories, tools and vault notes, ranked into one list.

    Each hit says which corpus it came from, because that is the whole
    difference between a search and a pile.
    """
    terms = [x for x in q.strip().lower().split() if x]
    if not terms:
        return []
    hits = []

    # `search_sessions` picks the candidates -- it is typo-tolerant and it
    # searches prompt bodies through an index it already keeps -- but the score
    # is recomputed here. Its own is on another scale entirely, and ranking the
    # corpora against each other with it buried every memory and note under
    # forty sessions. The floor is for the hits it found through a typo, which
    # `_score` cannot see and would drop.
    rows, prompts = cli.cached_sessions()
    for r in srv.search_sessions(q, rows=rows, limit=limit):
        score = _score(terms, r["title"].lower(), "", prompts.get(r["id"], ""))
        hits.append({"kind": "session", "label": r["title"], "sub": r["project"],
                     "score": max(score, 1.0), "mtime": r["mtime"], "ref": r})

    memories = {}
    for p in srv.list_memory():
        for m in p["memories"]:
            path = (srv.KNOWLEDGE_MEMORY / p["project"] / m["machine"]
                    / f"{m['slug']}.md")
            memories[path] = (p, m)
    text = _indexed(memories)
    for path, (p, m) in memories.items():
        body = text.get(str(path), (0.0, ""))[1]
        score = _score(terms, m["slug"].lower(),
                       (m["description"] or "").lower(), body)
        if score:
            hits.append({"kind": "memory", "label": m["slug"],
                         "sub": f"{srv._proj_label(p['project'])} \u00b7 {m['machine']}",
                         "score": score, "mtime": m["mtime"],
                         "ref": {"project": p["project"], "slug": m["slug"],
                                 "machine": m["machine"]}})

    notes = sorted((srv.REPO_ROOT / "vault").rglob("*.md"))
    text = _indexed(notes)
    for path in notes:
        mtime, body = text.get(str(path), (0.0, ""))
        score = _score(terms, path.stem.lower(), "", body)
        if score:
            hits.append({"kind": "note", "label": path.stem,
                         "sub": path.parent.name, "score": score,
                         "mtime": mtime, "ref": {"path": str(path)}})

    for row in _tool_rows():
        # a tool has a name and a description and no body: it is found by what
        # it is called and by what it says it does
        score = _score(terms, row["label"].lower(), (row["desc"] or "").lower(), "")
        if score:
            hits.append({"kind": "tool", "label": row["label"],
                         "sub": row["module"], "score": score, "mtime": 0.0,
                         "ref": {"module": row["module"], "id": row["id"],
                                 "what": row["what"]}})

    hits.sort(key=lambda h: (-h["score"], -h["mtime"]))
    return hits[:limit]


def detail_memory(row):
    f = srv.KNOWLEDGE_MEMORY / row["project"] / row["machine"] / f"{row['slug']}.md"
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return [f"error: could not read {f} ({e})"]
    return lines + _neighbour_lines(row)


def _neighbour_lines(row):
    """One level of the graph, in words.

    The prototype drew the graph with ASCII boxes; that is legible with five
    nodes and unreadable with fifty, so the spatial view stays in the `g`
    window. What belongs in the text is the neighbourhood — it answers "what
    does this connect to", which is the question you have while reading a
    memory, without pretending to be a map.
    """
    try:
        out, inc = srv.memory_neighbours(row["project"], row["slug"])
    except Exception:
        return []                      # a memory reads fine without its edges
    if not (out or inc):
        return []
    lines = ["", cli.c(t("mem_links"), cli.BOLD)]
    for arrow, ids in (("→", out), ("←", inc)):
        for mid in ids:
            proj, _, slug = mid.rpartition("/")
            tail = "" if proj == row["project"] else cli.c(f"  ({proj})", cli.DIM)
            lines.append(f"  {cli.c(arrow, ACCENT)} {slug}{tail}")
    return lines


def _origin():
    code, url = srv._git("remote", "get-url", "origin")
    return url.strip() if code == 0 and url.strip() else ""


def _upstream():
    code, url = srv._git("remote", "get-url", srv.UPSTREAM)
    return url.strip() if code == 0 and url.strip() else ""


def _count(root, glob):
    try:
        return sum(1 for _ in root.rglob(glob))
    except OSError:
        return 0


def knowledge_counts():
    """How much knowledge the repo holds. It does not depend on
    `get_sync_prefs()`: memories, sessions and vault are always exported by
    `sync_stage()`."""
    return {"memories": sum(p["count"] for p in srv.list_memory()),
            "sessions": _count(srv.KNOWLEDGE_SESSIONS, "*.jsonl"),
            "vault": _count(srv.REPO_ROOT / "vault", "*.md")}


def _personal_skills(claude_dir):
    """{id: row} of the personal skills. Plugin ones do not travel in the repo:
    comparing them would mark every one as 'local only' and be pure noise."""
    return {s["id"].split(":", 1)[1]: s for s in srv.list_skills(claude_dir)
            if s["source"] == "personal"}


def parity(claude_dir=None, repo_config=None):
    """What is out of sync between this machine and the repo."""
    cfg = repo_config if repo_config is not None else srv.KNOWLEDGE_CONFIG
    local = _personal_skills(claude_dir)
    repo = _personal_skills(cfg / "skills")
    _, plugins = srv.plugins_to_apply(claude_dir, cfg)
    return {"local_only": sorted(set(local) - set(repo)),
            "repo_only": sorted(set(repo) - set(local)),
            "sync": sorted(set(local) & set(repo)),
            "plugins": plugins,
            "modules": srv.config_status()}


_UPDATE = {"ts": 0.0, "data": {}}
UPDATE_TTL = 300  # seconds; srv.update_status() dedupes the network fetch itself


def update_state(force=False):
    """`srv.update_status()` behind a cache, so the home can ask on every paint.
    A failure is not worth a line on screen: no upstream, no notice.

    `force` goes through both caches, this one and the fetch TTL in the server.
    Pressing `u` five minutes after a release was published used to answer
    "already on the latest version" off a ref nobody had refreshed."""
    if not force and time.monotonic() - _UPDATE["ts"] < UPDATE_TTL and _UPDATE["data"]:
        return _UPDATE["data"]
    try:
        _UPDATE["data"] = srv.update_status(force=force)
    except Exception:
        _UPDATE["data"] = {"available": 0, "linked": True, "error": "unreachable"}
    _UPDATE["ts"] = time.monotonic()
    return _UPDATE["data"]


def ago(ts):
    """A unix timestamp → 'hace 3 min', in the language the TUI is set to.

    git's own `%cr` did this and it prints in English whatever the UI is set
    to: `69 minutes ago` sitting in the middle of a Spanish home. It also
    rounds in git's own way ("2 hours ago" for anything from 1h30 to 2h29),
    which is fine for a log and vague for a line that is meant to tell you how
    stale a number is.
    """
    if not ts:
        return t("ago_never")
    secs = max(0, int(time.time() - ts))
    if secs < 60:
        return t("ago_now")
    if secs < 3600:
        return t("ago_min", n=secs // 60)
    if secs < 86400:
        return t("ago_hour", n=secs // 3600)
    return t("ago_day", n=secs // 86400)


def checked_ago():
    """How old the `↑x ↓y` above it is — which is not how old the last sync is.

    These were the same number on screen and they are not the same fact. The
    home never fetches on its own, so ahead/behind is only as fresh as the last
    `git fetch`; the sync line under it is the last commit that touched
    `knowledge/`. Pressing FETCH moves this one and cannot move that one — a
    fetch writes no commits — and that is exactly what made one number
    pretending to be both confusing.

    git stamps `.git/FETCH_HEAD` on every fetch, so the answer is on disk and
    survives the process ending.
    """
    try:
        return ago((srv.REPO_ROOT / ".git" / "FETCH_HEAD").stat().st_mtime)
    except OSError:
        return t("ago_never")


def last_sync():
    """'hace 2 días · LaptopA' — the commit says which machine it came from."""
    code, out = srv._git("log", "-1", "--format=%ct|%s", "--", "knowledge")
    if code != 0 or "|" not in out:
        return t("never_synced")
    when, _, subject = out.partition("|")
    sep = "sync from "
    machine = subject.split(sep)[-1] if sep in subject else "?"
    try:
        when = ago(float(when))
    except ValueError:
        return t("never_synced")
    return f"{when} · {machine}"


def classify(paths):
    """Git paths → what they mean: {skills, config, memories, sessions, vault}."""
    out = {"skills": [], "config": [], "memories": {}, "sessions": 0, "vault": 0,
           # what moves outside git: config files to install/export and
           # memories to land, filled in by sync_preview/sync_incoming
           "activate": 0, "pending_memories": 0}
    for raw in paths:
        parts = raw.replace("\\", "/").strip('"').split("/")
        if parts[:4] == ["knowledge", "config", "skills", "skills"] and len(parts) > 4:
            if parts[4] not in out["skills"]:
                out["skills"].append(parts[4])
        elif parts[:2] == ["knowledge", "config"] and len(parts) > 2:
            if parts[2] not in out["config"]:
                out["config"].append(parts[2])
        elif parts[:2] == ["knowledge", "memory"] and len(parts) > 2:
            out["memories"][parts[2]] = out["memories"].get(parts[2], 0) + 1
        elif parts[:2] == ["knowledge", "sessions"]:
            out["sessions"] += 1
        elif parts[:1] == ["vault"]:
            out["vault"] += 1
    return out


def commands():
    """(usage, what it does) for every `sto` command.

    The list comes from the `cli.CLI` registry and not from a copy by hand: a
    new command shows up here on its own. The **usage** comes from the `cmd_*`
    docstring when there is one (`sto search <text> — …`), because the syntax is
    never translated and that way it cannot drift. The **description** comes
    from `STRINGS`, not from the docstring; if the key is missing, it falls back
    to whatever the docstring says after the dash.
    """
    out = []
    for name, fn in cli.CLI.items():
        doc = (getattr(fn, "__doc__", "") or "").strip().splitlines()
        first = doc[0].strip() if doc else ""
        usage, _, from_doc = first.partition(" — ")
        if not usage.startswith("sto "):
            usage, from_doc = f"sto {name}", ""
        key = f"cmd_{name}"
        what = t(key)
        if what == key:                        # no translation: whatever there is
            what = from_doc.strip().rstrip(".")
        out.append((usage, what))
    return out


_SUMMARY = {"ts": 0.0, "text": ""}
