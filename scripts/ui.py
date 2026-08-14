"""The OS TUI: one screen over the data functions of cli.py and the server.

`handle()` and `draw()` are almost pure (state + key → state; state → lines) —
with deliberate, bounded exceptions, so not truly pure: `handle` does real I/O
when filtering (`_handle_search` → `reload_tab` → loader), when opening a
detail (the tab's opener), when activating a config row (`↵` writes prefs to
disk) and on `p`/`l` (`sync_stage`, `sync_incoming` — export to disk and
`git add`; confirming starts a thread with `sync_push`/`sync_pull` and the loop
draws it moving); `draw` does real I/O through `status_summary()` in the header
(subprocess + request), amortised by a 30s cache. That is enough for the tests
to need neither a terminal nor a pty: they chain `handle`/`draw` while seeding
or replacing those functions. `run()` is the only thing that also touches the
terminal itself (alt screen, size, keyboard, cursor).
"""
import json
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # scripts/ is not a package

import cli  # noqa: E402
import i18n  # noqa: E402
import sessions_server as srv  # noqa: E402

try:
    import msvcrt  # ponytail: Windows only; both machines of this OS are
except ImportError:
    msvcrt = None

# 10 ms: Windows key repeat sends ~31 keys per second (one every 32 ms). With
# the old 50 ms the loop slept longer than the next key took to arrive, so every
# key waited up to half a frame extra and scrolling felt heavy. Sleeping 10 ms
# costs nothing because the loop only repaints when something changed (see
# `run()`), not on every turn.
POLL = 0.01


# ── TUI preferences ──

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


def load_prefs():
    """Read the prefs from disk. A value we do not know falls back to the
    default instead of breaking: anyone can edit the file by hand."""
    global ACCENT
    code = i18n.get_prefs().get("accent")
    ACCENT = code if any(c == code for _, c in ACCENTS) else "36"
    return ACCENT, i18n.load()


load_prefs()


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


def fit(line, w):
    """Clip to w visible columns and pad with spaces. ANSI does not count."""
    out, vis, i = [], 0, 0
    while i < len(line) and vis < w:
        if line[i] == "\033":
            j = line.find("m", i)
            if j < 0:
                break
            out.append(line[i:j + 1])
            i = j + 1
            continue
        out.append(line[i])
        vis += 1
        i += 1
    tail = "\033[0m" if "\033" in line else ""
    return "".join(out) + tail + " " * max(0, w - vis)


def section(title, w):
    """── Title ────────────── across the panel.

    Title in bold and the rule in dim: that is what makes a long panel read as
    sections instead of a list of loose lines.
    """
    used = 3 + len(title) + 1
    return (cli.c("──", cli.DIM) + " " + cli.c(title, cli.BOLD) + " "
            + cli.c("─" * max(0, w - used - 1), cli.DIM))


# ── banner ──

# Block Elements (U+2580–259F) on purpose: they are fixed width in Unicode. An
# "ambiguous-width" character (▰, ▱, almost any emoji) throws the block off,
# because fit() counts code points, not columns.
_GLYPHS = {"S": ("▄████▄", "██  ▀▀", "▀████▄", "▄▄  ██", "▀████▀"),
           "T": ("██████", "  ██  ", "  ██  ", "  ██  ", "  ██  "),
           "O": ("▄████▄", "██  ██", "██  ██", "██  ██", "▀████▀"),
           " ": ("  ",) * 5}
WORDMARK = [" ".join(_GLYPHS[ch][r] for ch in "STO OS") for r in range(5)]
WORDMARK_W = len(WORDMARK[0]) + 2


def banner(w):
    """The big wordmark, or a single line when the terminal is too narrow."""
    if w < WORDMARK_W + 2:
        return ["", cli.c("  ███ STO OS ███", ACCENT)]
    return [""] + [cli.c("  " + line, ACCENT) for line in WORDMARK]


def bar(pct, width=18):
    """███░░░ — usage bar. `pct` can come in as None when there is no data."""
    n = max(0, min(width, round((pct or 0) * width / 100)))
    return cli.c("█" * n, ACCENT) + cli.c("░" * (width - n), cli.DIM)


def _reset_at(iso):
    """'2026-08-14T18:00:00Z' → 'resets 15:00' in local time. Without data, ''.

    The quota endpoint returns UTC; painting that hour as-is claims the quota
    resets three hours later than it actually does.
    """
    if not isinstance(iso, str) or "T" not in iso:
        return ""              # a bare date has no reset time
    try:
        local = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    return t("resets_at", h=f"{local:%H:%M}")


# ── sync buttons ──

BUTTONS_W = 52   # below this the two boxes do not fit side by side


def button(key, label, n, on):
    """A 3-line box. Accent when enabled, dim when there is nothing to do —
    the colour is what says whether pressing the key does anything."""
    inner = f"  [{key}]  {label} {n:>3}  "
    code = ACCENT if on else cli.DIM
    return [cli.c("┌" + "─" * len(inner) + "┐", code),
            cli.c("│" + inner + "│", code),
            cli.c("└" + "─" * len(inner) + "┘", code)]


def sync_buttons(sy, w=100, up=0, down=0):
    """The PUSH/PULL strip.

    The number is **files**, not commits: "↑ PUSH 19" with 19 = commits told
    nobody anything. What travels are knowledge/vault files, and the breakdown
    above says what kind they are.
    """
    push_on = up > 0 or sy["ahead"] > 0 or sy["dirty"]
    pull_on = down > 0 or sy["behind"] > 0
    if w < BUTTONS_W:
        return [cli.c(f"  [p] ↑ PUSH {up}", ACCENT if push_on else cli.DIM)
                + cli.c(f"   [l] ↓ PULL {down}", ACCENT if pull_on else cli.DIM)]
    return ["  " + a + "   " + b
            for a, b in zip(button("p", "↑ PUSH", up, push_on),
                            button("l", "↓ PULL", down, pull_on))]


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
    return classify(sorted(set(up))), classify(sorted(set(down)))


def count_items(data):
    return (data["sessions"] + data["vault"] + len(data["skills"])
            + len(data["config"]) + sum(data["memories"].values()))


def preview_parts(data):
    """['12 sessions', '4 memories', '3 skills'] — empty when nothing travels."""
    out = []
    if data["sessions"]:
        out.append(f"{data['sessions']} {t('n_sessions')}")
    memories = sum(data["memories"].values())
    if memories:
        out.append(f"{memories} {t('n_memories')}")
    if data["skills"]:
        out.append(f"{len(data['skills'])} skills")
    if data["config"]:
        out.append(f"{len(data['config'])} config")
    if data["vault"]:
        out.append(f"{data['vault']} vault")
    return out


# ── home tab ──

def counters():
    """The big numbers on the home: sessions, projects, memories, skills…"""
    rows, _ = cli.cached_sessions()
    return [("n_sessions", len(rows)),
            ("n_projects", len({r["project"] for r in rows})),
            ("n_memories", knowledge_counts()["memories"]),
            ("n_skills", len(_personal_skills(None))),
            ("n_machines", len(srv.list_machines()))]


def wrap_items(items, w, indent="  ", sep="   "):
    """Fit the items into as many `w`-wide lines as it takes.

    The items already come coloured, so width is measured with strip_ansi and
    not len(). `indent` can be a label ("Machines: "): it goes on the first
    line only, and the rest align with spaces — repeating it on every line
    would make it look like one more item of the list.
    """
    cont = " " * len(strip_ansi(indent))
    lines, cur = [], []
    for it in items:
        pref = indent if not lines else cont
        if cur and len(strip_ansi(pref + sep.join(cur + [it]))) > w:
            lines.append(pref + sep.join(cur))
            cur = [it]
        else:
            cur.append(it)
    if cur:
        lines.append((indent if not lines else cont) + sep.join(cur))
    return lines


NARROW = 60   # below this, everything that is explanation and not data drops


def _drift(icon, color, name, text, w):
    """One line of the parity diff. When narrow, the name and the arrow stay:
    the text explaining it is what is expendable, not the what."""
    if w < NARROW:
        return f"    {cli.c(icon, color)} {cli.c(name[:max(1, w - 7)], color)}"
    return f"    {cli.c(icon, color)} {cli._pad(name, 28, color)}{text}"


def _diff_pair(local, repo):
    """'148 local · 149 in repo', the bigger side in yellow when they differ."""
    left, right = f"{local:>3}", f"{repo:>3}"
    if local != repo:
        left = cli.c(left, cli.YELLOW) if local > repo else left
        right = cli.c(right, cli.YELLOW) if repo > local else right
    return f"{left} {t('local')} · {right} {t('in_repo')}"


def _txt(line):
    """A panel row: you look at it, you do nothing with it."""
    return {"kind": "text", "text": line}


MODULE_LISTABLE = {"skills", "plugins"}   # the only ones with a real delete API


def module_items(mod, claude_dir=None):
    """What a config module holds on this machine.

    `skills` and `plugins` come from the server APIs and can be deleted. The
    rest are loose files under `~/.claude`: they are listed so you can look at
    them, but deleting them has no safe operation on the other side, so no.
    """
    cd = claude_dir or srv.CLAUDE_DIR
    if mod == "skills":
        return [{"kind": "item", "what": "skill", "id": row["id"], "label": name,
                 "desc": row.get("description", "")}
                for name, row in sorted(_personal_skills(claude_dir).items())]
    if mod == "plugins":
        _, installed = srv._local_plugins(claude_dir)
        return [{"kind": "item", "what": "plugin", "id": p, "label": p, "desc": ""}
                for p in installed]
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


def module_lines(st):
    """The inside-a-module view: title, warning and the list of items."""
    w = max(24, st.get("w", 100) - 2)
    mod = st["mod"]
    items = module_items(mod)
    out = [_txt(""), _txt(section(t("sec_contents", mod=mod, n=len(items)), w))]
    if mod not in MODULE_LISTABLE:
        out.append(_txt(cli.c("  " + t("not_deletable", id=mod), cli.DIM)))
    out.append(_txt(""))
    if not items:
        out.append(_txt(cli.c("  " + t("empty"), cli.DIM)))
    return out + items


def fmt_home(r, w=100):
    if not isinstance(r, dict):
        return r                     # old panel: a line already painted
    if r["kind"] == "module":
        tail = "" if r["enabled"] else cli.c("   " + t("module_off"), cli.DIM)
        return (f" {cli.c('›', ACCENT)} {cli._pad(r['id'], 14, ACCENT)}"
                f"{_diff_pair(r['local'], r['repo'])}{tail}")
    if r["kind"] == "item":
        # w - 40: 2 for the cursor, 3 of indent, 30 for the name, plus the
        # scrollbar's air. Without this the description rides on top of it.
        cut = max(0, w - 40)
        desc = cli.c("   " + " ".join(r["desc"].split())[:cut], cli.DIM) if r["desc"] else ""
        return f"   {cli._pad(r['label'], 30, cli.BOLD)}{desc}"
    return r["text"]


def home_lines(st):
    """The dashboard: banner, usage, counters, sync and config parity — or, if
    you entered a module with `↵`, what that module holds on this machine.

    It also leaves the PUSH/PULL button strip in `st["pinned"]`, which `draw()`
    pins to the foot of the body so it never scrolls: it is the only loader
    that writes state, and it does so because the buttons need the
    `sync_status()` this function already went to fetch.
    """
    if st.get("mod"):
        return module_lines(st)
    # -2: the scrollbar column plus its air. Building the content against the
    # bare width left it clipped right at the edge.
    w = max(24, st.get("w", 100) - 2)
    u = srv.usage_snapshot()
    sy = srv.sync_status(fetch=st.get("fetch", False))
    p = parity()
    subir, bajar = sync_preview(sy)
    st["pinned"] = sync_buttons(sy, w, count_items(subir), count_items(bajar))

    out = [_txt(l) for l in banner(w)] + [_txt("")]
    out.append(_txt(section(t("sec_usage"), w)))
    lims = u.get("limits") or []
    ancho_barra, ancho_label = (18, 16) if w >= 80 else (10, 12)
    for lim in lims:
        label = lim.get("label") or lim.get("kind") or "?"
        pct = lim.get("percent") or 0
        # the reset time is the first thing to drop: it is the least urgent bit
        cola = (f"   {cli.c(_reset_at(lim.get('resetsAt')), cli.DIM)}"
                if w >= NARROW else "")
        out.append(_txt(f"  {cli._pad(label[:ancho_label - 1], ancho_label, cli.DIM)}"
                        f"{bar(pct, ancho_barra)}  {cli.c(f'{pct:>3}%', cli.YELLOW)}{cola}"))
    if not lims:
        out.append(_txt(cli.c("  " + t("no_usage"), cli.DIM)))

    out.append(_txt(""))
    out += [_txt(l) for l in wrap_items(
        [f"{cli.c(str(n), ACCENT)} {cli.c(t(k), cli.DIM)}" for k, n in counters()], w)]
    out.append(_txt(""))
    out.append(_txt(section(t("sec_sync"), w)))
    estado = t("dirty") if sy["dirty"] else t("clean")
    out += [_txt(l) for l in wrap_items(
        [f"↑{sy['ahead']} ↓{sy['behind']}", estado, last_sync()], w, sep=" · ")]
    here = f" ({t('this_one')})"
    machines = [n + (here if d["local"] else "")
                for n, d in sorted(srv.list_machines().items())]
    out += [_txt(l) for l in wrap_items(
        machines, w, sep=" · ",
        indent="  " + cli.c(t("sec_machines") + ": ", cli.DIM))]
    # what travels each way, in plain words: the button number comes from here
    for key, data in (("to_push", subir), ("to_pull", bajar)):
        partes = preview_parts(data) or [cli.c(t("nothing"), cli.DIM)]
        out += [_txt(l) for l in wrap_items(
            partes, w, sep=" · ",
            indent="  " + cli.c(cli._pad(t(key), 14, cli.BOLD), ""))]
    out.append(_txt(""))
    out.append(_txt(section(t("sec_parity"), w)))
    out.append(_txt(cli.c("  " + t("inspect_hint"), cli.DIM)))
    for m in p["modules"]:
        out.append({"kind": "module", "id": m["id"], "local": m["localFiles"],
                    "repo": m["repoFiles"], "enabled": m["enabled"]})
    for name in p["local_only"]:
        out.append(_txt(_drift("↑", cli.YELLOW, name, t("local_only"), w)))
    for name in p["repo_only"]:
        out.append(_txt(_drift("↓", cli.GREEN, name, t("in_repo_not_installed"), w)))
    for pl in p["plugins"]:
        out.append(_txt(_drift("↓", cli.GREEN, pl, t("plugin_missing"), w)))
    if not (p["local_only"] or p["repo_only"] or p["plugins"]):
        out.append(_txt(cli.c("    " + t("all_synced"), cli.DIM)))
    return out


# ── grouping by project ──

SINGULAR = {"n_sessions": "one_session", "n_memories": "one_memory"}
PROJ_CAP = 32   # a longer name pushes the counter column out of place


def group_by_project(rows, noun):
    """Flat rows → one summary row per project, most recent first."""
    groups = {}
    for r in rows:
        g = groups.setdefault(r["project"],
                              {"kind": "project", "project": r["project"],
                               "n": 0, "mtime": 0.0, "noun": noun})
        g["n"] += 1
        g["mtime"] = max(g["mtime"], r["mtime"])
    return sorted(groups.values(), key=lambda g: g["mtime"], reverse=True)


def fmt_project(r):
    key = SINGULAR.get(r["noun"], r["noun"]) if r["n"] == 1 else r["noun"]
    return (cli._pad(r["project"][:PROJ_CAP], PROJ_CAP + 2, cli.BOLD)
            + cli.c(f"{r['n']:>4} {t(key)}", ACCENT)
            + "\n" + cli.c("  " + t("last_activity", d=cli._day(r["mtime"])), cli.DIM))


def _drill(st, rows, noun):
    """Flat when there is a filter, when `flat` is on, or when you already
    entered a project; otherwise, the list of projects."""
    if st["q"].strip() or st["flat"]:
        return rows
    if st["proj"]:
        return [r for r in rows if r["project"] == st["proj"]]
    return group_by_project(rows, noun)


# ── sessions tab ──

def load_sessions(st):
    rows, _ = cli.cached_sessions(include_agents=st["agents"])
    if st["q"].strip():
        # the prompt index is already in memory: filtering never touches disk
        rows = srv.search_sessions(st["q"], rows=rows, limit=len(rows))
    return _drill(st, [dict(r, kind="session") for r in rows], "n_sessions")


def fmt_session(r, w=100):
    """Two lines: the data row on top, the full title below."""
    if r["kind"] == "project":
        return fmt_project(r)
    head = (f"{cli._pad(cli._day(r['mtime']), 14, cli.BOLD)}"
            f"{r['n_prompts']:>4}p {r['n_tools']:>5}t   "
            f"{cli.c(r['id'][:8], cli.DIM)}")
    # the title comes from the first prompt and can carry newlines inside:
    # unflattened, the row would take more than ROW_H lines and the scroll would lie
    return head + "\n" + cli.c("  " + " ".join(r["title"].split()), cli.DIM)


def detail_session(row):
    return cli.timeline_lines(row)


# ── memory tab ──

def load_memory(st):
    """Every project's memories, flattened and sorted by date."""
    rows = []
    for p in srv.list_memory():
        for m in p["memories"]:
            rows.append(dict(m, project=p["project"], kind="memory"))
    st["pinned"] = [""] + button("g", t("graph_button"), len(rows), bool(rows))
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    if st["q"].strip():
        q = st["q"].lower()
        rows = [r for r in rows
                if q in f"{r['project']} {r['slug']} {r['type']} {r['description']}".lower()]
    return _drill(st, rows, "n_memories")


def fmt_memory(r, w=100):
    if r["kind"] == "project":
        return fmt_project(r)
    head = (f"{cli._pad(r['slug'], 32, cli.BOLD)}{cli._pad(r['type'], 10, ACCENT)}"
            f"{cli._pad(r['machine'], 16, cli.DIM)}{cli._day(r['mtime'])}")
    return head + "\n" + cli.c("  " + " ".join(r["description"].split()), cli.DIM)


def wrap_ansi(line, w, indent=""):
    """A long line → several of `w` visible columns, breaking on spaces.

    `fit()` clips and that is that: in the detail view that ate the end of
    every prompt and every answer from Claude. Here it has to wrap, and wrap
    counting columns and not bytes: the text carries ANSI inside, so the active
    colour is closed at the end of each piece and reopened on the next one, or
    the continuation comes out unpainted.
    """
    if w <= 1:
        return [line]
    out, buf, vis, sgr, i, cut = [], [], 0, "", 0, -1
    width = w
    while i < len(line):
        ch = line[i]
        if ch == "\033":
            j = line.find("m", i)
            if j < 0:
                break
            code = line[i:j + 1]
            sgr = "" if code == "\033[0m" else code
            buf.append(code)
            i = j + 1
            continue
        buf.append(ch)
        if ch == " ":
            cut = len(buf) - 1
        vis += 1
        i += 1
        if vis >= width:
            rest = buf[cut + 1:] if cut > 0 else []
            if cut > 0:
                del buf[cut:]
            out.append(("" if not out else indent) + "".join(buf)
                       + ("\033[0m" if sgr else ""))
            buf = ([sgr] if sgr else []) + rest
            vis = sum(1 for c in buf if not c.startswith("\033"))
            cut = -1
            width = max(1, w - len(indent))
    if buf or not out:
        out.append(("" if not out else indent) + "".join(buf)
                   + ("\033[0m" if sgr else ""))
    return out


def detail_lines(st, w):
    """The detail wrapped to today's width, memoised.

    Wrapping thousands of lines every frame would be throwing work away 20
    times a second; the width only changes when the terminal is resized.
    `dwrap_w = None` is what invalidates the cache when another detail opens.
    """
    if st.get("dwrap_w") != w:
        st["dwrap"] = [wl for l in st["detail"] for wl in wrap_ansi(l, w, "  ")]
        st["dwrap_w"] = w
    return st["dwrap"]


def detail_memory(row):
    f = srv.KNOWLEDGE_MEMORY / row["project"] / row["machine"] / f"{row['slug']}.md"
    try:
        return f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return [f"error: could not read {f} ({e})"]


def _flatten(lines):
    """timeline_lines puts \\n inside some lines (the role separator); it has to
    be flattened before scrolling or the scroll maths lies."""
    out = []
    for l in lines:
        out.extend(l.split("\n"))
    return out


# ── config tab ──

def _origin():
    code, url = srv._git("remote", "get-url", "origin")
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


def load_config(st):
    """Rows of the settings screen. `kind` decides what `↵` does on each one."""
    on = set(srv.get_sync_prefs())
    rows = [{"kind": "head", "text": t("sec_prefs")},
            {"kind": "accent"}, {"kind": "lang"},
            {"kind": "gap"},
            {"kind": "head", "text": t("sec_always")}]
    rows += [{"kind": "fixed", "id": k, "n": v}
             for k, v in knowledge_counts().items()]
    rows += [{"kind": "gap"}, {"kind": "head", "text": t("sec_modules")}]
    rows += [{"kind": "module", "id": m, "on": m in on} for m in srv.CONFIG_MODULES]
    rows += [{"kind": "gap"}, {"kind": "head", "text": t("sec_remote")},
             {"kind": "text", "text": f"origin   {_origin() or t('no_remote')}"},
             {"kind": "text", "text": ""},
             {"kind": "sub", "text": t("sub_first_time")}]
    rows += [{"kind": "text", "text": t(k)} for k in ("step1", "step2", "step3")]
    rows += [{"kind": "text", "text": ""}, {"kind": "sub", "text": t("sub_each_machine")}]
    rows += [{"kind": "text", "text": t(k)} for k in ("step4", "step5", "step6")]
    return rows


def fmt_config(r, w=100):
    if r["kind"] == "gap":
        return ""
    if r["kind"] == "head":
        return section(r["text"], w)
    if r["kind"] == "accent":
        swatch = " ".join(cli.c("██", c) if c == ACCENT else cli.c("░░", cli.DIM)
                          for _, c in ACCENTS)
        return (f"  {cli._pad(t('accent_color'), 22, cli.BOLD)}"
                f"{cli._pad(accent_name(), 12, ACCENT)}{swatch}")
    if r["kind"] == "lang":
        swatch = "  ".join(cli.c(code, ACCENT) if code == i18n.LANG else cli.c(code, cli.DIM)
                           for code in LANGS)
        return (f"  {cli._pad(t('language'), 22, cli.BOLD)}"
                f"{cli._pad(i18n.LANG, 12, ACCENT)}{swatch}")
    if r["kind"] == "fixed":
        count = t("n_in_repo", n=f"{r['n']:>4}")
        return (f"  {cli.c('●', ACCENT)} {cli._pad(t('n_' + r['id']), 20, cli.BOLD)}"
                f"{count}   " + cli.c(t("always_syncing"), cli.DIM))
    if r["kind"] == "sub":
        return "  " + cli.c(r["text"], cli.BOLD)
    if r["kind"] == "module":
        mark = cli.c("[x]", ACCENT) if r["on"] else cli.c("[ ]", cli.DIM)
        return (f"  {mark} {cli._pad(r['id'], 20, cli.BOLD)}"
                + cli.c(t("syncing") if r["on"] else t("not_syncing"), cli.DIM))
    return cli.c("  " + r["text"], cli.DIM) if r["text"] else ""


def config_activate(st):
    """`↵` on the selected config row. Writes prefs to disk.

    ponytail: its own branch in `handle()` instead of generalising the TABS
    `opener` slot into "action" — it is the only tab that mutates instead of
    opening a detail.
    """
    if not st["rows"]:
        return st
    row = st["rows"][st["sel"]]
    if row["kind"] == "accent":
        codes = [c for _, c in ACCENTS]
        set_accent(codes[(codes.index(ACCENT) + 1) % len(codes)])
        st["flash"] = t("flash_accent", v=accent_name())
    elif row["kind"] == "lang":
        set_lang(LANGS[(LANGS.index(i18n.LANG) + 1) % len(LANGS)])
        st["flash"] = t("flash_language", v=i18n.LANG)
    elif row["kind"] == "module":
        on = set(srv.get_sync_prefs())
        on.symmetric_difference_update({row["id"]})
        srv.set_sync_prefs(sorted(on))
        st["flash"] = t("flash_module", id=row["id"],
                        state=t("syncing") if row["id"] in on else t("not_syncing"))
    elif row["kind"] == "fixed":
        st["flash"] = t("flash_always_on", id=row["id"])
        return st
    else:
        return st
    st["loaded_at"] = 0.0
    return st


# ── parity and sync ──

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


def last_sync():
    """'2 days ago · LaptopA' — the commit says which machine it came from."""
    code, out = srv._git("log", "-1", "--format=%cr|%s", "--", "knowledge")
    if code != 0 or "|" not in out:
        return t("never_synced")
    when, _, subject = out.partition("|")
    sep = "sync from "
    machine = subject.split(sep)[-1] if sep in subject else "?"
    return f"{when} · {machine}"


def classify(paths):
    """Git paths → what they mean: {skills, config, memories, sessions, vault}."""
    out = {"skills": [], "config": [], "memories": {}, "sessions": 0, "vault": 0}
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


def manifest_lines(kind, data):
    """The summary of what travels, ready to paint over the frame."""
    out = [cli.c(" " + t("push_to" if kind == "push" else "pull_from"), cli.BOLD)]
    if data["skills"]:
        shown = data["skills"][:8]
        rest = len(data["skills"]) - len(shown)
        text = ", ".join(shown) + (f"  …+{rest}" if rest else "")
        out.append(f"   {cli._pad('skills', 12, ACCENT)}{len(data['skills']):>3}   " + text)
    if data["memories"]:
        detail = " · ".join(f"{p} ({n})" for p, n in sorted(data["memories"].items()))
        out.append(f"   {cli._pad('memories', 12, ACCENT)}"
                   f"{sum(data['memories'].values()):>3}   {detail}")
    if data["config"]:
        out.append(f"   {cli._pad('config', 12, ACCENT)}      "
                   + ", ".join(data["config"]))
    if data["sessions"]:
        out.append(f"   {cli._pad('sessions', 12, ACCENT)}{data['sessions']:>3}")
    if data["vault"]:
        out.append(f"   {cli._pad('vault', 12, ACCENT)}{data['vault']:>3}")
    if len(out) == 1:
        out.append(cli.c("   " + t("nothing_to_sync"), cli.DIM))
    out.append(cli.c(" " + t("confirm"), ACCENT) + cli.c("   " + t("cancel"), cli.DIM))
    return out


# ── help tab ──

USAGE_CAP = 26   # any longer and it eats the description's column


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
        if len(usage) > USAGE_CAP:
            usage = usage[:USAGE_CAP - 1] + "…"
        out.append((usage, what))
    return out


def help_lines(st):
    """The `sto` commands, with what each one does.

    Keyboard shortcuts do not go here: the bottom bar already shows the ones for
    the level you are on, and repeating them was a list that went stale on its
    own every time a key moved.
    """
    w = max(24, st.get("w", 100) - 2)
    out = [_txt(""), _txt(section(t("sec_commands"), w)), _txt("")]
    for usage, what in commands():
        out.append(_txt(f"    {cli._pad(usage, 28, ACCENT)}{cli.c(what, cli.DIM)}"))
    return out


TAB_IDS = ["home", "sessions", "memory", "config", "help"]
TABS = [
    ("home", home_lines, fmt_home, None),
    ("sessions", load_sessions, fmt_session, detail_session),
    ("memory", load_memory, fmt_memory, detail_memory),
    ("config", load_config, fmt_config, None),
    # help reuses fmt_home: they are all text rows and that formatter already
    # knows how to paint them (plus `module`/`item`, which never show up here)
    ("help", help_lines, fmt_home, None),
]
HOME, SESSIONS, MEMORY, CONFIG, HELP = 0, 1, 2, 3, 4
DRILL = (SESSIONS, MEMORY)               # tabs that group by project
CADENCE = (30.0, 3.0, 3.0, 60.0, 3600.0)  # seconds per tab; help never changes
ROW_H = (1, 2, 2, 1, 1)                   # lines one row takes in each tab


def new_state():
    return {"tab": HOME, "sel": 0, "top": 0, "q": "", "mode": "list",
            "rows": [], "detail": [], "dscroll": 0, "agents": False,
            "loaded_at": 0.0, "flash": "", "confirm": None, "quit": False,
            "fetch": False, "manifest": [], "pinned": [],
            "proj": None, "flat": False, "mod": None, "w": 100,
            "dwrap": [], "dwrap_w": None, "job": None, "frame": 0}


def reload_tab(st):
    """Reload the active tab's rows. A loader that blows up does not kill the TUI."""
    loader = TABS[st["tab"]][1]
    st["pinned"] = []          # only home fills it back in
    try:
        st["rows"] = loader(st)
        st["flash"] = ""
    except Exception as e:  # ponytail: the tab shows the error, the loop goes on
        st["rows"] = []
        st["flash"] = f"error: {e}"
    st["loaded_at"] = time.monotonic()
    st["fetch"] = False
    st["sel"] = min(st["sel"], max(0, len(st["rows"]) - 1))
    if st["tab"] == HOME and not st["mod"]:
        return st      # home opens showing the panel, not pinned to a module
    return _snap(st, 1)


def body_height(h):
    return max(1, h - 4)  # 2 of header, 1 rule and 1 of key hints at the bottom


def pinned_of(st, h):
    """The strip pinned to the foot of the body. It never eats the whole body."""
    if st["tab"] not in (HOME, MEMORY) or st["confirm"] or st.get("job") or st["mode"] != "list":
        return []
    return st["pinned"][:max(0, body_height(h) - 1)]


def visible_rows(st, h):
    """How many rows fit: the body, minus what is pinned, divided by ROW_H."""
    free = body_height(h) - len(pinned_of(st, h))
    return max(1, free // ROW_H[st["tab"]])


def _clamp(st, h):
    """The cursor leads, the window follows. Only applies in list mode."""
    if st["mode"] != "list":
        return st
    vis = visible_rows(st, h)
    st["sel"] = max(0, min(st["sel"], max(0, len(st["rows"]) - 1)))
    if st["tab"] == HOME and not st["mod"]:
        # the dashboard is almost all text: with the window following the
        # cursor only from the edge, the first few ↓ moved nothing on screen and
        # the key looked unresponsive. Here the window starts at the cursor, so
        # every ↓ scrolls one line; when the list runs out the top pins itself
        # and the cursor walks the modules at the end.
        st["top"] = max(0, min(st["sel"], len(st["rows"]) - vis))
        return st
    st["top"] = max(min(st["top"], st["sel"]), st["sel"] - vis + 1, 0)
    return st


def scrollbar(total, top, vis, height):
    """A column of `height` chars: '│' the rail, '█' the thumb. All spaces when
    everything fits — without it there is no way to know the list goes on."""
    if total <= vis or height <= 0:
        return [" "] * max(0, height)
    thumb = max(1, round(height * vis / total))
    start = round((height - thumb) * top / (total - vis))
    return ["█" if start <= i < start + thumb else "│" for i in range(height)]


def keys_for(st):
    if st["tab"] == HELP:
        return t("k_help")
    if st["tab"] == HOME:
        return t("k_module") if st["mod"] else t("k_home")
    if st["tab"] == CONFIG:
        return t("k_config")
    if st["tab"] in DRILL and not (st["proj"] or st["flat"] or st["q"].strip()):
        return t("k_project")
    return t("k_list") if st["tab"] == SESSIONS else t("k_memory")


_SUMMARY = {"ts": 0.0, "text": ""}
SUMMARY_TTL = 30  # seconds; painted every frame and it spawns git, so cache it


def status_summary():
    """'usage 42%  ↑3 ↓0' — highest usage % across limits + ahead/behind commits.

    ponytail: the only function doing real I/O on draw()'s path (header() always
    calls it) — ccusage/git subprocesses and a network request through
    srv.usage_snapshot()/srv.sync_status(). The 30s cache is what makes painting
    it every frame tolerable; in tests you seed it or replace this function
    outright (see test_ui.py).
    """
    if time.monotonic() - _SUMMARY["ts"] < SUMMARY_TTL and _SUMMARY["text"]:
        return _SUMMARY["text"]
    try:
        lims = srv.usage_snapshot().get("limits") or []
        pct = max((l.get("percent") or 0) for l in lims) if lims else 0
        sy = srv.sync_status(fetch=False)
        _SUMMARY["text"] = f"{t('usage_pct', p=pct)}  ↑{sy['ahead']} ↓{sy['behind']}"
    except Exception:  # ponytail: the status bar never takes the draw loop down
        _SUMMARY["text"] = ""
    _SUMMARY["ts"] = time.monotonic()
    return _SUMMARY["text"]


TAB_GAP = 3


def tab_label(tid):
    """The label with its own air: the padding of the active rectangle has to
    take the same room as the gap of the inactive ones, or the tabs shift
    around when you switch."""
    return f" {t('tab_' + tid)} "


def tab_positions():
    """(index, label, x0, x1) for each tab, in visible columns."""
    out, x = [], 1
    for i, tid in enumerate(TAB_IDS):
        label = tab_label(tid)
        out.append((i, label, x, x + len(label)))
        x += len(label) + TAB_GAP
    return out


def tab_chip(label, active):
    """The active one is a filled rectangle in the accent colour.

    Reverse video (`7`) instead of an explicit background: inverting makes the
    text take the terminal's *real* background colour, whatever it is. Setting
    black by hand looked fine on a dark theme and was unreadable on a light one.
    """
    return cli.c(label, f"7;{ACCENT}") if active else cli.c(label, cli.DIM)


def header(st, w):
    left = " " + (" " * TAB_GAP).join(
        tab_chip(label, i == st["tab"]) for i, label, *_ in tab_positions())
    if st["proj"]:
        left += cli.c(f"   › {st['proj']}", cli.BOLD)
    # below NARROW the summary steals columns from the tabs and comes out
    # clipped; the data is there in full on the home anyway
    right = status_summary() if w >= NARROW else ""
    gap = max(1, w - len(strip_ansi(left)) - len(right) - 1)
    return left + " " * gap + cli.c(right, cli.DIM)


def draw(st, w, h):
    """The h lines of the frame, each of w visible columns."""
    st["w"] = w          # the loaders build their content against the width
    # no rule under the tabs: one blank line and done. It doubles as the margin
    # that keeps the wordmark off the terminal's edge.
    lines = [header(st, w), ""]
    _clamp(st, h)
    pin = pinned_of(st, h)
    room = body_height(h) - len(pin)
    total = vis = from_ = 0
    if st.get("job"):
        body = job_lines(st)[:room]
    elif st["confirm"]:
        body = st["manifest"][:room]
    elif st["mode"] == "detail":
        # -2: the scrollbar column and its air
        wrapped = detail_lines(st, max(4, w - 2))
        st["dscroll"] = min(st["dscroll"], max(0, len(wrapped) - room))
        body = wrapped[st["dscroll"]:st["dscroll"] + room]
        total, vis, from_ = len(wrapped), room, st["dscroll"]
    elif not st["rows"]:
        body = [cli.c("  " + t("no_results" if st["q"].strip() else "no_data"),
                      cli.DIM)]
    else:
        fmt = TABS[st["tab"]][2]
        nvis = visible_rows(st, h)
        body = []
        for i, row in enumerate(st["rows"][st["top"]:st["top"] + nvis]):
            text = fmt(row, w) if fmt else row
            cursor = "> " if fmt and i + st["top"] == st["sel"] and _actionable(row) else "  "
            # clipped to ROW_H: a formatter returning extra lines must not push
            # the rows below and desync the cursor from the window
            for j, sub in enumerate(str(text).split("\n")[:ROW_H[st["tab"]]]):
                body.append((cursor if j == 0 else "  ") + sub)
        total, vis, from_ = len(st["rows"]), nvis, st["top"]
    body = (body + [""] * room)[:room]
    if total > vis > 0:
        body = [fit(l, w - 2) + " " + cli.c(c, cli.DIM)
                for l, c in zip(body, scrollbar(total, from_, vis, room))]
    lines += body + pin
    lines.append(cli.c("─" * w, cli.DIM))

    if st["confirm"]:
        bottom = st["manifest"][-1] if st["manifest"] else ""
    elif st["mode"] == "search":
        bottom = cli.c(f" /{st['q']}", cli.YELLOW) + cli.c("   " + t("search_hint"), cli.DIM)
    elif st["mode"] == "detail":
        bottom = st["flash"] or t("k_detail")
    else:
        keys = keys_for(st)
        if st["q"].strip():
            keys = (cli.c(" " + t("filter", q=st["q"]), cli.YELLOW)
                    + cli.c("  " + keys, cli.DIM))
        bottom = st["flash"] or keys
    if total > vis > 0:
        # ponytail: the counter is a luxury — if it does not fit without eating a
        # key hint, it is not painted. The scrollbar already says there is more.
        count = f"{from_ + 1}–{min(from_ + vis, total)} / {total} "
        gap = w - len(strip_ansi(bottom)) - len(count)
        if gap >= 1:
            bottom = bottom + " " * gap + cli.c(count, cli.DIM)
    lines.append(bottom)
    return [fit(l, w) for l in lines[:h]]


SELECTABLE = ("accent", "lang", "module", "fixed", "item")


def _snap(st, step):
    """The cursor skips titles, separators and loose text: standing on a
    `── Preferences ──` does nothing and looks odd on top of that.

    Applies in config and on the home. On the home the dashboard is thirty-odd
    lines of text with the modules at the end: moving one line at a time it took
    twenty arrows to reach `skills`, and since the cursor is not painted over
    text, the key looked unresponsive. Snapping, every `↓` lands on the next
    module; PgUp/PgDn are left for reading the panel above.
    """
    if not st["rows"]:
        return st
    if st["tab"] not in (CONFIG, HOME):
        return st
    idx = [i for i, r in enumerate(st["rows"])
           if isinstance(r, dict) and r.get("kind") in SELECTABLE]
    if not idx or st["sel"] in idx:
        return st
    ahead = [i for i in idx if i >= st["sel"]] if step >= 0 else []
    back = [i for i in idx if i <= st["sel"]] if step < 0 else []
    if step >= 0:
        st["sel"] = min(ahead) if ahead else max(idx)
    elif back:
        st["sel"] = max(back)
    else:
        # on the dashboard, above the first module is the rest of the panel:
        # `↑` from there goes back to the top instead of staying put
        st["sel"] = 0 if st["tab"] == HOME and not st["mod"] else min(idx)
    return st


def _actionable(row):
    """A row that does nothing carries no cursor: a lone `>` next to a blank
    dashboard line is noise and says nothing about where you are."""
    return not isinstance(row, dict) or row.get("kind") not in ("text", "sub")


def _reset_view(st, reload=True):
    """Send the cursor back to the top. `reload=False` leaves the tab empty
    until the next `tick()` — useful when switching tabs, where the loader can
    be expensive and we do not want to pay for it on the same keystroke."""
    st["sel"] = st["top"] = 0
    if reload:
        return _snap(reload_tab(st), 1)
    st["rows"] = []
    st["loaded_at"] = 0.0
    return st


def handle(st, key):
    """State + key → new state.

    Not truly pure: filtering (incremental search), opening a detail, activating
    a config row and `p`/`l`/confirming a push-pull all do real I/O (disk,
    `git add`, network) — see the module docstring. The rest of the keys are
    pure dict-in, dict-out.
    """
    if st.get("job"):
        return st      # no keys while it uploads: cutting halfway leaves the repo half-done
    if st["confirm"]:
        return _handle_confirm(st, key)
    if key == "\x03" or (key == "q" and st["mode"] != "search"):
        st["quit"] = True
        return st
    st["flash"] = ""
    if st["mode"] == "detail":
        return _handle_detail(st, key)
    if st["mode"] == "search":
        return _handle_search(st, key)
    # only sessions and memory filter: home and config have a formatter but no
    # list where searching would mean anything
    if key == "/" and st["tab"] in DRILL:
        st["mode"] = "search"
    elif key == "\x1b":
        return _handle_back(st)
    elif key == "down":
        st["sel"] += 1
    elif key == "up":
        st["sel"] -= 1
    elif key == "pgdn":
        st["sel"] += 10
    elif key == "pgup":
        st["sel"] -= 10
    elif key in ("right", "left", "\t", "shifttab"):
        forward = key in ("right", "\t")
        st["tab"] = (st["tab"] + (1 if forward else -1)) % len(TABS)
        st["q"], st["proj"], st["flat"], st["mod"] = "", None, False, None
        return _reset_view(st, reload=False)
    elif key in ("1", "2", "3", "4", "5"):
        st["tab"] = int(key) - 1
        st["q"], st["proj"], st["flat"], st["mod"] = "", None, False, None
        return _reset_view(st, reload=False)
    elif key == "a" and st["tab"] in DRILL:
        st["flat"] = not st["flat"]
        st["proj"] = None
        return _reset_view(st)
    elif key == "g" and st["tab"] == MEMORY:
        res = cli.open_memory_graph()
        st["flash"] = res.get("error") or res.get("message") or t("graph_opening")
    elif key == "g" and st["tab"] == SESSIONS:
        st["agents"] = not st["agents"]
        st["loaded_at"] = 0.0
    elif key == "r":
        st["loaded_at"] = 0.0
    elif key == "d" and st["tab"] == HOME and st["mod"]:
        return _handle_delete(st)
    elif key == "f" and st["tab"] == HOME:
        st["fetch"] = True
        st["loaded_at"] = 0.0
        st["flash"] = t("fetching")
    elif key in ("p", "l"):
        kind = "push" if key == "p" else "pull"
        try:
            data = srv.sync_stage() if key == "p" else srv.sync_incoming()
        except Exception as e:  # ponytail: like reload_tab, a failure does not kill the TUI
            st["flash"] = f"error: {e}"
        else:
            if data.get("error"):
                st["flash"] = data["error"]
            else:
                st["confirm"] = {"kind": kind}
                st["manifest"] = manifest_lines(kind, classify(data["paths"]))
    elif key == "\r":
        return _handle_enter(st)
    st["sel"] = max(0, min(st["sel"], max(0, len(st["rows"]) - 1)))
    if key in ("pgup", "pgdn") and st["tab"] == HOME and not st["mod"]:
        return st        # PgUp/PgDn are for reading: they scroll without snapping
    return _snap(st, -1 if key in ("up", "pgup") else 1)


def _handle_enter(st):
    """`↵`: enter a project, open a detail, or change a config value."""
    if st["tab"] == CONFIG:
        return config_activate(st)
    fmt, opener = TABS[st["tab"]][2], TABS[st["tab"]][3]
    if not (fmt and st["rows"]):
        return st
    row = st["rows"][st["sel"]]
    if not isinstance(row, dict):
        return st
    if row.get("kind") == "module":
        st["mod"] = row["id"]
        return _reset_view(st)
    if row.get("kind") == "project":
        st["proj"] = row["project"]
        return _reset_view(st)
    if opener:
        try:
            st["detail"] = _flatten(opener(row))
        except Exception as e:
            st["detail"] = [f"error: {e}"]
        # dwrap_w=None invalidates the wrapping: this detail is another text
        st["mode"], st["dscroll"], st["dwrap_w"] = "detail", 0, None
    return st


def _handle_back(st):
    """`Esc` goes up one level: filter, then the open project or module."""
    if st["q"]:
        st["q"] = ""
    elif st["proj"]:
        st["proj"] = None
    elif st["mod"]:
        st["mod"] = None
    else:
        return st
    return _reset_view(st)


def _handle_delete(st):
    """`d` inside a module. Skills and plugins only: they are the only ones with
    a delete operation on the other side (`delete_skill`, `claude plugin
    uninstall`). A loose `~/.claude` file is for looking at, not for deleting
    from here.
    """
    if not st["rows"]:
        return st
    row = st["rows"][st["sel"]]
    if not (isinstance(row, dict) and row.get("what") in ("skill", "plugin")):
        st["flash"] = t("not_deletable", id=st["mod"])
        return st
    st["confirm"] = {"kind": "delete", "what": row["what"],
                     "id": row["id"], "label": row["label"]}
    st["manifest"] = delete_lines(row)
    return st


def delete_lines(row):
    """The confirmation card for a delete. Same contract as `manifest_lines`:
    the last line is the one painted on the bottom bar."""
    return [cli.c(" " + t("delete_title", what=row["what"]), cli.BOLD)
            + "  " + cli.c(row["label"], cli.YELLOW),
            cli.c("   " + t("delete_warning"), cli.DIM),
            cli.c(" " + t("confirm"), ACCENT) + cli.c("   " + t("cancel"), cli.DIM)]


def _do_delete(st, c):
    if c["what"] == "skill":
        err = srv.delete_skill(c["id"])
        st["flash"] = err or t("deleted", id=c["label"])
    else:
        res = srv.plugin_cmd("uninstall", c["id"])
        st["flash"] = res.get("error") or t("deleted", id=c["label"])
    st["loaded_at"] = 0.0
    return st


SPIN = "|/-\\"   # ponytail: ASCII; the braille of the pretty spinners comes out
                 # as a box in the old Windows console


def start_job(st, kind):
    """Start push/pull on a thread and leave the steps in `st["job"]["steps"]`.

    This used to be a blocking call and the screen froze until git came back,
    with no way to tell uploading from hung. The thread only does
    `steps.append` and writes `res` at the end; the draw loop only reads: that
    is enough, no lock needed.
    """
    job = {"kind": kind, "steps": [], "res": None}
    fn = srv.sync_push if kind == "push" else srv.sync_pull

    def work():
        try:
            job["res"] = fn(progress=job["steps"].append)
        except Exception as e:  # ponytail: a thread failure is a flash, not a crash
            job["res"] = {"error": str(e)}

    threading.Thread(target=work, daemon=True).start()
    st["job"] = job
    st["flash"] = t("pushing" if kind == "push" else "pulling")
    return st


def job_lines(st):
    """The panel: one step per line, ✓ the closed ones, spinner the running one."""
    job = st["job"]
    out = [cli.c(" " + t("push_to" if job["kind"] == "push" else "pull_from"), cli.BOLD)]
    steps = list(job["steps"])          # the thread can append while we draw
    for i, step in enumerate(steps):
        running = i == len(steps) - 1 and job["res"] is None
        mark = (cli.c(SPIN[st["frame"] % len(SPIN)], ACCENT) if running
                else cli.c("✓", cli.GREEN))
        out.append(f"   {mark} {t(step)}")
    return out


def job_tick(st):
    """Advance the spinner and, once the thread is done, put the result in flash."""
    st["frame"] = int(time.monotonic() * 8)   # 8 fps: visibly spinning without burning CPU
    res = st["job"]["res"]
    if res is None:
        return st
    st["job"] = None
    st["flash"] = res.get("error") or res.get("message") or t("done")
    st["loaded_at"] = 0.0
    return st


def _handle_confirm(st, key):
    c, st["confirm"], st["manifest"] = st["confirm"], None, []
    if key != "\r":
        st["flash"] = t("cancelled")
        return st
    if c["kind"] == "delete":
        return _do_delete(st, c)
    return start_job(st, c["kind"])


def _handle_detail(st, key):
    if key == "\x1b":
        st["mode"] = "list"
        st["detail"], st["dscroll"], st["dwrap_w"] = [], 0, None
    elif key == "down":
        st["dscroll"] += 1
    elif key == "up":
        st["dscroll"] -= 1
    elif key == "pgdn":
        st["dscroll"] += 10
    elif key == "pgup":
        st["dscroll"] -= 10
    # against the wrapped text, which is longer than the raw one; draw() bounds
    # it again against the window's real height
    st["dscroll"] = max(0, min(st["dscroll"], len(st.get("dwrap") or st["detail"])))
    return st


def _handle_search(st, key):
    if key == "\x1b":
        st["q"], st["mode"] = "", "list"
    elif key == "\r":
        st["mode"] = "list"
    elif key == "\x08":
        st["q"] = st["q"][:-1]
    elif len(key) == 1 and key.isprintable():
        st["q"] += key
    else:
        return st                      # arrows and the like: they do not touch the filter
    st["sel"] = st["top"] = 0
    return reload_tab(st)


SPECIAL = {"H": "up", "P": "down", "K": "left", "M": "right", "I": "pgup",
           "Q": "pgdn", "\x0f": "shifttab"}   # \x0f is the Shift+Tab scancode


def read_key():
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):     # special-key prefix
        return SPECIAL.get(msvcrt.getwch(), "")
    return ch


MAX_DRAIN = 64  # ceiling: a stuck key must never stop the repaint


def pending_keys():
    """Every key already sitting in the console buffer, in one go."""
    keys = []
    while msvcrt.kbhit() and len(keys) < MAX_DRAIN:
        keys.append(read_key())
    return keys


def drain(st, keys):
    """Apply a whole burst before repainting.

    The mouse wheel sends ~3 arrow events per notch and the alt buffer queues
    them. Processing one key per frame, a burst of 60 events cost 60 frames and
    scrolling felt heavy and jumpy; here it costs one.
    """
    for k in keys:
        st = handle(st, k)
        if st["quit"]:
            break
    return st


def tick(st):
    """Reload the active tab if its cadence expired, or advance the push/pull."""
    if st.get("job"):
        return job_tick(st)
    if st["mode"] == "list" and time.monotonic() - st["loaded_at"] >= CADENCE[st["tab"]]:
        reload_tab(st)
    return st


# ── terminal ──

# Alt screen + autowrap off. Without the alt screen every frame stays in the
# scrollback and scrolling with the mouse shows old frames stacked (the
# "duplicated view"); with autowrap on, writing the last cell of the last row
# scrolls the terminal and leaks one line per frame. On top of that, in the alt
# buffer Windows Terminal translates the mouse wheel into ↑↓ (alternate scroll
# mode), so wheel scrolling lands in the same key handler and there is no need
# to parse mouse events or touch the console mode.
ENTER_TUI = "\033[?1049h\033[?7l\033[?25l\033[2J"
EXIT_TUI = "\033[?25h\033[?7h\033[?1049l"


def diff_frame(lines, prev):
    """Only the lines that changed, positioned — Ink's rendering idea.

    Repainting the whole frame 20 times a second flickers and pushes ~3 KB per
    frame down the console pipe; writing only what changed does neither.
    """
    if len(prev) != len(lines):
        return "\033[2J" + "".join(f"\033[{i + 1};1H{l}" for i, l in enumerate(lines))
    return "".join(f"\033[{i + 1};1H{l}"
                   for i, (l, old) in enumerate(zip(lines, prev)) if l != old)


def run():
    """sto ui — the loop. Returns the dispatch's {message|error} contract."""
    if msvcrt is None:
        return {"error": "sto ui only runs on Windows for now"}
    if not sys.stdout.isatty():
        return {"error": "sto ui needs a terminal"}
    st = reload_tab(new_state())
    sys.stdout.write(ENTER_TUI)
    # `dirty` is what makes building the frame (~1 ms) worth paying for only
    # when there is something new to show, instead of 100 times a second
    prev, size, dirty = [], None, True
    try:
        while not st["quit"]:
            w, h = shutil.get_terminal_size((100, 30))
            if (w, h) != size:
                # the content is built against the width (banner, buttons,
                # bars, sections), so a resize needs more than a repaint
                st["w"], prev, size, dirty = w, [], (w, h), True
                st = reload_tab(st)
            if dirty:
                lines = draw(st, w, h)
                out = diff_frame(lines, prev)
                if out:
                    sys.stdout.write(out)
                    sys.stdout.flush()
                prev, dirty = lines, False
            keys = pending_keys()
            if keys:
                st = drain(st, keys)
                dirty = True
            else:
                time.sleep(POLL)
                before = (st["loaded_at"], st["frame"], st["job"] is not None)
                st = tick(st)
                dirty = (st["loaded_at"], st["frame"], st["job"] is not None) != before
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(EXIT_TUI)
        sys.stdout.flush()
    return {"message": "bye"}
