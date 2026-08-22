"""braingent-sto CLI: presentation on top of the server's data functions.

Imports `sessions_server` directly (no HTTP): the data functions are pure and
do not need the server running.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # scripts/ is not a package

import i18n  # noqa: E402
import sessions_server as srv  # noqa: E402

t = i18n.t

if sys.platform == "win32":
    os.system("")  # ponytail: turns VT on in the old conhost; no-op in WT and pwsh 7
sys.stdout.reconfigure(errors="replace")  # transcripts carry emoji, cp1252 does not

COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
DIM, BOLD, CYAN, YELLOW, RED, GREEN = "2", "1", "36", "33", "31", "32"


def c(text, code):
    """Colorize when there is a tty. Careful: pad BEFORE calling, ANSI throws
    off `:<n`."""
    return f"\033[{code}m{text}\033[0m" if COLOR else str(text)


CACHE = srv.REPO_ROOT / ".sto-cache" / "sessions.json"
CACHE_VERSION = 1


def _load_cache(path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d.get("entries", {}) if d.get("version") == CACHE_VERSION else {}


def _save_cache(entries, path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": CACHE_VERSION, "entries": entries}),
                        encoding="utf-8")
    except OSError:
        pass  # ponytail: without the cache it still works, only slower


def cached_sessions(projects_dir=None, knowledge_dir=None, cache_path=None,
                    include_agents=False):
    """(rows, prompts) for every session, reusing the mtime-keyed cache.

    rows: session_meta + `machine` (None when local) + `path`, mtime desc.
    prompts: {id: lowercased prompts}, which is what `search_sessions` needs.
    Subagent sessions (id `agent-*`) stay out unless asked for: their briefs
    are long and repeat the terms, so they score high and bury the human
    conversation in `search`.
    """
    path = cache_path or CACHE
    old = _load_cache(path)
    pd = projects_dir or srv.dx.PROJECTS_DIR
    cands = [(srv.LOCAL_MACHINE, p) for _, p in
             srv.dx.find_sessions(None, projects_dir=pd, max_sessions=srv.MAX_SESSIONS)]
    cands += srv._knowledge_sessions(knowledge_dir)

    entries, rows, prompts, seen = {}, [], {}, set()
    for machine, p in cands:
        key = str(p)
        if key in entries:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        hit = old.get(key)
        if hit and hit.get("mtime") == mtime:
            entry = hit
        else:
            meta = srv.session_meta(p)
            entry = {"mtime": mtime,
                     "machine": None if machine == srv.LOCAL_MACHINE else machine,
                     "meta": meta,
                     "prompts": srv._PROMPTS_INDEX.get(meta["id"], "")}
        entries[key] = entry
        meta = entry["meta"]
        if meta["n_prompts"] == 0 or meta["id"] in seen:
            continue  # noise: sessions where nothing was asked, or a duplicate
        if not include_agents and meta["id"].startswith("agent-"):
            continue
        seen.add(meta["id"])
        rows.append(dict(meta, machine=entry["machine"], path=key))
        prompts[meta["id"]] = entry["prompts"]

    if entries != old:
        _save_cache(entries, path)
    srv._PROMPTS_INDEX.update(prompts)
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:srv.MAX_SESSIONS], prompts


def _day(mtime):
    return time.strftime("%Y-%m-%d", time.localtime(mtime))


def _pad(text, width, code):
    """Colorize after padding: ANSI does not count as width."""
    return c(text, code) + " " * max(1, width - len(text))


def n_sessions(n):
    """`1 session` / `4 sessions`. A `session(s)` on screen reads as anything
    but tidy, and it is only two keys."""
    return t("cli_1_session") if n == 1 else t("cli_n_sessions", n=n)


def n_memories(n):
    return t("cli_1_memory") if n == 1 else t("cli_n_memories", n=n)


def cmd_sessions(*args):
    """sto sessions [<project>]"""
    rows, _ = cached_sessions()
    if not rows:
        return {"error": t("cli_no_sessions")}
    if args:
        proj = " ".join(args)
        mine = [r for r in rows if r["project"] == proj]
        if not mine:
            return {"error": t("cli_unknown_project", proj=proj)}
        out = [f"{c(proj, BOLD)} · {n_sessions(len(mine))}"]
        out += [f"  {_pad(r['id'][:8], 10, CYAN)}{_day(r['mtime'])}  "
                f"{r['n_prompts']:>3}p {r['n_tools']:>4}t  {r['title'][:70]}"
                for r in mine]
        return {"message": "\n".join(out)}

    projs = {}
    for r in rows:
        p = projs.setdefault(r["project"], {"n": 0, "mtime": 0.0, "machines": set()})
        p["n"] += 1
        p["mtime"] = max(p["mtime"], r["mtime"])
        p["machines"].add(r["machine"] or srv.LOCAL_MACHINE)
    lines = [f"  {_pad(name, 36, BOLD)}"
             f"{n_sessions(d['n']):<18}"
             f"{_day(d['mtime'])}  {c(', '.join(sorted(d['machines'])), DIM)}"
             for name, d in sorted(projs.items(), key=lambda kv: -kv[1]["mtime"])]
    return {"message": "\n".join(lines)}


def resolve_id(prefix, rows):
    """(row, error) — a session id prefix down to a single row."""
    hits = [r for r in rows if r["id"].startswith(prefix)]
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, t("cli_no_session", id=prefix)
    cand = "\n".join(f"  {h['id'][:12]}  {h['title'][:60]}" for h in hits[:10])
    return None, t("cli_ambiguous", q=prefix) + "\n" + cand


def page(text):
    """Stdlib pager: `more` on Windows, $PAGER/less on Unix, plain without a tty.

    ponytail: `pydoc` is imported here and not at the top — it drags `inspect`
    behind it and costs ~90 ms of import on every `sto` command, while only
    `sto show`/`sto skills <id>` ever page anything.
    """
    import pydoc
    enc = sys.stdout.encoding or "utf-8"
    pydoc.pager(text.encode(enc, "replace").decode(enc, "replace"))


_ROLE = {"user": ("cli_you", CYAN), "assistant": ("cli_claude", GREEN),
         "error": ("cli_error", RED)}


def timeline_lines(row):
    """One session's transcript, line by line. Source for `show` and the TUI."""
    tl = srv.session_timeline(Path(row["path"]))
    out = [f"{c(row['project'], BOLD)} · {row['id']} · {_day(row['mtime'])}"]
    for it in tl["timeline"]:
        if it["role"] == "tool":
            out.append(c(f"  [{it['tool']}] {it.get('detail', '')}", DIM))
        elif it["role"] == "image":
            out.append(c("  " + t("cli_image"), DIM))
        else:
            tag, code = _ROLE[it["role"]]
            out.append(f"\n{c(t(tag), code)}\n{it['text']}")
    return out


def cmd_show(sid=""):
    """sto show <id> — one transcript, through the pager."""
    if not sid:
        return {"error": t("cli_use_show")}
    rows, _ = cached_sessions()
    row, err = resolve_id(sid, rows)
    if err:
        return {"error": err}
    lines = timeline_lines(row)
    page("\n".join(lines))
    return {"message": t("cli_blocks", id=row["id"][:8], n=len(lines) - 1)}


SNIPPET_PAD = 60
SEARCH_SHOWN = 10


def snippet(row, terms):
    """The slice of the first prompt containing one of `terms`, highlighted.

    Terms are tried in order and the first one that shows up in any prompt
    wins; if none does (say, a quoted phrase that only matched on a single
    word), it falls back to the title. It re-parses the .jsonl: the search
    index is lowercased and no good for display. Only called for the rows that
    actually get printed.
    """
    try:
        with open(row["path"], encoding="utf-8", errors="replace") as fh:
            prompts = srv.dx.parse_lines(fh)["prompts"]
    except OSError:
        prompts = []
    for term in terms:
        low = term.lower()
        for p in prompts:
            i = p.lower().find(low)
            if i < 0:
                continue
            a, b = max(0, i - SNIPPET_PAD), i + len(term) + SNIPPET_PAD
            match = p[i:i + len(term)]
            frag = p[a:b].replace("\n", " ")
            frag = frag.replace(match, c(match, YELLOW), 1)
            return ("…" if a else "") + frag + ("…" if b < len(p) else "")
    return row["title"][:120]


def cmd_search(*terms):
    """sto search <text> — search across the sessions."""
    q = " ".join(terms).strip()
    if not q:
        return {"error": t("cli_use_search")}
    rows, _ = cached_sessions()
    hits = srv.search_sessions(q, rows=rows, limit=len(rows))
    if not hits:
        return {"message": t("cli_no_hits", q=q)}
    words = q.split()
    out = []
    for r in hits[:SEARCH_SHOWN]:
        out.append(f"  {_pad(r['id'][:8], 10, CYAN)}{_pad(r['project'], 24, BOLD)}"
                   f"{_day(r['mtime'])}")
        out.append(f"      {snippet(r, words)}")
    if len(hits) > SEARCH_SHOWN:
        out.append(c("  " + t("cli_more_hits", n=len(hits) - SEARCH_SHOWN), DIM))
    return {"message": "\n".join(out)}


def cmd_skills(*args):
    """sto skills [<id>] — the list, or one SKILL.md through the pager."""
    if not args:
        rows = sorted(srv.list_skills(), key=lambda r: r["id"])
        if not rows:
            return {"message": t("cli_no_skills")}
        return {"message": "\n".join(
            f"  {_pad(r['id'], 32, CYAN)}{_pad(r['name'], 22, BOLD)}{r['description'][:60]}"
            for r in rows)}
    sid = args[0]
    sk = srv.get_skill(sid)
    if sk is None:
        near = [r["id"] for r in srv.list_skills() if sid.lower() in r["id"].lower()]
        if near:
            return {"error": t("cli_did_you_mean", id=sid) + "\n"
                             + "\n".join("  " + n for n in near[:10])}
        return {"error": t("cli_no_skill", id=sid)}
    page(f"{c(sk['name'], BOLD)} · {sk['source']}\n{c(sk['path'], DIM)}\n\n{sk['body']}")
    return {"message": f"— {sk['id']}"}


def cmd_usage():
    """sto usage — plan limits and the last few days of spend."""
    u = srv.usage_snapshot()
    out = []
    for lim in u.get("limits") or []:
        pct = lim.get("percent") or 0
        code = RED if pct >= 80 else (YELLOW if pct >= 50 else GREEN)
        label = lim.get("label") or lim.get("kind") or "?"
        reset = (lim.get("resetsAt") or "")[:16].replace("T", " ")
        out.append(f"  {label.ljust(16)}{c(f'{pct}%'.rjust(5), code)}"
                   f"   {c(t('cli_reset') + ' ' + reset, DIM)}")
    daily = u.get("daily") or []
    if daily:
        out.append("")
        for d in daily[-7:]:
            tok = (d.get("inputTokens") or 0) + (d.get("outputTokens") or 0)
            cost = d.get("totalCost")
            line = f"  {str(d.get('date', '?')).ljust(12)}{tok:>12,} tok"
            if isinstance(cost, (int, float)):
                line += f"   US$ {cost:.2f}"
            out.append(line)
    if not out:
        return {"error": t("cli_no_usage", e=u.get("error") or "no limits, no ccusage")}
    if u.get("error"):
        out.append(c("  " + t("cli_usage_partial", e=u["error"]), DIM))
    return {"message": "\n".join(out)}


def cmd_machines():
    """sto machines — the machines feeding the repo."""
    ms = srv.list_machines()
    lines = [f"  {_pad(name, 22, BOLD)}{d['type'].ljust(10)}"
             f"{c('(' + t('this_one') + ')', GREEN) if d['local'] else ''}".rstrip()
             for name, d in sorted(ms.items())]
    return {"message": "\n".join(lines)}


def _labels(g):
    return {n.get("id"): n.get("label") or n.get("id") for n in g.get("nodes", [])}


def graph_stats(g):
    """Graph summary: size, orphans and the most connected nodes."""
    deg = Counter()
    for l in g.get("links", []):
        deg[l.get("source")] += 1
        deg[l.get("target")] += 1
    labels = _labels(g)
    return {"nodes": len(g.get("nodes", [])),
            "links": len(g.get("links", [])),
            "orphans": sum(1 for n in g.get("nodes", []) if not deg.get(n.get("id"))),
            "top": [(labels.get(i, i), d) for i, d in deg.most_common(10)]}


def graph_neighbors(g, query):
    """(node, error) — incoming and outgoing neighbours of the matching node."""
    q = query.lower()
    hits = [n for n in g.get("nodes", [])
            if str(n.get("id", "")).lower().startswith(q)
            or str(n.get("label", "")).lower().startswith(q)]
    if not hits:
        return None, t("cli_graph_none", q=query)
    if len(hits) > 1:
        exact = [n for n in hits if q in (str(n.get("id", "")).lower(),
                                          str(n.get("label", "")).lower())]
        if len(exact) != 1:
            cand = "\n".join("  " + str(n.get("label") or n.get("id")) for n in hits[:10])
            return None, t("cli_ambiguous", q=query) + "\n" + cand
        hits = exact
    node = hits[0]
    nid, labels = node.get("id"), _labels(g)
    out = [(labels.get(l.get("target"), l.get("target")), l.get("relation", ""))
           for l in g.get("links", []) if l.get("source") == nid]
    inc = [(labels.get(l.get("source"), l.get("source")), l.get("relation", ""))
           for l in g.get("links", []) if l.get("target") == nid]
    return {"label": labels.get(nid, nid), "out": out, "in": inc}, None


# ── the graph window ──

GRAPH_HTML = srv.REPO_ROOT / "graphify-out" / "graph.html"

# Chromium in `--app=<url>` mode: a window with no tabs, no address bar and no
# menu — it looks and behaves like a standalone app. It is not a "native"
# window in the strict sense (the engine is still the browser), but it is the
# only thing that gives a chrome-less window without adding a dependency:
# graph.html already exists and renders the graph with WebGL, and
# reimplementing it over a tkinter canvas would be a lot of code for a worse
# result.
# ponytail: the day this must not depend on an installed browser, that is
# pywebview (a dependency) — not worth it until it hurts.
_APP_BROWSERS = ("msedge", "chrome", "brave", "chromium")
_APP_PATHS = (
    ("ProgramFiles(x86)", r"Microsoft\Edge\Application\msedge.exe"),
    ("ProgramFiles", r"Microsoft\Edge\Application\msedge.exe"),
    ("ProgramFiles", r"Google\Chrome\Application\chrome.exe"),
    ("ProgramFiles(x86)", r"Google\Chrome\Application\chrome.exe"),
    ("ProgramFiles", r"BraveSoftware\Brave-Browser\Application\brave.exe"),
    ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe"),
)


def find_app_browser():
    """A Chromium to open in app mode, or None.

    Edge and Chrome are usually not on PATH on Windows, so after `which` you
    have to look where the system installs them.
    """
    for name in _APP_BROWSERS:
        exe = shutil.which(name)
        if exe:
            return exe
    for var, rest in _APP_PATHS:
        base = os.environ.get(var)
        if base:
            p = Path(base) / rest
            if p.is_file():
                return str(p)
    return None


def open_window(path, launcher=None, fallback=None):
    """Open a local .html in a chrome-less window.

    `launcher`/`fallback` exist for the tests: they are the real
    `subprocess.Popen` and `webbrowser.open`.
    """
    url = Path(path).resolve().as_uri()
    exe = find_app_browser()
    if exe:
        try:
            (launcher or subprocess.Popen)(
                [exe, f"--app={url}", "--window-size=1400,900"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"message": t("cli_graph_window", app=Path(exe).stem)}
        except OSError as e:
            return {"error": t("cli_graph_failed", e=e)}
    (fallback or webbrowser.open)(url)
    return {"message": t("cli_graph_browser")}


def open_graph(launcher=None, fallback=None):
    """`sto graph --open` — the repo graph (graphify) in a window."""
    if not GRAPH_HTML.is_file():
        return {"error": t("cli_graph_missing")}
    return open_window(GRAPH_HTML, launcher, fallback)


# The memory graph is not generated by graphify: it comes from
# `knowledge/memory`, the very thing the push uploaded, so it shows the
# memories of every machine and every session. The template is filled in and
# saved to the local cache (gitignored): it is an artifact, not knowledge.
MEMORY_TEMPLATE = Path(__file__).parent / "memory_graph.html"
MEMORY_HTML = srv.REPO_ROOT / ".sto-cache" / "memory-graph.html"


PLACEHOLDER = "__" + "DATA" + "__"   # split so this file is not a second copy


def _embeddable(data: str) -> str:
    """JSON safe to drop inside a <script> block.

    Every `<` becomes the JSON escape `<`, which JS reads straight back as
    `<`. Escaping only `</script>` is not enough: an inner `<script` puts the
    HTML tokenizer into double-escaped state, and then the *real* `</script>`
    stops closing the tag — a memory that quoted `<script>` took the whole
    window down with `Unexpected identifier` the moment bodies started
    travelling. U+2028/2029 are the other classic: legal inside a JSON string,
    a line break to a JS parser.
    """
    return (data.replace("<", r"\u003c")
                .replace("\u2028", r"\u2028").replace("\u2029", r"\u2029"))


# The window is the one surface outside the TUI painted in the accent, and it
# is HTML: the six terminal colours need a hex each. Same order as ui.ACCENTS.
ACCENT_HEX = {"36": "#2bd6c4", "32": "#4cd964", "35": "#c08cf5",
              "34": "#5aa9f8", "33": "#e3c05a", "31": "#f2705f"}
TEMPLATE_ACCENT = "--accent:#2bd6c4"


def _accent_hex():
    """The accent picked in `sto ui`, as a hex. Unknown value → the default."""
    return ACCENT_HEX.get(i18n.get_prefs().get("accent"), ACCENT_HEX["36"])


def build_memory_graph(dest=None):
    """Fill the template with the graph as of now and return the file."""
    dest = Path(dest) if dest else MEMORY_HTML
    data = _embeddable(json.dumps(srv.memory_graph(bodies=True), ensure_ascii=False))
    tpl = MEMORY_TEMPLATE.read_text(encoding="utf-8")
    tpl = tpl.replace(TEMPLATE_ACCENT, f"--accent:{_accent_hex()}")
    n = tpl.count(PLACEHOLDER)
    if n != 1:
        raise OSError(f"the template has {n} copies of the data placeholder, expected 1")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(tpl.replace(PLACEHOLDER, data), encoding="utf-8")
    return dest


def open_memory_graph(launcher=None, fallback=None, dest=None):
    """`sto graph --memory` — the repo's memories in a window."""
    try:
        file = build_memory_graph(dest)
    except OSError as e:
        return {"error": t("cli_graph_build_failed", e=e)}
    return open_window(file, launcher, fallback)


def cmd_graph(*args):
    """sto graph [--open|--memory|<note>] — summary, neighbours, or a window."""
    if args and args[0] in ("--memory", "-m", "--memorias"):
        return open_memory_graph()
    if args and args[0] in ("--open", "-o"):
        return open_graph()
    try:
        g = json.loads(srv.GRAPH_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": t("cli_graph_missing")}
    if not args:
        s = graph_stats(g)
        out = ["  " + t("cli_graph_summary", n=s["nodes"], l=s["links"], o=s["orphans"]),
               "", c("  " + t("cli_graph_top"), DIM)]
        out += [f"  {_pad(label, 40, BOLD)}{d:>4}" for label, d in s["top"]]
        return {"message": "\n".join(out)}
    node, err = graph_neighbors(g, " ".join(args))
    if err:
        return {"error": err}
    out = [c(node["label"], BOLD)]
    out += [f"  -> {_pad(label, 40, CYAN)}{c(rel, DIM)}" for label, rel in node["out"]]
    out += [f"  <- {_pad(label, 40, YELLOW)}{c(rel, DIM)}" for label, rel in node["in"]]
    if not node["out"] and not node["in"]:
        out.append(c("  " + t("cli_graph_orphan"), DIM))
    return {"message": "\n".join(out)}


def cmd_status(*a):
    """sto status — where the sync stands, in two lines and without JSON."""
    st = srv.sync_status()
    if not st["remote"]:
        return {"error": t("cli_status_remote")}
    dirty = t("cli_status_dirty") if st["dirty"] else t("cli_status_clean")
    ahead = f"↑{st['ahead']} {t('cli_status_ahead')}"
    behind = f"↓{st['behind']} {t('cli_status_behind')}"
    out = [f"  {_pad(st['branch'] or '?', 16, BOLD)}{c(st['remote'], DIM)}",
           f"  {_pad(st['machine'], 16, DIM)}{_pad(ahead, 18, CYAN)}"
           f"{_pad(behind, 18, YELLOW)}{c(dirty, DIM)}"]
    if st["fetchError"]:
        out.append(c("  " + t("cli_fetch_failed", e=st["fetchError"]), YELLOW))
    return {"message": "\n".join(out)}


def cmd_update(*args):
    """sto update [--apply|--link] — updates to the OS itself, from upstream."""
    if args and args[0] in ("--link", "-l"):
        return srv.update_link()
    if args and args[0] in ("--apply", "-y", "--yes"):
        return srv.update_apply()
    st = srv.update_status(force=True)
    if st["error"]:
        return {"error": t("cli_update_failed", e=st["error"])}
    if not st["linked"]:
        return {"message": "\n".join(
            ["  " + c(t("cli_update_unlinked"), YELLOW),
             "  " + c(t("cli_update_link_hint"), DIM)])}
    if not st["available"]:
        return {"message": "  " + t("cli_update_none")}
    out = ["  " + c(t("cli_update_available", n=st["available"]), CYAN)]
    out += [c("    " + l, DIM) for l in st["log"][:10]]
    out.append("  " + c(t("cli_update_hint"), DIM))
    return {"message": "\n".join(out)}


def cmd_badge(*args):
    """sto badge [--install|--off] — the STO badge in Claude Code's status line."""
    if args and args[0] in ("--install", "--on"):
        res = srv.set_badge(True)
        return res if res.get("error") else {"message": "  " + t("cli_badge_installed")}
    if args and args[0] in ("--off", "--remove"):
        res = srv.set_badge(False)
        return res if res.get("error") else {"message": "  " + t("cli_badge_removed")}
    st = srv.badge_status()
    import statusline
    out = ["  " + statusline.badge()]
    if st["on"]:
        out.append("  " + c(t("cli_badge_active"), GREEN))
        if st["other"]:
            out.append("  " + c(t("cli_badge_chained", cmd=st["other"][:70]), DIM))
    else:
        out.append("  " + c(t("cli_badge_hint"), DIM))
        if st["other"]:
            out.append("  " + c(t("cli_badge_chained", cmd=st["other"][:70]), DIM))
    return {"message": "\n".join(out)}


def cmd_config(*a):
    """sto config — which ~/.claude modules travel through the repo."""
    on = set(srv.get_sync_prefs())
    lines = []
    for mod in srv.CONFIG_MODULES:
        mark = c("[x]", CYAN) if mod in on else c("[ ]", DIM)
        state = t("cli_modules_on") if mod in on else t("cli_modules_off")
        lines.append(f"  {mark} {_pad(mod, 20, BOLD)}{c(state, DIM)}")
    return {"message": "\n".join(lines)}


def cmd_forget(*args):
    """sto forget <skill|config|plugin|memory>:<name> [--apply]

    The repo half of a deletion. chezmoi deprecated its single `remove` in
    favour of `forget` (source state) and `destroy` (source state + disk); one
    verb called "delete" never says which of the two it did.
    """
    target = next((a for a in args if not a.startswith("--")), "")
    if not target:
        return {"error": t("cli_forget_usage")}
    seco = "--apply" not in args
    paths, err = srv.forget(target, apply=not seco)
    if err:
        return {"error": err}
    out = ["  " + c(p, DIM) for p in paths[:20]]
    if len(paths) > 20:
        out.append("  " + c(f"… +{len(paths) - 20}", DIM))
    out.append("  " + c(t("cli_forget_hint") if seco
                        else t("cli_forget_done", n=len(paths)), CYAN))
    out.append("  " + c(t("cli_forget_keeps_local"), DIM))
    return {"message": "\n".join(out)}


def cmd_memory(*args):
    """sto memory [<project> | show <project>/<slug> | search <text> | sync | repair]"""
    sub = args[0] if args else ""
    if sub == "repair":
        seco = "--apply" not in args
        moves = srv.repair_memory(dry=seco)
        if not moves:
            return {"message": "  " + t("cli_mem_repair_none")}
        out = [f"  {_pad(m['from'][:44], 46, DIM)}-> {_pad(m['to'], 26, CYAN)}"
               f"{n_memories(m['files'])}" for m in moves]
        out.append("  " + c(t("cli_mem_repair_hint") if seco
                            else t("cli_mem_repaired", n=len(moves)), DIM))
        return {"message": "\n".join(out)}
    if sub == "sync":
        n = srv.export_memory() + srv.import_memory()
        for dirs in srv._memory_dirs().values():
            for d in dirs:
                srv.rebuild_index(d)
        return {"message": t("cli_mem_synced", n=n)}
    data = srv.list_memory()
    if sub == "show":
        target = args[1] if len(args) > 1 else ""
        proj, _, slug = target.partition("/")
        for p in data:
            for m in p["memories"]:
                if m["slug"] == slug and proj in (p["project"],
                                                  srv._proj_label(p["project"])):
                    f = srv.KNOWLEDGE_MEMORY / p["project"] / m["machine"] / f"{slug}.md"
                    return {"message": f.read_text(encoding="utf-8", errors="replace")}
        return {"error": t("cli_mem_missing", target=target)}
    if sub == "search":
        q = " ".join(args[1:]).lower()
        if not q:
            return {"error": t("cli_use_mem_search")}
        hits = []
        for p in data:
            for m in p["memories"]:
                f = srv.KNOWLEDGE_MEMORY / p["project"] / m["machine"] / f"{m['slug']}.md"
                if q in f.read_text(encoding="utf-8", errors="replace").lower():
                    label = srv._proj_label(p["project"]) + "/" + m["slug"]
                    hits.append(f"  {_pad(label, 52, CYAN)}"
                                f"{c(m['machine'], DIM)}")
        return {"message": "\n".join(hits) or t("cli_no_hits", q=q)}
    if sub:
        p = next((x for x in data
                  if sub in (x["project"], srv._proj_label(x["project"]))), None)
        if p is None:
            return {"error": t("cli_unknown_project", proj=sub)}
        rows = [f"  {_pad(m['slug'], 40, BOLD)}{_pad(m['type'], 12, CYAN)}"
                f"{_pad(m['machine'], 16, DIM)}{_day(m['mtime'])}"
                for m in sorted(p["memories"], key=lambda m: -m["mtime"])]
        head = f"{c(srv._proj_label(p['project']), BOLD)} · {n_memories(p['count'])}"
        return {"message": "\n".join([head] + rows)}
    rows = [f"  {_pad(srv._proj_label(p['project']), 40, BOLD)}"
            f"{n_memories(p['count']):<20}"
            f"{c(', '.join(p['machines']), DIM)}"
            for p in data]
    return {"message": "\n".join(rows) or t("cli_no_memories")}


def cmd_ui(*args):
    """`sto ui`, and `sto ui --ink` for the optional Ink flavour.

    Two front-ends over one home. The default one is `ui.py`: Python stdlib,
    always there, no runtime to install. `--ink` is a Node app under `app-tui/`
    that reads `GET /api/home` — the same numbers, laid out with a real flexbox
    instead of column arithmetic done by hand.

    It is opt-in and it stays opt-in. Without Node this says so and falls back
    rather than failing: the flavour is a preference, and the OS has to run on
    a machine that never installs one.
    """
    if not args:
        return __import__("ui").run()   # ponytail: lazy — ui imports cli
    if args != ("--ink",):
        return _no_args("ui")
    node = shutil.which("node")
    if node is None:
        print(t("ink_no_node"))
        return __import__("ui").run()
    app = srv.REPO_ROOT / "app-tui"
    if not (app / "node_modules").exists():
        print(t("ink_installing"))
        if subprocess.run(["npm", "install"], cwd=app, shell=True).returncode:
            print(t("ink_install_failed"))
            return __import__("ui").run()
    # the Ink app talks HTTP, so unlike the stdlib TUI it needs the server up.
    # A daemon thread and not a subprocess: it dies with this process, and a
    # server orphaned by a crashed front-end is a port nobody can rebind.
    _serve_in_background()
    subprocess.run(["npx", "tsx", "src/app.jsx"], cwd=app, shell=True)
    return {"message": ""}


def _serve_in_background():
    """Start the API server here unless something already answers on the port."""
    import socket
    import threading
    port = int(os.environ.get("STO_SESSIONS_PORT", "8765"))
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return                      # somebody is already serving it
    httpd = srv.ThreadingHTTPServer(("127.0.0.1", port), srv.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def _no_args(cmd):
    """Force the TypeError that main() already turns into 'invalid arguments'."""
    raise TypeError(f"{cmd} takes no arguments")


CLI = {
    "push": srv.sync_push,
    "pull": srv.sync_pull,
    "status": cmd_status,
    "config": cmd_config,
    "update": cmd_update,
    "badge": cmd_badge,
    "memory": cmd_memory,
    "forget": cmd_forget,
    "sessions": cmd_sessions,
    "show": cmd_show,
    "search": cmd_search,
    "skills": cmd_skills,
    "usage": cmd_usage,
    "machines": cmd_machines,
    "graph": cmd_graph,
    "ui": cmd_ui,
}


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd not in CLI:
        return {"error": t("cli_commands", names=", ".join(CLI))}
    try:
        return CLI[cmd](*argv[1:])
    except TypeError:
        return {"error": t("cli_bad_args", cmd=cmd)}


if __name__ == "__main__":
    res = main(sys.argv[1:])
    # every command returns {message|error}: never dump a raw dict
    print(res.get("error") or res.get("message") or "")
    sys.exit(1 if res.get("error") else 0)
