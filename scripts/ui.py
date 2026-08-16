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
# Bold yellow, and deliberately not one of the ACCENTS: this is the only colour
# on the home that means "this one is for you to act on", so it must not turn
# into whatever the accent is set to. 256-colour orange would read better and
# is not worth the bet — the old conhost paints it as a box.
NOTICE = "1;33"


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

BUTTONS_W = 52    # below this the two boxes do not fit side by side
BUTTONS3_W = 70   # and below this FETCH does not fit next to them


def button(key, label, n, on):
    """A 3-line box. Accent when enabled, dim when there is nothing to do —
    the colour is what says whether pressing the key does anything.

    `n=None` for a button that does not count anything: FETCH moves no files,
    it goes and asks."""
    inner = f"  [{key}]  {label}  " if n is None else f"  [{key}]  {label} {n:>3}  "
    code = ACCENT if on else cli.DIM
    return [cli.c("┌" + "─" * len(inner) + "┐", code),
            cli.c("│" + inner + "│", code),
            cli.c("└" + "─" * len(inner) + "┘", code)]


def sync_buttons(sy, w=100, up=0, down=0):
    """The PUSH/PULL/FETCH strip.

    The number is **files**, not commits: "↑ PUSH 19" with 19 = commits told
    nobody anything. What travels are knowledge/vault files, and the breakdown
    above says what kind they are.

    FETCH earns its box because ↑↓ is the one number on this screen that goes
    stale on its own: the home repaints every 30 s but asks
    `sync_status(fetch=False)`, so what it shows is however old the last
    `git fetch` is. It is always lit — asking is always something you can do —
    and it drops off first when the terminal narrows, since the footer legend
    carries the key anyway.
    """
    # `up`/`down` already count everything a press would move, config
    # activation included, so `dirty` is gone: it lit PUSH for an unrelated
    # edit under scripts/ that the push was never going to commit.
    push_on = up > 0 or sy["ahead"] > 0
    pull_on = down > 0 or sy["behind"] > 0
    # Two dim buttons are the same picture as "I have not checked yet". With
    # nothing to move in either direction, say so.
    ok = [cli.c(f"  ✓ {t('all_synced')}", cli.GREEN)] if not (push_on or pull_on) else []
    if w < BUTTONS_W:
        return ok + [cli.c(f"  [p] ↑ PUSH {up}", ACCENT if push_on else cli.DIM)
                     + cli.c(f"   [l] ↓ PULL {down}", ACCENT if pull_on else cli.DIM)]
    boxes = [button("p", "↑ PUSH", up, push_on), button("l", "↓ PULL", down, pull_on)]
    if w >= BUTTONS3_W:
        boxes.append(button("f", "⟳ FETCH", None, True))
    return ok + ["  " + "   ".join(fila) for fila in zip(*boxes)]


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
        tail = ("" if r["enabled"] or w < NARROW
                else cli.c("   " + t("module_off"), cli.DIM))
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
    u = srv.usage_snapshot(detail=False)
    # the home never fetches on its own; `st["fetch"]` is only ever set by `f`,
    # so if it is on somebody asked for it and the TTL does not get a vote
    pedido = st.get("fetch", False)
    sy = srv.sync_status(fetch=pedido, force=pedido)
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
    # two lines and not one: ahead/behind carries the age of the last fetch,
    # the sync line carries the age of the last commit. Sharing a line, one
    # relative time had to stand for both and stood for neither — pressing
    # FETCH visibly moved nothing.
    out += [_txt(l) for l in wrap_items(
        [f"↑{sy['ahead']} ↓{sy['behind']}", estado,
         cli.c(t("checked", ago=checked_ago()), cli.DIM)], w, sep=" · ")]
    out += [_txt(l) for l in wrap_items(
        [last_sync()], w, sep=" · ",
        indent="  " + cli.c(cli._pad(t("last_sync"), 14, cli.BOLD), ""))]
    up_st = update_state(pedido)      # `f` asks upstream too, not only origin
    # wrap_items and not one f-string: this line has to survive a narrow
    # terminal like every other one on the home
    if up_st.get("linked") is False:
        out += [_txt(l) for l in wrap_items(
            [cli.c(t("unlinked_short"), cli.YELLOW),
             cli.c(t("unlinked_key"), cli.DIM)], w)]
    elif up_st.get("available"):
        out += [_txt(l) for l in wrap_items(
            [cli.c(f"▲ {t('update_available')}: {up_st['available']}", cli.GREEN),
             cli.c(t("update_apply_key"), ACCENT)], w)]
    # `u` merged new code into the repo, but this process is still running the
    # old one: Python read `ui.py` at import and a redraw cannot undo that. It
    # stays up until the TUI is restarted, which is precisely what it asks for
    # — a flash would be gone by the next repaint, when nothing has changed yet.
    if st.get("updated"):
        out += [_txt(l) for l in wrap_items(
            [cli.c("✓ " + t("update_restart"), NOTICE)], w)]
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


MACHINE_W = 13   # fits a hostname; past that the name is cut, not the row


def list_row(title, sub, machine=None, w=100, code=cli.BOLD):
    """The two-line row that sessions and memories share.

    Title on top in full colour, everything you would only read *after*
    deciding on the row dim underneath, and the machine it came from in a
    column of its own against the right edge.

    The order matters more than it looks. These lists came out sorted by date
    with the date bold on top and the title dim below it, which is backwards:
    the dates are already in order, so scanning them tells you nothing, and the
    one thing that identifies the row was the faintest thing on it. Now the
    eye goes down a column of titles.

    `w` is the frame's full width; the row gets `w - 4` of it — `draw()` puts a
    2-column cursor in front and keeps 2 for the scrollbar and its air.
    """
    inner = max(20, w - 4)
    tag = machine[:MACHINE_W] if machine and w >= NARROW else ""
    title = _clip(title, inner - (len(tag) + 2 if tag else 0))
    head = cli.c(title, code)
    if tag:
        head += " " * max(1, inner - len(title) - len(tag)) + cli.c(tag, cli.DIM)
    # the sub line carries its own 2 spaces: draw() only indents it past the
    # cursor, and the extra step is what makes it read as subordinate
    return head + "\n" + cli.c("  " + _clip(sub, inner - 2), cli.DIM)


def _clip(text, room):
    """One flat line of at most `room` columns, ellipsised if it did not fit.

    Flattening is not cosmetic: a session title is the first prompt verbatim
    and can carry newlines, and a row that returns more lines than ROW_H pushes
    every row under it out from where the cursor thinks it is.
    """
    text = " ".join(str(text).split()) or "—"
    return text if len(text) <= room else text[:max(1, room - 1)] + "…"


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


def _plural(n, one, many):
    return t(one) if n == 1 else t(many, n=n)


def fmt_session(r, w=100):
    """A session inside a project: what was asked, then how big it got.

    `12p 47t 7fd22e7e` was three unlabelled numbers in a row and the id was the
    only one you could even guess at. Spelled out and separated they take the
    same line and read without a legend; the id keeps its place at the end
    because it is what `sto show` wants.

    The title comes from the first prompt and can carry newlines inside —
    `list_row` flattens it, or the row would take more than ROW_H lines and the
    scrollbar would start lying.
    """
    if r["kind"] == "project":
        return fmt_project(r)
    sub = " · ".join([cli._day(r["mtime"]),
                      _plural(r["n_prompts"], "row_prompt", "row_prompts"),
                      _plural(r["n_tools"], "row_tool", "row_tools"),
                      r["id"][:8]])
    return list_row(r["title"], sub, r["machine"] or srv.LOCAL_MACHINE, w)


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
    """Same shape as a session row, so the two tabs read as one thing.

    The machine used to sit in the middle of the head, between the type and the
    date, where it split the row in two and lined up with nothing on the tab
    next door. It is the same question a session answers, so it gets the same
    column.
    """
    if r["kind"] == "project":
        return fmt_project(r)
    sub = " · ".join([r["type"], cli._day(r["mtime"]), r["description"]])
    return list_row(r["slug"], sub, r["machine"], w)


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


def _upstream():
    code, url = srv._git("remote", "get-url", srv.UPSTREAM)
    return url.strip() if code == 0 and url.strip() else ""


def _short_remote(url, w):
    """The remote as wide as there is room for. A URL has no spaces to wrap on,
    so what gives is the part you already know: the scheme, the host and the
    `.git`. `owner/repo` is the bit that tells you *which* repo it is."""
    if not url or len(url) <= w:
        return url
    short = url.removesuffix(".git")
    for prefix in ("https://github.com/", "git@github.com:", "https://", "git@"):
        short = short.removeprefix(prefix)
    return short if len(short) <= w else "…" + short[-(w - 1):]


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
            {"kind": "badge", "on": srv.badge_status()["on"]},
            {"kind": "gap"},
            {"kind": "head", "text": t("sec_always")}]
    rows += [{"kind": "fixed", "id": k, "n": v}
             for k, v in knowledge_counts().items()]
    rows += [{"kind": "gap"}, {"kind": "head", "text": t("sec_modules")}]
    rows += [{"kind": "module", "id": m, "on": m in on} for m in srv.CONFIG_MODULES]
    # -6: the two-space indent `fmt_config` adds plus the scrollbar and its air
    w = max(30, st.get("w", 100) - 6)
    rows += [{"kind": "gap"}, {"kind": "head", "text": t("sec_remote")}]
    for name, url, note in (("origin", _origin(), t("r_origin")),
                            ("upstream", _upstream(), t("r_upstream"))):
        head = wrap_text(note, w, indent=f"{name:<9}", hang=9)
        rows += [{"kind": "text", "text": l} for l in head]
        rows.append({"kind": "text",
                     "text": f"{'':<9}{_short_remote(url, w - 9) or t('no_remote')}"})
    # The setup guide is folded away by default. Twenty-odd lines you read once
    # and never again were the reason this screen did not fit a normal terminal,
    # and the overflow was worse than cosmetic: the cursor only lands on
    # SELECTABLE rows, the window follows the cursor, and the last selectable row
    # was a module — so everything under it could not be scrolled to at all.
    # Folded, the screen fits and the toggle is the last row, which is what lets
    # the cursor drag the window to the very bottom when the terminal is small.
    rows += [{"kind": "gap"}, {"kind": "guide", "open": bool(st.get("guide"))}]
    if not st.get("guide"):
        return rows
    for sub, donde, steps in (
            (t("sub_first_time"), "where_steps",
             ("step1", "step2", "step3", "step3b", "step3c")),
            (t("sub_each_machine"), "where_more",
             ("step4", "step5", "step6", "step6b", "step6c")),
            (t("sub_updates"), None, ("step7", "step8", "step9"))):
        rows += [{"kind": "text", "text": ""}, {"kind": "sub", "text": sub}]
        # the "where do I run this" line first: that was the whole confusion,
        # the steps never said which folder they belonged to
        for k in ([donde] if donde else []) + list(steps):
            # wrapped here and not in `fmt_config`: the rows are the unit the
            # cursor and the scrollbar count, so a line that grows at paint time
            # would push the ones below out of the window
            rows += [{"kind": "text", "text": l}
                     for l in wrap_text(t(k), w, indent="  ", hang=3)]
    # closing toggle: with the guide open the text is what runs off the bottom,
    # so the last row has to be one the cursor can reach
    rows += [{"kind": "text", "text": ""},
             {"kind": "guide", "open": True, "foot": True}]
    return rows


def fmt_config(r, w=100):
    # the label column, and after it the value: fixed at 22/12 the three
    # preference rows ran off the edge of a narrow terminal
    lab, val = (22, 12) if w >= NARROW else (max(10, w - 24), 10)
    if r["kind"] == "gap":
        return ""
    if r["kind"] == "head":
        return section(r["text"], w)
    if r["kind"] == "accent":
        # 36 = the two labels; below that the swatch does not fit and the row
        # spilled past the edge. The colour name still says which one is on.
        swatch = ("" if w < 54 else
                  " ".join(cli.c("██", c) if c == ACCENT else cli.c("░░", cli.DIM)
                           for _, c in ACCENTS))
        return (f"  {cli._pad(t('accent_color'), lab, cli.BOLD)}"
                f"{cli._pad(accent_name(), val, ACCENT)}{swatch}").rstrip()
    if r["kind"] == "lang":
        swatch = "  ".join(cli.c(code, ACCENT) if code == i18n.LANG else cli.c(code, cli.DIM)
                           for code in LANGS)
        return (f"  {cli._pad(t('language'), lab, cli.BOLD)}"
                f"{cli._pad(i18n.LANG, val, ACCENT)}{swatch}")
    if r["kind"] == "badge":
        mark = cli.c("[x]", ACCENT) if r["on"] else cli.c("[ ]", cli.DIM)
        return (f"  {cli._pad(t('badge_row'), lab, cli.BOLD)}{mark}   "
                + cli.c(t("badge_on") if r["on"] else t("badge_off"), cli.DIM))
    if r["kind"] == "fixed":
        count = t("n_in_repo", n=f"{r['n']:>4}")
        tail = "   " + cli.c(t("always_syncing"), cli.DIM) if w >= NARROW else ""
        return (f"  {cli.c('●', ACCENT)} {cli._pad(t('n_' + r['id']), lab - 2, cli.BOLD)}"
                f"{count}{tail}")
    if r["kind"] == "sub":
        return "  " + cli.c(r["text"], cli.BOLD)
    if r["kind"] == "guide":
        if r.get("foot"):
            return "  " + cli.c("▴ " + t("guide_close"), cli.DIM)
        return ("  " + cli.c(("▾ " if r["open"] else "▸ ") + t("guide_open"), ACCENT)
                + ("" if r["open"] or w < NARROW
                   else cli.c("   " + t("guide_hint"), cli.DIM)))
    if r["kind"] == "module":
        mark = cli.c("[x]", ACCENT) if r["on"] else cli.c("[ ]", cli.DIM)
        return (f"  {mark} {cli._pad(r['id'], lab - 2, cli.BOLD)}"
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
        _repaint(st)
    elif row["kind"] == "lang":
        set_lang(LANGS[(LANGS.index(i18n.LANG) + 1) % len(LANGS)])
        st["flash"] = t("flash_language", v=i18n.LANG)
        _repaint(st)
    elif row["kind"] == "badge":
        res = srv.set_badge(not row["on"])
        st["flash"] = res.get("error") or t("flash_badge",
                                            state=t("badge_off" if row["on"] else "badge_on"))
    elif row["kind"] == "module":
        on = set(srv.get_sync_prefs())
        on.symmetric_difference_update({row["id"]})
        srv.set_sync_prefs(sorted(on))
        st["flash"] = t("flash_module", id=row["id"],
                        state=t("syncing") if row["id"] in on else t("not_syncing"))
    elif row["kind"] == "guide":
        st["guide"] = not st.get("guide")
        st = reload_tab(st)
        # the cursor stays on the toggle it just pressed: folding the guide from
        # its closing row would otherwise leave `sel` pointing past the end
        st["sel"] = min(i for i, r in enumerate(st["rows"])
                        if r.get("kind") == "guide")
        return st
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


def update_manifest(up_st):
    """What `u` is about to merge: the commit list, and the promise it keeps."""
    out = [cli.c(" " + t("update_available") + f": {up_st['available']}", cli.BOLD)]
    out += [cli.c("   " + l, cli.DIM) for l in up_st.get("log", [])[:8]]
    out.append(cli.c("   " + t("update_safe"), cli.GREEN))
    out.append(cli.c(" " + t("confirm"), ACCENT) + cli.c("   " + t("cancel"), cli.DIM))
    return out


def manifest_lines(kind, data):
    """The summary of what travels, ready to paint over the frame."""
    out = [cli.c(" " + t("push_to" if kind == "push" else "pull_from"), cli.BOLD)]
    if data["skills"]:
        shown = data["skills"][:8]
        rest = len(data["skills"]) - len(shown)
        text = ", ".join(shown) + (f"  …+{rest}" if rest else "")
        out.append(f"   {cli._pad('skills', 12, ACCENT)}{len(data['skills']):>3}   " + text)
    n_mem = max(sum(data["memories"].values()), data.get("pending_memories", 0))
    if n_mem:
        detail = " · ".join(f"{p} ({n})" for p, n in sorted(data["memories"].items()))
        out.append(f"   {cli._pad('memories', 12, ACCENT)}{n_mem:>3}   {detail}")
    if data["config"]:
        out.append(f"   {cli._pad('config', 12, ACCENT)}      "
                   + ", ".join(data["config"]))
    if data["sessions"]:
        out.append(f"   {cli._pad('sessions', 12, ACCENT)}{data['sessions']:>3}")
    if data["vault"]:
        out.append(f"   {cli._pad('vault', 12, ACCENT)}{data['vault']:>3}")
    if data.get("activate"):
        out.append(f"   {cli._pad(t('n_activate'), 12, ACCENT)}{data['activate']:>3}"
                   f"   {cli.c(t('activate_hint'), cli.DIM)}")
    if len(out) == 1:
        out.append(cli.c("   " + t("nothing_to_sync"), cli.DIM))
    out.append(cli.c(" " + t("confirm"), ACCENT) + cli.c("   " + t("cancel"), cli.DIM))
    return out


# ── help tab ──


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


def wrap_text(text, w, indent="", hang=0):
    """A sentence over as many `w`-wide lines as it takes. `wrap_items` packs a
    list; this packs prose, which is the same job with a space for a separator,
    continuation indent and ANSI-aware widths already included.

    `hang` pushes the continuation lines further in, so a wrapped `2. git…`
    does not read as a step of its own.
    """
    lines = wrap_items(text.split(), w - hang, indent=indent, sep=" ")
    return lines[:1] + [" " * hang + l for l in lines[1:]]


def help_lines(st):
    """The `sto` commands, with what each one does.

    The syntax used to be cut at 26 columns with an ellipsis, which is the one
    thing on this screen you cannot guess: `sto memory [<project> | s…` tells
    you nothing. Now nothing is truncated — when the full form does not fit the
    column, the arguments drop to their own wrapped line under the command, and
    both the column and the wrapping follow the terminal's width.

    Keyboard shortcuts do not go here: the bottom bar already shows the ones for
    the level you are on, and repeating them was a list that went stale on its
    own every time a key moved.
    """
    w = max(24, st.get("w", 100) - 2)
    col = min(30, max(12, w // 3))       # the command column, never past a third
    out = [_txt(""), _txt(section(t("sec_commands"), w)), _txt("")]
    for usage, what in commands():
        head, _, args = usage.partition(" ")
        name, _, args = args.partition(" ")   # "sto memory" | "[<project> | …]"
        cmd = f"{head} {name}".strip()
        one_line = usage if len(usage) <= col - 2 else cmd
        first = f"    {cli._pad(one_line, col, ACCENT)}"
        desc = wrap_text(what, w, indent=" " * (col + 4))
        out.append(_txt(first + cli.c(desc[0].strip(), cli.DIM)))
        out += [_txt(cli.c(l, cli.DIM)) for l in desc[1:]]
        if one_line != usage:            # the arguments could not ride along
            out += [_txt(cli.c(l, cli.DIM))
                    for l in wrap_text(args, w, indent=" " * 8)]
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
            "fetch": False, "manifest": [], "pinned": [], "updated": False,
            "guide": False,
            "proj": None, "flat": False, "mod": None, "w": 100,
            "dwrap": [], "dwrap_w": None, "job": None, "frame": 0,
            "cache": {}}


def _plain_view(st):
    """Is this the tab's default view? Only that one is worth caching: a
    filtered or drilled-in list belongs to the keystrokes that built it."""
    return not (st["proj"] or st["mod"] or st["q"].strip() or st["flat"])


def _keep(st):
    st["cache"][st["tab"]] = (st["rows"], st["pinned"], st["loaded_at"])


def _repaint(st):
    """Throw away every cached tab: colour and language are baked into it.

    The home rows and the button strip are *rendered* strings, ANSI included,
    so after changing the accent the cache kept painting the logo, the buttons
    and the bars in the old colour until each tab happened to expire. Same for
    the language. The cost of being wrong here is a screen that lies; the cost
    of clearing is one reload."""
    st["cache"].clear()
    _BG["box"] = None          # a load in flight was rendered in the old colour
    st["loaded_at"] = 0.0      # and repaint the tab that is up right now


def _recall(st):
    """Put the tab's last rows back on screen. Coming back to the home used to
    paint 'no data' and then block the loop for 1.3 s rebuilding it; the rows
    from a minute ago are a far better answer than an empty screen, and
    `tick()` refreshes them in the background from there."""
    rows, pinned, at = st["cache"].get(st["tab"], ([], [], 0.0))
    st["rows"], st["pinned"], st["loaded_at"] = rows, pinned, at
    return bool(rows)


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
    if _plain_view(st):
        _keep(st)
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
    if st["tab"] == CONFIG:
        # above the first selectable row there is only its section header, and
        # `top` can never climb past `sel`: without this, scrolling down and
        # back up left the window one line short of the top for good.
        idx = next((i for i, r in enumerate(st["rows"])
                    if isinstance(r, dict) and r.get("kind") in SELECTABLE), None)
        if idx is not None and st["sel"] <= idx:
            st["top"] = 0
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
        lims = srv.usage_snapshot(detail=False).get("limits") or []
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
        if st["loaded_at"] == 0.0:          # never loaded: it is coming, not absent
            body = [cli.c(f"  {SPIN[st['frame'] % len(SPIN)]} {t('loading')}", ACCENT)]
        else:
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
        if st["flash"] and busy():
            # the spinner is the whole point: "fetching…" on its own could just
            # as well be a message left over from a fetch that already ended
            bottom = cli.c(f" {SPIN[st['frame'] % len(SPIN)]} ", ACCENT) + st["flash"]
    if total > vis > 0:
        # ponytail: the counter is a luxury — if it does not fit without eating a
        # key hint, it is not painted. The scrollbar already says there is more.
        count = f"{from_ + 1}–{min(from_ + vis, total)} / {total} "
        gap = w - len(strip_ansi(bottom)) - len(count)
        if gap >= 1:
            bottom = bottom + " " * gap + cli.c(count, cli.DIM)
    lines.append(bottom)
    return [fit(l, w) for l in lines[:h]]


# every kind `config_activate`/`_handle_enter` knows how to act on. A row
# missing here is invisible to the cursor: `_snap` walks straight past it and
# `↵` can never reach it — which is exactly how the badge toggle shipped dead.
SELECTABLE = ("accent", "lang", "badge", "module", "fixed", "item", "guide")


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
    if not _recall(st):
        st["rows"], st["loaded_at"] = [], 0.0
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
    elif key == "u" and st["tab"] == HOME and not st["mod"]:
        up_st = update_state(force=True)   # an explicit press always asks
        if up_st.get("linked") is False:
            st["flash"] = t("cli_update_link_hint")
        elif not up_st.get("available"):
            st["flash"] = t("cli_update_none")
        else:
            st["confirm"] = {"kind": "update"}
            st["manifest"] = update_manifest(up_st)
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
                info = classify(data["paths"])
                info["activate"] = data.get("activate", 0)
                info["pending_memories"] = data.get("memories", 0)
                st["confirm"] = {"kind": kind}
                st["manifest"] = manifest_lines(kind, info)
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
    fn = {"push": srv.sync_push, "pull": srv.sync_pull,
          "update": srv.update_apply}[kind]

    def work():
        try:
            job["res"] = fn(progress=job["steps"].append)
        except Exception as e:  # ponytail: a thread failure is a flash, not a crash
            job["res"] = {"error": str(e)}

    threading.Thread(target=work, daemon=True).start()
    st["job"] = job
    st["flash"] = t({"push": "pushing", "pull": "pulling",
                     "update": "updating"}[kind])
    return st


def job_lines(st):
    """The panel: one step per line, ✓ the closed ones, spinner the running one."""
    job = st["job"]
    out = [cli.c(" " + t({"push": "push_to", "pull": "pull_from",
                          "update": "update_available"}[job["kind"]]), cli.BOLD)]
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
    kind, st["job"] = st["job"]["kind"], None
    st["flash"] = res.get("error") or res.get("message") or t("done")
    if kind == "update":
        _UPDATE["ts"] = 0.0
        # only on success: an update that failed to merge has nothing to restart for
        st["updated"] = st["updated"] or not res.get("error")
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


_BG = {"thread": None, "box": None}


def busy():
    """Is a background reload running right now?

    The bottom bar asks so it can animate: a message that sits there perfectly
    still is indistinguishable from a hung one, which is precisely the doubt
    `fetching…` used to leave.
    """
    return bool(_BG["thread"] and _BG["thread"].is_alive())


def _view_key(st):
    """What the rows on screen are a list OF.

    A background load started on one screen can land after you moved to
    another, and the rows of one tab painted by another tab's formatter is a
    crash: `KeyError: 'type'` in `fmt_memory` with a session row in hand. The
    key is compared on arrival and a stale answer is dropped."""
    return (st["tab"], st["proj"], st["mod"], st["q"].strip(),
            st["flat"], st["agents"])


def bg_reload(st):
    """Refresh the rows off the main loop, keeping the old ones on screen.

    The periodic refresh used to run inline: `cached_sessions()` every 3 s on
    the list tabs, and on the home a git + parity + dry-run sweep every 30 s.
    The whole loop stopped for as long as that took, keystrokes included —
    which is the freeze you feel mid-scroll. The loader only reads the state
    (`home_lines` writes `pinned`, and it writes it into the copy), so a
    snapshot is all the thread needs.
    """
    if busy():
        return st                       # one at a time; the cadence can wait
    if _BG["box"] is not None and _BG["box"][3] != _view_key(st):
        _BG["box"] = None               # answers the screen you already left
    if _BG["box"] is not None:
        rows, pinned, err, _ = _BG["box"]
        _BG["box"] = None
        st["rows"], st["pinned"] = rows, pinned
        # unconditionally, same contract as reload_tab: the message that was up
        # ("fetching…") described work that has just finished. Only setting it
        # on error left it frozen on screen until an unrelated keypress wiped
        # it, which is how a finished fetch looked exactly like a hung one.
        st["flash"] = err
        st["sel"] = min(st["sel"], max(0, len(st["rows"]) - 1))
        st["loaded_at"] = time.monotonic()
        st["fetch"] = False
        if _plain_view(st):
            _keep(st)
        return st
    snap, loader, key = dict(st), TABS[st["tab"]][1], _view_key(st)
    snap["pinned"] = []

    def work():
        try:
            rows, err = loader(snap), ""
        except Exception as e:  # ponytail: same contract as reload_tab
            rows, err = [], f"error: {e}"
        _BG["box"] = (rows, snap["pinned"], err, key)

    _BG["thread"] = threading.Thread(target=work, daemon=True)
    _BG["thread"].start()
    return st


def tick(st):
    """Reload the active tab if its cadence expired, or advance the push/pull."""
    if st.get("job"):
        return job_tick(st)
    if busy() or (not st["rows"] and st["loaded_at"] == 0.0):
        st["frame"] = int(time.monotonic() * 8)   # spin while a load runs
    # `loaded_at == 0.0` means "never loaded", not "loaded at second zero": on
    # Windows `monotonic()` counts from boot, so with less than an hour of
    # uptime the subtraction never reached the help tab's 3600 s cadence and it
    # spun on `loading…` forever (config did the same for the first minute).
    stale = (st["loaded_at"] == 0.0
             or time.monotonic() - st["loaded_at"] >= CADENCE[st["tab"]])
    if st["mode"] == "list" and stale:
        # empty rows means the view just changed (tab switch, filter): there is
        # nothing to keep showing, so pay for it now instead of painting a
        # blank tab for a second.
        bg_reload(st) if st["rows"] else reload_tab(st)
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
    # The screen goes up BEFORE the first load: that load is ~1 s of git,
    # skills and dry runs, and paying for it with the shell still on screen is
    # what made `sto ui` feel like it did not start. The frame with the tabs
    # appears at once and `tick()` fills the body in.
    st = new_state()
    st["flash"] = t("loading")
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
