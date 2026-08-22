#!/usr/bin/env python3
"""STO Sessions Browser backend.

Read-only stdlib HTTP server over ~/.claude/projects/**/*.jsonl. Reuses
dream_extract.py for parsing. Serves two JSON endpoints on 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path, PurePath

sys.path.insert(0, str(Path(__file__).parent))  # so `import dream_extract` works
import agents
import dream_extract as dx

MAX_SESSIONS = 500
TITLE_CAP = 120


_PROMPTS_INDEX: dict[str, str] = {}  # session id → lowercased prompt text, for search


_PROJECT_NAMES: dict[str, str] = {}  # session dir name → short project identity


def project_name(path: Path, cwd: str | None = None) -> str:
    """Short, machine-independent project identity for a session file.

    Git repo with an origin remote → repo name from the remote URL (same repo
    cloned anywhere on any machine groups as one project). Otherwise the cwd
    basename. Without cwd (trimmed knowledge exports) → parent dir name.
    """
    # ponytail: basename identity; distinct non-repo projects with equal
    # basenames merge into one group. Add a parent segment if that ever hurts.
    key = path.parent.name
    if cwd and key not in _PROJECT_NAMES:
        import subprocess as sp
        name = PurePath(cwd.replace("\\", "/")).name or key
        try:
            r = sp.run(["git", "-C", cwd, "remote", "get-url", "origin"],
                       capture_output=True, text=True, timeout=5)
            url = r.stdout.strip()
            if r.returncode == 0 and url:
                name = url.rstrip("/").split("/")[-1].removesuffix(".git") or name
        except OSError:
            pass
        _PROJECT_NAMES[key] = name
    return _PROJECT_NAMES.get(key, key)


def session_meta(path: Path) -> dict:
    with path.open(encoding="utf-8", errors="replace") as fh:
        d = dx.parse_lines(fh)
    _PROMPTS_INDEX[path.stem] = " ".join(d["prompts"]).lower()
    return {
        "id": path.stem,
        "project": project_name(path, d.get("cwd")),
        "mtime": path.stat().st_mtime,
        "title": (d["prompts"][0][:TITLE_CAP] if d["prompts"] else "(no prompt)"),
        "n_prompts": len(d["prompts"]),
        "n_tools": sum(d["tools"].values()),
        "errors": d["errors"],
    }


ERROR_SNIPPET_CAP = 320
IMAGE_DATA_CAP = 300_000  # base64 chars; bigger attachments are skipped
_DETAIL_KEYS = ("file_path", "command", "pattern", "url", "path", "query",
                "prompt", "skill", "description")


def _tool_detail(inp) -> str:
    """Short human-readable summary of a tool_use input."""
    if not isinstance(inp, dict):
        return ""
    for k in _DETAIL_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:160]
    return ""


TOOL_INPUT_VALUE_CAP = 4000
TOOL_INPUT_KEY_CAP = 12


def _tool_input_slim(inp) -> dict:
    """Full tool input for the expandable view: every param, redacted + capped."""
    if not isinstance(inp, dict):
        return {}
    out = {}
    for k, v in list(inp.items())[:TOOL_INPUT_KEY_CAP]:
        if v is None or v == "":
            continue
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        out[str(k)] = dx._redact(s[:TOOL_INPUT_VALUE_CAP])
    return out


def _block_text(content) -> str:
    """Flatten a tool_result content (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def session_timeline(path: Path) -> dict:
    items = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            kind = o.get("type")
            if kind == "user" and isinstance(content, str):
                s = content.strip()
                if s and not s.startswith("<"):
                    items.append({"role": "user", "text": dx._redact(s)})
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if kind == "assistant" and btype == "text" and b.get("text", "").strip():
                        items.append({"role": "assistant", "text": dx._redact(b["text"])})
                    elif kind == "assistant" and btype == "tool_use" and b.get("name"):
                        items.append({"role": "tool", "tool": b["name"],
                                      "detail": _tool_detail(b.get("input")),
                                      "input": _tool_input_slim(b.get("input"))})
                    elif kind == "user" and btype == "text" and b.get("text", "").strip():
                        s = b["text"].strip()
                        if not s.startswith("<"):
                            items.append({"role": "user", "text": dx._redact(s)})
                    elif kind == "user" and btype == "image":
                        src = b.get("source") or {}
                        data = src.get("data", "")
                        if src.get("type") == "base64" and 0 < len(data) <= IMAGE_DATA_CAP:
                            items.append({"role": "image",
                                          "media_type": src.get("media_type", "image/png"),
                                          "data": data})
                    elif btype == "tool_result" and b.get("is_error"):
                        snippet = _block_text(b.get("content")).strip()[:ERROR_SNIPPET_CAP]
                        items.append({"role": "error", "text": dx._redact(snippet)})
    return {"id": path.stem, "project": project_name(path), "timeline": items}


import platform

LOCAL_MACHINE = platform.node() or "local"
KNOWLEDGE_SESSIONS = Path(__file__).parent.parent / "knowledge" / "sessions"


def machine_type() -> str:
    """"laptop" | "desktop" for THIS machine — battery presence is the tell."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _SPS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_ubyte),
                            ("BatteryFlag", ctypes.c_ubyte),
                            ("BatteryLifePercent", ctypes.c_ubyte),
                            ("Reserved1", ctypes.c_ubyte),
                            ("BatteryLifeTime", ctypes.c_uint32),
                            ("BatteryFullLifeTime", ctypes.c_uint32)]

            sps = _SPS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                return "desktop" if sps.BatteryFlag & 128 else "laptop"
        elif any(Path("/sys/class/power_supply").glob("BAT*")):
            return "laptop"
    except OSError:
        pass
    return "desktop"


def list_machines(knowledge_dir=None) -> dict:
    """{name: {type, local}} for this machine + every machine seen in knowledge/."""
    kd = knowledge_dir if knowledge_dir is not None else KNOWLEDGE_SESSIONS
    out = {LOCAL_MACHINE: {"type": machine_type(), "local": True}}
    if kd.is_dir():
        for machine_dir in sorted(kd.iterdir()):
            if not machine_dir.is_dir() or machine_dir.name in out:
                continue
            mtype = "unknown"
            try:
                mtype = json.loads((machine_dir / "machine.json")
                                   .read_text(encoding="utf-8")).get("type", "unknown")
            except (OSError, ValueError):
                pass
            out[machine_dir.name] = {"type": mtype, "local": False}
    return out


def _knowledge_sessions(knowledge_dir=None) -> list[tuple[str, Path]]:
    """(machine, path) for every session in the repo, this machine's own included.

    Our own folder used to be skipped as "already listed from ~/.claude/projects",
    and that is why the same repo showed fewer sessions on the machine that
    recorded them than on the other one: Claude Code prunes its transcripts, the
    exports in the repo are never pruned. The live file still wins when both
    exist — `list_sessions` puts the local ones first and dedupes by id.
    """
    kd = knowledge_dir if knowledge_dir is not None else KNOWLEDGE_SESSIONS
    if not kd.is_dir():
        return []
    out = []
    for machine_dir in sorted(kd.iterdir()):
        if not machine_dir.is_dir():
            continue
        out.extend((machine_dir.name, p) for p in machine_dir.rglob("*.jsonl"))
    return out


_sessions_cache: dict = {"ts": 0.0, "data": None}
SESSIONS_TTL = 15  # seconds; parsing every .jsonl per request costs ~2s


def list_sessions(projects_dir=None, knowledge_dir=None) -> list[dict]:
    import time as _t
    cacheable = projects_dir is None and knowledge_dir is None
    if cacheable and _sessions_cache["data"] is not None \
            and _t.time() - _sessions_cache["ts"] < SESSIONS_TTL:
        return _sessions_cache["data"]
    pd = projects_dir or dx.PROJECTS_DIR
    cands = [(LOCAL_MACHINE, p)
             for _, p in dx.find_sessions(None, projects_dir=pd, max_sessions=MAX_SESSIONS)]
    cands += _knowledge_sessions(knowledge_dir)
    rows, seen = [], set()
    for machine, p in cands:
        if p.stem in seen:
            continue
        seen.add(p.stem)
        m = session_meta(p)
        if m["n_prompts"] == 0:
            continue  # noise: sessions where nothing was asked
        m["machine"] = None if machine == LOCAL_MACHINE else machine
        rows.append(m)
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    rows = rows[:MAX_SESSIONS]
    if cacheable:
        _sessions_cache.update(ts=_t.time(), data=rows)
    return rows


def search_sessions(q: str, projects_dir=None, knowledge_dir=None, limit=50,
                    rows=None) -> list[dict]:
    """Rank sessions by match/closeness of q against titles + prompt content.

    `rows` avoids the rescan: the CLI passes the rows from its on-disk cache.
    """
    import difflib
    q = q.strip().lower()
    if not q:
        return []
    terms = q.split()
    if rows is None:
        rows = list_sessions(projects_dir=projects_dir, knowledge_dir=knowledge_dir)
    scored = []
    for r in rows:
        text = (_PROMPTS_INDEX.get(r["id"], "") + " " + r["title"].lower())
        score = 0.0
        words = None
        for t in terms:
            if t in text:
                score += 2 + min(text.count(t), 10) * 0.1
            else:
                if words is None:
                    words = list(dict.fromkeys(text.split()))[:2000]
                if difflib.get_close_matches(t, words, n=1, cutoff=0.8):
                    score += 1  # near miss: typo-tolerant word match
        if score >= len(terms):  # every term matched, exactly or fuzzily
            scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], -x[1]["mtime"]))
    return [r for _, r in scored[:limit]]


def find_path_by_id(sid: str, projects_dir=None, knowledge_dir=None):
    pd = projects_dir or dx.PROJECTS_DIR
    for _, p in dx.find_sessions(None, projects_dir=pd, max_sessions=MAX_SESSIONS):
        if p.stem == sid:
            return p
    for _, p in _knowledge_sessions(knowledge_dir):
        if p.stem == sid:
            return p
    return None


# The agent's home comes from `agents.py`, the one place that knows the shape of
# an agent. Kept under the old name: every call site already threads it through
# a `claude_dir=` parameter, and renaming 16 of those buys nothing.
CLAUDE_DIR = agents.home()
GRAPH_JSON = Path(__file__).parent.parent / "graphify-out" / "graph.json"
DESC_CAP = 300


def _frontmatter(text: str) -> dict:
    """Parse `key: value` YAML frontmatter, including folded/literal multiline
    scalars (`>`, `|` markers). Good enough for SKILL.md."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta, i = {}, 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            v = v.strip()
            if v in (">", ">-", "|", "|-"):  # multiline scalar: gather indented block
                parts = []
                while i + 1 < len(lines) and (lines[i + 1].startswith((" ", "\t")) or not lines[i + 1].strip()):
                    if lines[i + 1].strip() == "---":
                        break
                    parts.append(lines[i + 1].strip())
                    i += 1
                v = " ".join(x for x in parts if x)
            meta[k.strip()] = v
        i += 1
    return meta


def _skill_paths(claude_dir: Path):
    """Yield (source, skill_dir) for personal skills + installed-plugin skills."""
    skills_root = claude_dir / agents.active()["skills"]
    if skills_root.is_dir():
        for d in sorted(skills_root.iterdir()):
            if (d / "SKILL.md").is_file():
                yield "personal", d
    manifest = claude_dir / agents.active()["plugins"] / "installed_plugins.json"
    try:
        plugins = json.loads(manifest.read_text(encoding="utf-8")).get("plugins", {})
    except (OSError, ValueError):
        return
    for key, installs in plugins.items():
        source = key.split("@", 1)[0]
        for inst in installs if isinstance(installs, list) else []:
            root = Path(inst.get("installPath", ""))
            if not root.is_dir():
                continue
            for md in sorted(root.rglob("SKILL.md")):
                yield source, md.parent


def list_skills(claude_dir=None) -> list[dict]:
    rows, seen = [], set()
    for source, d in _skill_paths(claude_dir or CLAUDE_DIR):
        sid = f"{source}:{d.name}"
        if sid in seen:
            continue
        seen.add(sid)
        meta = _frontmatter((d / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
        desc = meta.get("description", "")
        rows.append({
            "id": sid,
            "name": meta.get("name", d.name),
            "source": source,
            "description": desc[:DESC_CAP],
        })
    return rows


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).lstrip("\n")
    return text


def get_skill(skill_id: str, claude_dir=None):
    for source, d in _skill_paths(claude_dir or CLAUDE_DIR):
        if f"{source}:{d.name}" == skill_id:
            content = (d / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            meta = _frontmatter(content)
            return {"id": skill_id, "name": meta.get("name", d.name),
                    "source": source, "description": meta.get("description", ""),
                    "path": str(d), "body": _strip_frontmatter(content),
                    "content": content}
    return None


# ── Skills management (filesystem + claude plugin CLI, zero model tokens) ──
_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._/-]*$")


def delete_skill(skill_id: str, claude_dir=None):
    """Delete a personal skill folder. Returns None on success, error string otherwise."""
    import shutil as sh
    cd = claude_dir or CLAUDE_DIR
    if not skill_id.startswith("personal:"):
        return "only personal skills can be deleted; plugins: uninstall the plugin"
    name = skill_id.split(":", 1)[1]
    root = (cd / "skills").resolve()
    target = (root / name).resolve()
    if target.parent != root or not (target / "SKILL.md").is_file():
        return "skill not found"
    sh.rmtree(target)
    return None


def export_skill_zip(skill_id: str, claude_dir=None):
    """Zip a skill folder (personal or plugin). Returns bytes or None."""
    import io
    import zipfile
    for source, d in _skill_paths(claude_dir or CLAUDE_DIR):
        if f"{source}:{d.name}" == skill_id:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted(d.rglob("*")):
                    if f.is_file():
                        z.write(f, f"{d.name}/{f.relative_to(d)}")
            return buf.getvalue()
    return None


def plugin_cmd(action: str, plugin: str) -> dict:
    """Run `claude plugin <action> <plugin>` — package ops only, no model tokens."""
    import shutil as sh
    import subprocess as sp
    if action not in ("install", "uninstall", "update"):
        return {"error": "action must be install, uninstall or update"}
    if not _PLUGIN_NAME_RE.fullmatch(plugin or ""):
        return {"error": "invalid plugin name"}
    exe = sh.which("claude")
    if not exe:
        return {"error": "claude CLI not found on PATH"}
    try:
        r = sp.run([exe, "plugin", action, plugin],
                   capture_output=True, text=True, timeout=300)
    except sp.TimeoutExpired:
        return {"error": "claude plugin command timed out"}
    out = (r.stdout + "\n" + r.stderr).strip()[-800:]
    return {"ok": True, "output": out} if r.returncode == 0 else {"error": out or f"exit {r.returncode}"}


# ── Modular ~/.claude config sync (rides the same git push/pull) ────────
CONFIG_MODULES: dict[str, tuple[str, ...]] = {
    "claude-md": ("CLAUDE.md",),
    "settings": ("settings.json",),
    "keybindings": ("keybindings.json",),
    "skills": ("skills",),
    "agents": ("agents",),
    "hooks": ("hooks",),
    "plugins": (),  # manifest-based, not file-copy: see export/apply_plugins
}
KNOWLEDGE_CONFIG = Path(__file__).parent.parent / "knowledge" / "config"
SYNC_PREFS = CLAUDE_DIR / "sto-sync.json"  # per-machine: which modules sync
# never synced, ever: credentials and machine-local settings
CONFIG_EXCLUDE = {".credentials.json", "settings.local.json", "__pycache__",
                  ".DS_Store", "node_modules", ".sto-backup"}
_TEXT_EXT = {".md", ".json", ".txt", ".yaml", ".yml", ".toml",
             ".js", ".mjs", ".cjs", ".ts", ".py", ".ps1", ".sh"}


def get_sync_prefs() -> list[str]:
    try:
        mods = json.loads(SYNC_PREFS.read_text(encoding="utf-8")).get("modules", [])
        return [m for m in mods if m in CONFIG_MODULES]
    except (OSError, ValueError):
        return []


def set_sync_prefs(modules: list[str]) -> list[str]:
    mods = [m for m in modules if m in CONFIG_MODULES]
    SYNC_PREFS.write_text(json.dumps({"modules": mods}, indent=1), encoding="utf-8")
    return mods


def _home_variants(home: str) -> list[str]:
    fwd, back = home.replace("\\", "/"), home.replace("/", "\\")
    return [back.replace("\\", "\\\\"), back, fwd]  # json-escaped first (longest match)


def _tokenize(text: str, home: str) -> str:
    for v in _home_variants(home):
        text = text.replace(v, "{{HOME}}")
    return text


def _detokenize(text: str, home: str) -> str:
    """`{{HOME}}` → this machine's home, written the way the file writes paths.

    The asymmetry with `_tokenize` is what corrupted settings.json on every
    pull: the export matches the JSON-escaped `C:\\\\Users\\\\x` form first (it is
    the longest variant), but the import pasted back the raw `C:\\Users\\x` —
    and `\\U` is not a legal JSON escape, so the file stopped parsing and
    Claude Code silently fell back to its defaults.

    The character right after the token says which form the file is in: a
    doubled backslash means the surrounding text is escaped (JSON, or a JSON
    block inside a .md), so the home has to be escaped too. Anything else —
    `\\` on its own in a .ps1, `/` anywhere — takes the path verbatim.
    """
    token, esc = "{{HOME}}", home.replace("\\", "\\\\")
    out, i = [], 0
    while (j := text.find(token, i)) != -1:
        out.append(text[i:j])
        i = j + len(token)
        out.append(esc if text.startswith("\\\\", i) else home)
    out.append(text[i:])
    return "".join(out)


def _module_files(base: Path, module: str):
    """Yield (abs_path, rel_path_from_base) for a module's existing files."""
    for entry in CONFIG_MODULES[module]:
        p = base / entry
        if p.is_file() and p.name not in CONFIG_EXCLUDE:
            yield p, Path(entry)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not (set(f.relative_to(base).parts) & CONFIG_EXCLUDE):
                    yield f, f.relative_to(base)


def _same(target: Path, text: str | None, blob: bytes | None) -> bool:
    """Is `target` already exactly what we were about to write?

    Skipping the identical write is not only speed (149 skill files got
    rewritten byte-for-byte on every single export): rewriting bumps the mtime,
    and mtime is what `export_memory` and the git preview use as change
    detector.
    """
    try:
        if text is not None:
            return target.read_text(encoding="utf-8", errors="replace") == text
        return target.read_bytes() == blob
    except OSError:
        return False


def export_config(modules, claude_dir=None, repo_config=None, home=None,
                  dry=False) -> int:
    """Copy enabled config modules into knowledge/config/<module>/, home paths
    tokenized as {{HOME}}, secrets redacted. Returns files written.

    `dry=True` writes nothing and returns how many files *would* change — that
    is what the home preview needs to say "this push carries 3 config files"
    without touching the disk on every repaint.
    """
    cd = claude_dir or CLAUDE_DIR
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    home = home or str(Path.home())
    written = 0
    for m in modules:
        if m not in CONFIG_MODULES:
            continue
        if m == "plugins":
            written += export_plugins(claude_dir=cd, repo_config=cfg, dry=dry)
            continue
        dest_root = cfg / m
        for f, rel in _module_files(cd, m):
            out = dest_root / rel
            text = blob = None
            if f.suffix.lower() in _TEXT_EXT:
                text = dx._redact(_tokenize(f.read_text(encoding="utf-8", errors="replace"), home))
            else:
                blob = f.read_bytes()
            if _same(out, text, blob):
                continue
            written += 1
            if dry:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            if text is not None:
                out.write_text(text, encoding="utf-8")
            else:
                out.write_bytes(blob)
    return written


def apply_config(modules, claude_dir=None, repo_config=None, home=None,
                 dry=False) -> int:
    """Write repo config modules into ~/.claude, {{HOME}} resolved for THIS
    machine. Existing files are backed up under ~/.claude/.sto-backup/<ts>/.

    `dry=True` writes nothing and returns how many files a pull would actually
    activate on this machine. That number is the whole point of the PULL
    button: `git` being up to date says nothing about whether the skills and
    plugins the repo carries are installed *here*.
    """
    import shutil as sh
    from datetime import datetime
    cd = claude_dir or CLAUDE_DIR
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    home = home or str(Path.home())
    backup = cd / ".sto-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
    applied = 0
    for m in modules:
        if m == "plugins":
            applied += apply_plugins(claude_dir=cd, repo_config=cfg, dry=dry)
            continue
        src_root = cfg / m
        if m not in CONFIG_MODULES or not src_root.is_dir():
            continue
        for f in sorted(src_root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src_root)
            target = cd / rel
            text = blob = None
            if f.suffix.lower() in _TEXT_EXT:
                text = _detokenize(f.read_text(encoding="utf-8", errors="replace"), home)
            else:
                blob = f.read_bytes()
            if _same(target, text, blob):
                continue
            applied += 1
            if dry:
                continue
            if target.exists():
                bpath = backup / rel
                bpath.parent.mkdir(parents=True, exist_ok=True)
                sh.copy2(target, bpath)
            target.parent.mkdir(parents=True, exist_ok=True)
            if text is not None:
                target.write_text(text, encoding="utf-8")
            else:
                target.write_bytes(blob)
    return applied


def count_skills(base: Path) -> int:
    """Skills under `base`, counted as skills and not as files.

    A skill is a folder with a `SKILL.md`; the references, scripts and assets
    beside it are its insides. Counting files said `159 local · 159 in repo`
    on the home while opening the same module listed 32 — the same word for
    two different units, which reads as a bug in the sync.
    """
    d = base / "skills"
    return sum(1 for _ in d.glob("*/SKILL.md")) if d.is_dir() else 0


def config_status(claude_dir=None, repo_config=None) -> list[dict]:
    cd = claude_dir or CLAUDE_DIR
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    enabled = set(get_sync_prefs())
    out = []
    for m in CONFIG_MODULES:
        # plugins already counted plugins and skills counted files: both rows
        # are read as "how many of these do I have", so both count their own unit
        if m == "plugins":
            local = len(_local_plugins(cd)[1])
            repo_n = len(_repo_plugins(cfg)[1])
        elif m == "skills":
            local, repo_n = count_skills(cd), count_skills(cfg / m)
        else:
            local = sum(1 for _ in _module_files(cd, m))
            repo_n = sum(1 for f in (cfg / m).rglob("*") if f.is_file()) if (cfg / m).is_dir() else 0
        out.append({"id": m, "localFiles": local, "repoFiles": repo_n, "enabled": m in enabled})
    return out


# ── Plugins module: sync the plugin LIST, reinstall via `claude plugin` ──
# Copying ~/.claude/plugins wholesale would ship machine-absolute installPaths
# and megabytes of cache; instead the manifest (marketplaces + plugin ids)
# travels, and pull installs whatever is missing with the claude CLI.

def _local_plugins(claude_dir=None) -> tuple[dict, list[str]]:
    """(marketplaces {name: github repo}, installed plugin ids name@marketplace)."""
    cd = claude_dir or CLAUDE_DIR
    marketplaces: dict[str, str] = {}
    try:
        d = json.loads((cd / "plugins" / "known_marketplaces.json").read_text(encoding="utf-8"))
        for name, info in d.items():
            src = (info or {}).get("source") or {}
            if src.get("source") == "github" and src.get("repo"):
                marketplaces[name] = src["repo"]
    except (OSError, ValueError):
        pass
    plugins: list[str] = []
    try:
        d = json.loads((cd / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        plugins = sorted(d.get("plugins", {}))
    except (OSError, ValueError):
        pass
    return marketplaces, plugins


def _repo_plugins(repo_config=None) -> tuple[dict, list[str]]:
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    try:
        d = json.loads((cfg / "plugins" / "plugins.json").read_text(encoding="utf-8"))
        return dict(d.get("marketplaces", {})), list(d.get("plugins", []))
    except (OSError, ValueError):
        return {}, []


def export_plugins(claude_dir=None, repo_config=None, dry=False) -> int:
    """Write the local plugin manifest into knowledge/config/plugins/. 1 file."""
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    marketplaces, plugins = _local_plugins(claude_dir)
    if not marketplaces and not plugins:
        return 0
    out = cfg / "plugins" / "plugins.json"
    text = json.dumps({"marketplaces": marketplaces, "plugins": plugins}, indent=1)
    if _same(out, text, None):
        return 0
    if dry:
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return 1


def plugins_to_apply(claude_dir=None, repo_config=None) -> tuple[dict, list[str]]:
    """(marketplaces to add, plugins to install): in the repo manifest, missing locally."""
    local_mk, local_pl = _local_plugins(claude_dir)
    repo_mk, repo_pl = _repo_plugins(repo_config)
    missing_mk = {k: v for k, v in repo_mk.items() if k not in local_mk}
    missing_pl = [p for p in repo_pl if p not in set(local_pl)]
    return missing_mk, missing_pl


def _claude_plugin(*args) -> bool:
    import shutil as sh
    import subprocess as sp
    exe = sh.which("claude")
    if not exe:
        return False
    try:
        return sp.run([exe, "plugin", *args], capture_output=True,
                      text=True, timeout=300).returncode == 0
    except (OSError, sp.TimeoutExpired):
        return False


def apply_plugins(claude_dir=None, repo_config=None, runner=None, dry=False) -> int:
    """Install repo-manifest plugins missing on this machine. Returns installs.
    Never uninstalls: extra local plugins are left alone."""
    run = runner or _claude_plugin
    missing_mk, missing_pl = plugins_to_apply(claude_dir, repo_config)
    if dry:
        return len(missing_pl)
    for repo in missing_mk.values():
        run("marketplace", "add", repo)
    return sum(1 for p in missing_pl if run("install", p))


# ── Knowledge sync (git-based, zero tokens) ─────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
EXPORT_MAX_BYTES = 10 * 1024 * 1024
# A session Claude Code is writing to right now grows again the second after the
# push that carried it, so every push produced one more file for the other
# machine to pull, and no machine was ever "up to date". Let a session sit still
# before exporting it. ponytail: two minutes of wall clock, not a lock on the
# file — the session you are in is written to on every message, and one that is
# really over travels on the next push.
EXPORT_SETTLE = 120


def _git(*args, timeout=120):
    import subprocess as sp
    try:
        r = sp.run(["git", "-C", str(REPO_ROOT), *args],
                   capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout.strip() + ("\n" + r.stderr.strip() if r.stderr.strip() else "")).strip()
    except (OSError, Exception) as e:  # git missing / timeout
        return 1, str(e)


def _trim_session_line(line: str):
    """Reduce one .jsonl line to what the chat viewer renders (redacted).

    Keeps: user/assistant text, tool_use name + detail keys, error results.
    Drops: images, tool outputs, metadata lines. Returns None to skip."""
    try:
        o = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if o.get("type") not in ("user", "assistant") or not isinstance(o.get("message"), dict):
        return None
    msg = o["message"]
    content = msg.get("content")
    if isinstance(content, str):
        new_content = dx._redact(content)
    elif isinstance(content, list):
        new_content = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and b.get("text"):
                new_content.append({"type": "text", "text": dx._redact(b["text"])})
            elif t == "tool_use" and b.get("name"):
                slim = {k: v[:1000] for k, v in _tool_input_slim(b.get("input")).items()}
                new_content.append({"type": "tool_use", "name": b["name"], "input": slim})
            elif t == "tool_result" and b.get("is_error"):
                new_content.append({"type": "tool_result", "is_error": True,
                                    "content": dx._redact(_block_text(b.get("content"))[:ERROR_SNIPPET_CAP])})
        if not new_content:
            return None
    else:
        return None
    return json.dumps({"type": o["type"], "message": {"role": msg.get("role"), "content": new_content}},
                      ensure_ascii=False)


def export_sessions(projects_dir=None, dest=None) -> int:
    """Write trimmed, redacted copies of prompt-bearing local sessions into
    knowledge/sessions/<machine>/. Skips unchanged files. Returns files written."""
    dest = dest if dest is not None else KNOWLEDGE_SESSIONS / LOCAL_MACHINE
    pd = projects_dir or dx.PROJECTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    now = time.time()
    (dest / "machine.json").write_text(  # device identity for other machines' UIs
        json.dumps({"name": dest.name, "type": machine_type()}), encoding="utf-8")
    written = 0
    for _, p in dx.find_sessions(None, projects_dir=pd, max_sessions=MAX_SESSIONS):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size > EXPORT_MAX_BYTES:
            continue  # ponytail: giant sessions stay local
        if now - st.st_mtime < EXPORT_SETTLE:
            continue  # still being written
        meta = session_meta(p)  # parses every file each push; fine at ≤500 sessions
        if meta["n_prompts"] == 0:
            continue
        out = dest / meta["project"] / p.name
        if out.exists() and out.stat().st_mtime >= st.st_mtime:
            continue
        lines = []
        with p.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    trimmed = _trim_session_line(line)
                    if trimmed:
                        lines.append(trimmed)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(out, (st.st_atime, st.st_mtime))  # keep mtime for change detection
        written += 1
    return written


# ---------- per-project memory (cross-machine) ----------

KNOWLEDGE_MEMORY = REPO_ROOT / "knowledge" / "memory"
_MEMORY_TYPE_RE = re.compile(r"^\s+type:\s*(\S+)\s*$", re.M)


def _memory_meta(text: str) -> dict:
    """name/description/type of a native Claude Code memory.

    `type` lives nested under `metadata:`, which _frontmatter() does not descend
    into; a regex over the frontmatter block pulls it out."""
    fm = _frontmatter(text)
    block = text.split("---")[1] if text.startswith("---") else ""
    m = _MEMORY_TYPE_RE.search(block)
    return {"name": fm.get("name", "").strip("\"'"),
            "description": fm.get("description", "").strip("\"'"),
            "type": m.group(1) if m else ""}


_STO_PROJECT_MARKER = ".sto-project"


# The separators Claude Code collapses into `-`. Whether it also collapses a
# dot is not something any project here can prove, so `_encodings` offers both
# readings instead of betting on one.
_SLUG_SEP = re.compile(r"[ /\\:]")
_SLUG_SEP_DOT = re.compile(r"[ /\\:.]")


def _slug_project(slug_dir: Path) -> str:
    """Cross-machine identity of ~/.claude/projects/<slug>/.

    The slug is an encoded path that cannot be decoded (`:`, `\\` and spaces all
    collapse into `-`), so the identity comes from the `cwd` of a sibling
    session, which is exactly what project_name() already consumes.

    The first successful resolution is persisted to `<slug_dir>/.sto-project`.
    It is needed because Claude Code prunes old `.jsonl` files
    (`cleanupPeriodDays`, 30 days by default) but keeps `memory/`: without the
    marker, every dormant project would end up falling back to the raw slug as
    soon as its sessions were gone, even if its identity had been resolved
    before.

    When the sessions are gone AND there is no marker, the slug is decoded back
    into a real path (`_decode_slug`) and that path is asked for its identity.
    That is the case that used to lose: Claude Code prunes transcripts at 30
    days, so any project you have not opened in a month became its own raw slug
    — and since the slug carries the machine's path, the same project on two
    machines stopped being the same project and their memories never merged.

    ponytail: the marker is authoritative — if the real identity changes (say a
    git remote is added after the first resolution), `.sto-project` has to be
    deleted by hand for it to resolve again."""
    marker = slug_dir / _STO_PROJECT_MARKER
    if marker.exists():
        name = marker.read_text(encoding="utf-8", errors="replace").strip()
        if name:
            return name
    for jsonl in sorted(slug_dir.glob("*.jsonl")):
        cwd = ""
        try:
            with jsonl.open(encoding="utf-8", errors="replace") as fh:
                for _ in range(20):  # cwd shows up in almost every line
                    line = fh.readline()
                    if not line:
                        break
                    try:
                        cwd = json.loads(line).get("cwd") or ""
                    except (json.JSONDecodeError, ValueError, AttributeError):
                        continue
                    if cwd:
                        break
        except OSError:
            continue
        if cwd:
            return _remember_project(marker, project_name(jsonl, cwd))
    path = _decode_slug(slug_dir.name)
    if path is not None:
        return _remember_project(marker, project_name(path / "x", str(path)))
    return slug_dir.name


def _remember_project(marker: Path, name: str) -> str:
    try:
        marker.write_text(name, encoding="utf-8")
    except OSError:
        pass  # ponytail: without the marker it resolves again next time
    return name


def _encodings(name: str) -> list[str]:
    """How this directory name could appear inside a slug. The dot-keeping
    reading comes first, so it wins when both would match."""
    out = [_SLUG_SEP.sub("-", name)]
    dotted = _SLUG_SEP_DOT.sub("-", name)
    if dotted != out[0]:
        out.append(dotted)
    return out


def _decode_slug(slug: str) -> Path | None:
    """The slug back into the real directory, or None if it is not on this disk.

    Claude Code builds the slug by collapsing every separator, space and dot of
    the absolute path into `-`, which is not reversible on its own: nothing in
    `Web-App-Projects` says where a folder ends. So instead of parsing it, walk
    the filesystem — at each level the children are the only candidates, and
    encoding a real name back is exact. Longest first, so `OneDrive - UTN FRLP`
    wins over a sibling called `OneDrive`.

    Only ever called for a project whose transcripts are gone, and the answer
    is written to `.sto-project`, so the directory walk happens once.
    """
    m = re.match(r"^([A-Za-z])--", slug)
    if m:
        cur, rest = Path(m.group(1) + ":/"), slug[m.end():]
    elif slug.startswith("-"):
        cur, rest = Path("/"), slug[1:]
    else:
        return None                      # not a path-shaped slug
    while rest:
        try:
            kids = sorted((k for k in cur.iterdir() if k.is_dir()),
                          key=lambda k: -len(k.name))
        except OSError:
            return None                  # gone, or not ours to read
        for child in kids:
            hit = next((e for e in _encodings(child.name)
                        if rest == e or rest.startswith(e + "-")), None)
            if hit is None:
                continue
            if rest == hit:
                return child
            cur, rest = child, rest[len(hit) + 1:]
            break
        else:
            return None                  # the path does not exist here
    return cur


def _memory_dirs(projects_dir=None) -> dict[str, list[Path]]:
    """project → [local memory/ directories that belong to it].

    It is a list and not a single path because one project can have several
    slugs on the same machine (opening the repo and a subfolder of it gives two
    slugs with the same git remote)."""
    pd = projects_dir or dx.PROJECTS_DIR
    out: dict[str, list[Path]] = {}
    if not pd.exists():
        return out
    for slug in sorted(pd.iterdir()):
        mem = slug / "memory"
        if slug.is_dir() and mem.is_dir():
            out.setdefault(_slug_project(slug), []).append(mem)
    return out


def _newest(dirs) -> dict[str, Path]:
    """file name → the newest copy across several directories.

    Excludes MEMORY.md: it is a derived index, rebuilt locally."""
    best: dict[str, Path] = {}
    for d in dirs:
        for f in d.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            cur = best.get(f.name)
            if cur is None or f.stat().st_mtime > cur.stat().st_mtime:
                best[f.name] = f
    return best


def export_memory(projects_dir=None, dest=None, dry=False) -> int:
    """Mirror the local memory into knowledge/memory/<project>/<machine>/.

    A real mirror (it deletes what is no longer local) but scoped to this
    machine's folder, so it cannot destroy what another one learned.

    `dry=True` writes nothing and returns how many memories a push would carry.
    Without it the home preview showed 0 memories until you actually pressed
    `p`: nothing is dirty in git until the export has run.
    """
    root = dest if dest is not None else KNOWLEDGE_MEMORY
    written = 0
    for project, dirs in _memory_dirs(projects_dir).items():
        # ponytail: the union of every slug of the project. Deleting a memory
        # in one slug is not enough: the union revives it. Delete it in both.
        src = _newest(dirs)
        if not src:
            continue  # no real memories: do not create an empty folder
        out = root / project / LOCAL_MACHINE
        if not dry:
            out.mkdir(parents=True, exist_ok=True)
        for f in out.glob("*.md"):
            if f.name not in src:
                written += 1          # a deletion travels too
                if not dry:
                    f.unlink()
        for name, f in src.items():
            st = f.stat()
            tgt = out / name
            if tgt.exists() and tgt.stat().st_mtime >= st.st_mtime:
                continue
            written += 1
            if dry:
                continue
            tgt.write_text(dx._redact(f.read_text(encoding="utf-8", errors="replace")),
                           encoding="utf-8")
            os.utime(tgt, (st.st_atime, st.st_mtime))  # mtime = detector de cambio
    return written


def import_memory(projects_dir=None, src=None, dry=False) -> int:
    """Merge knowledge/memory/<project>/*/ into the local memory. Returns writes.

    `dry=True` writes nothing and returns how many memories a pull would land
    on this machine — the number the PULL button needs, since a repo that is
    up to date in git can still be holding memories this machine never got.

    It does not decide "newest mtime wins" between local and remote: git does
    not preserve mtimes, so a file arriving through a merge/checkout is stamped
    with the checkout time and can look newer than a local memory Claude just
    wrote. Instead it compares every file against the last thing THIS machine
    published (knowledge/memory/<project>/<LOCAL_MACHINE>/), which is a stable
    merge base and does not depend on filesystem clocks. `_newest` is still used
    only to pick between copies from *other* machines, remote-vs-remote, where
    the worst that can happen is preferring the other one."""
    root = src if src is not None else KNOWLEDGE_MEMORY
    if not root.exists():
        return 0
    local = _memory_dirs(projects_dir)
    written = 0
    for pdir in sorted(root.iterdir()):
        if not pdir.is_dir():
            continue
        targets = local.get(pdir.name)
        if not targets:
            # ponytail: a project with no local slug (never opened here). It
            # materialises on the first pull after opening it once.
            continue
        mine_dir = pdir / LOCAL_MACHINE
        best = _newest([m for m in sorted(pdir.iterdir()) if m.is_dir()])
        for name, f in best.items():
            win_text = f.read_text(encoding="utf-8", errors="replace")
            mine_file = mine_dir / name
            # mine_text already comes redacted from the repo (export_memory
            # wrote it); no need to run it through dx._redact() again.
            mine_text = (mine_file.read_text(encoding="utf-8", errors="replace")
                         if mine_file.exists() else None)
            st = f.stat()
            for t in targets:
                tgt = t / name
                if tgt.exists():
                    # ponytail: if the local memory holds a secret-shaped
                    # string, dx._redact() masks it and this comparison will
                    # never match the remote (already redacted) -> that file
                    # stops being updated from other machines. Safe side: better
                    # stale than overwritten with redacted data.
                    tgt_text = dx._redact(tgt.read_text(encoding="utf-8", errors="replace"))
                    if tgt_text == win_text:
                        continue  # identical: no churn
                    if mine_text is None:
                        continue  # local work not published yet: not overwritten
                    if tgt_text != mine_text:
                        continue  # diverged since my last push; it goes out on the next one
                else:
                    if mine_file.exists():
                        continue  # deliberate local delete: not resurrected
                written += 1
                if dry:
                    continue
                tgt.write_text(win_text, encoding="utf-8")
                os.utime(tgt, (st.st_atime, st.st_mtime))
    return written


_INDEX_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)")


def rebuild_index(memory_dir: Path) -> None:
    """Rebuild MEMORY.md keeping whatever was already there.

    MEMORY.md is not synced: each machine's index would only cover its own
    subset. It is rebuilt locally: existing lines are kept as they are (heading
    and prose included), the ones pointing at files that are gone are dropped,
    and the memories that arrived from other machines are added."""
    files = {f.name for f in memory_dir.glob("*.md") if f.name != "MEMORY.md"}
    idx = memory_dir / "MEMORY.md"
    if not files and not idx.exists():
        return  # empty memory folder: do not seed an empty index
    lines, seen = [], set()
    if idx.exists():
        for line in idx.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _INDEX_LINK_RE.search(line)
            if m is None:
                lines.append(line)  # heading, prose, blank lines
            elif m.group(1) in files:
                lines.append(line)
                seen.add(m.group(1))
    else:
        lines = ["# Memory Index", ""]
    for name in sorted(files - seen):
        meta = _memory_meta((memory_dir / name).read_text(encoding="utf-8", errors="replace"))
        title = meta["name"] or name.removesuffix(".md")
        desc = f" — {meta['description']}" if meta["description"] else ""
        lines.append(f"- [{title}]({name}){desc}")
    # newline="\n": without this Windows translates to CRLF and rewrites the
    # bytes of every MEMORY.md on every pull, even when the content is identical.
    idx.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def repair_memory(projects_dir=None, src=None, dry=False) -> list[dict]:
    """Re-file memories filed under a raw slug instead of a project identity.

    Only fixes what THIS machine can resolve — a folder holding another
    machine's path decodes to nothing here, and repairing it is that machine's
    job. Running it on both is what makes the two halves meet.

    Returns [{from, to, files}]; `dry=True` decides nothing and moves nothing.
    """
    root = src if src is not None else KNOWLEDGE_MEMORY
    moves: list[dict] = []
    if not root.exists():
        return moves
    # the local markers first: without them the next export writes the old name
    # straight back and the repair undoes itself
    for slug in sorted((projects_dir or dx.PROJECTS_DIR).iterdir()
                       if (projects_dir or dx.PROJECTS_DIR).exists() else []):
        if slug.is_dir() and (slug / "memory").is_dir() and not dry:
            _slug_project(slug)
    for pdir in sorted(root.iterdir()):
        if not pdir.is_dir():
            continue
        path = _decode_slug(pdir.name)
        if path is None:
            continue                      # not a slug, or not a path on this disk
        name = project_name(path / "_", str(path))
        if name == pdir.name or not name:
            continue                      # already filed under its identity
        files = [f for m in pdir.iterdir() if m.is_dir() for f in m.glob("*.md")]
        moves.append({"from": pdir.name, "to": name, "files": len(files)})
        if dry:
            continue
        for mdir in sorted(x for x in pdir.iterdir() if x.is_dir()):
            dest = root / name / mdir.name
            dest.mkdir(parents=True, exist_ok=True)
            for f in sorted(mdir.glob("*.md")):
                target = dest / f.name
                # ponytail: never clobber. A same-named memory already filed
                # under the real identity is the newer story; the slug copy is
                # what got stranded.
                if not target.exists():
                    f.replace(target)
                else:
                    f.unlink()
            for leftover in mdir.iterdir():
                leftover.unlink()
            mdir.rmdir()
        pdir.rmdir()
    return moves


def list_memory(src=None) -> list[dict]:
    """Repo memories grouped by project. Source for the CLI and /api/memory."""
    root = src if src is not None else KNOWLEDGE_MEMORY
    out = []
    if not root.exists():
        return out
    for pdir in sorted(root.iterdir()):
        if not pdir.is_dir():
            continue
        items = []
        for mdir in sorted(pdir.iterdir()):
            if not mdir.is_dir():
                continue
            for f in sorted(mdir.glob("*.md")):
                meta = _memory_meta(f.read_text(encoding="utf-8", errors="replace"))
                items.append({"slug": f.stem, "type": meta["type"], "machine": mdir.name,
                              "mtime": f.stat().st_mtime,
                              "description": meta["description"] or meta["name"]})
        if items:
            out.append({"project": pdir.name,
                        "machines": sorted({i["machine"] for i in items}),
                        "count": len(items), "memories": items})
    return out


# ── forget: stop carrying something in the repo ─────────────────────────
# chezmoi ships four removal verbs and deprecated its ambiguous `remove` in
# favour of `forget` (repo only) and `destroy` (repo + disk). We take the same
# split: `forget` never touches ~/.claude, so a slip on the wrong row costs a
# push, not your work. The local half already exists as `delete_skill`.

FORGET_KINDS = ("skill", "config", "plugin", "memory")


_DROPPED = {"ts": 0.0, "data": None}
DROPPED_TTL = 60.0     # seconds; one `git log` per minute, not per repaint


def dropped_skills(limit=400, force=False):
    """Skill names the repo used to carry and a commit removed.

    This is the fourth parity state, and the only one that is not on disk:
    a skill you have locally but the repo does not can mean two opposite
    things — you just wrote it and never pushed, or another machine dropped
    it and you pulled the deletion. They looked identical, which is exactly
    what a tombstone file is usually invented for. Git already recorded it,
    so `--diff-filter=D` answers for free and nothing new has to be kept in
    sync (see `forget`).

    Names re-added later are excluded by the caller, which only asks about
    skills that are absent from the repo right now.
    """
    import time
    if not force and _DROPPED["data"] is not None and \
            time.monotonic() - _DROPPED["ts"] < DROPPED_TTL:
        return _DROPPED["data"]
    code, out = _git("log", f"-{limit}", "--diff-filter=D", "--name-only",
                     "--format=", "--", "knowledge/config/skills/skills", timeout=20)
    names = set()
    if code == 0:
        for line in out.splitlines():
            parts = line.strip().split("/")
            # knowledge/config/skills/skills/<name>/…
            if len(parts) > 5 and parts[:4] == ["knowledge", "config", "skills", "skills"]:
                names.add(parts[4])
    _DROPPED["data"], _DROPPED["ts"] = names, time.monotonic()
    return names


def _forget_rel(p: Path) -> str:
    """Repo-relative when it is inside the repo, absolute otherwise (tests
    point the domains at temp dirs, and a manifest is for reading anyway)."""
    try:
        return str(p.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def _forget_paths(kind, name, cfg, mem):
    """Repo paths a target owns, or (None, error)."""
    if kind == "skill":
        root = (cfg / "skills" / "skills").resolve()
        target = (root / name).resolve()
        if target.parent != root or not (target / "SKILL.md").is_file():
            return None, f"skill not in repo: {name}"
        return [target], None
    if kind == "config":
        if name not in CONFIG_MODULES:
            return None, f"unknown config module: {name}"
        target = cfg / name
        if not target.is_dir():
            return None, f"module not in repo: {name}"
        return [target], None
    if kind == "memory":
        root = mem.resolve()
        target = (root / name).resolve()
        # name is <project>/<machine>/<slug>; anything shorter or climbing out
        # of the tree is a caller bug, not a memory
        if len(Path(name).parts) != 3 or root not in target.parents:
            return None, f"expected <project>/<machine>/<slug>: {name}"
        target = target.with_suffix(".md")
        if not target.is_file():
            return None, f"memory not in repo: {name}"
        return [target], None
    return None, f"unknown kind: {kind}"


def _forget_guard(kind, name, cd, mem):
    """Refuse when the export would just put it back on the next push.

    `sync_stage` runs `export_config`/`export_memory` *before* it stages, so
    forgetting something this machine still has locally is undone within the
    same push — silently, which is the worst way to fail.
    """
    if kind == "skill" and (cd / "skills" / name / "SKILL.md").is_file():
        return (f"{name} is still installed here, and the next push would "
                f"export it again — uninstall it locally first")
    if kind == "config" and any(True for _ in _module_files(cd, name)):
        return (f"module {name} still has local files, and the next push would "
                f"export them again — untick it in the config tab first")
    if kind == "plugin":
        if name in set(_local_plugins(cd)[1]):
            return (f"{name} is still installed here, and the next push would "
                    f"export it again — uninstall the plugin first")
    if kind == "memory":
        project, machine, slug = Path(name).parts
        dirs = _memory_dirs().get(project, [])
        if machine == LOCAL_MACHINE and dirs and f"{slug}.md" in _newest(dirs):
            # export_memory already mirrors deletions for THIS machine's folder,
            # so the supported move is to delete it locally and push. Forget is
            # for the other machines' folders, which no export of ours touches.
            return (f"{slug} still exists in this machine's memory — delete it "
                    f"there and push, which already removes it from the repo")
    return None


def forget(target, apply=False, claude_dir=None, repo_config=None, repo_memory=None):
    """Stop carrying `target` in the repo. The local copy is never touched.

    `target` is `<kind>:<name>` over the four synced domains — `skill:code-review`,
    `config:agents`, `plugin:caveman@marketplace`,
    `memory:<project>/<machine>/<slug>`.

    Returns `(paths, error)` with repo-relative paths as strings. `apply=False`
    is a dry run so the caller can show the manifest before asking: nothing in
    this repo deletes without the user seeing the list first.

    The deletion reaches the remote on the next `sto push` — `sync_stage`
    already runs `git add -A`, which stages removals. The other machine keeps
    its copy and decides for itself; git history says which of the two happened
    (`git log --diff-filter=D`), so no tombstone file has to be invented.
    """
    import shutil as sh
    cd = claude_dir or CLAUDE_DIR
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    mem = repo_memory if repo_memory is not None else KNOWLEDGE_MEMORY
    kind, _, name = target.partition(":")
    if kind not in FORGET_KINDS or not name:
        return [], f"expected <kind>:<name> with kind in {'/'.join(FORGET_KINDS)}"

    if kind == "plugin":
        manifest = cfg / "plugins" / "plugins.json"
        marketplaces, plugins = _repo_plugins(cfg)
        if name not in plugins:
            return [], f"plugin not in repo: {name}"
        if err := _forget_guard(kind, name, cd, mem):
            return [], err
        rel = [_forget_rel(manifest) + f" ({name})"]
        if apply:
            plugins = [p for p in plugins if p != name]
            manifest.write_text(
                json.dumps({"marketplaces": marketplaces, "plugins": plugins},
                           indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return rel, None

    targets, err = _forget_paths(kind, name, cfg, mem)
    if err:
        return [], err
    if err := _forget_guard(kind, name, cd, mem):
        return [], err
    rel = []
    for t in targets:
        for f in ([t] if t.is_file() else sorted(x for x in t.rglob("*") if x.is_file())):
            rel.append(_forget_rel(f))
    if apply:
        for t in targets:
            sh.rmtree(t) if t.is_dir() else t.unlink()
    return rel, None


WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def _proj_label(slug: str) -> str:
    """A project slug is the flattened path; for the graph the tail is enough.

    `C--Users-x-Downloads-Web-App-Projects-honda-frelife-bot` → `honda-frelife-bot`.
    With no known marker, the last three pieces: the whole path does not fit
    next to a node.
    """
    for marker in ("-Projects-", "-Materias-", "-repos-", "-Documents-"):
        if marker in slug:
            return slug.split(marker)[-1]
    parts = slug.split("-")
    return "-".join(parts[-3:]) if len(parts) > 3 else slug


def memory_graph(src=None, bodies=False) -> dict:
    """The repo's memories as a graph: {nodes, links}.

    `bodies=True` carries each memory's full text on its node. The graph window
    is a single offline HTML file with no server behind it, so reading a memory
    there means the text travelled with the JSON — ~120 KB for a repo this
    size, which is nothing next to being able to actually read what you clicked.

    One node per memory and one per project. Edges: every memory hangs off its
    project, and every `[[wikilink]]` is a memory→memory edge. The link resolves
    inside the project first (which is how they are written) and, failing that,
    against the slug across the whole repo when it is unique: an `[[x]]`
    ambiguous between two projects says less than not drawing it.

    It is the same thing the push exported, so the graph covers every machine
    and every session, not only the one opening it.
    """
    root = src if src is not None else KNOWLEDGE_MEMORY
    nodes, links, per_project, global_slug = [], [], {}, {}
    for proj in list_memory(root):
        pid = "proj:" + proj["project"]
        nodes.append({"id": pid, "label": _proj_label(proj["project"]),
                      "kind": "project", "title": proj["project"],
                      "n": proj["count"], "machines": proj["machines"]})
        for m in proj["memories"]:
            mid = f"{proj['project']}/{m['slug']}"
            node = {"id": mid, "label": m["slug"], "kind": "memory",
                    "type": m["type"], "machine": m["machine"],
                    "project": proj["project"], "desc": m["description"],
                    "mtime": m["mtime"]}
            if bodies:
                f = root / proj["project"] / m["machine"] / f"{m['slug']}.md"
                try:
                    node["body"] = _strip_frontmatter(
                        f.read_text(encoding="utf-8", errors="replace")).strip()
                except OSError:
                    node["body"] = ""
            nodes.append(node)
            links.append({"source": mid, "target": pid, "kind": "in"})
            per_project.setdefault(proj["project"], {})[m["slug"]] = mid
            global_slug.setdefault(m["slug"], []).append(mid)
    # second pass: every slug is known by now, so the [[x]] links resolve
    for proj in list_memory(root):
        for m in proj["memories"]:
            mid = f"{proj['project']}/{m['slug']}"
            f = root / proj["project"] / m["machine"] / f"{m['slug']}.md"
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ref in {x.strip() for x in WIKILINK.findall(body)}:
                dest = per_project.get(proj["project"], {}).get(ref)
                if not dest:
                    cand = global_slug.get(ref) or []
                    dest = cand[0] if len(cand) == 1 else None
                if dest and dest != mid:
                    links.append({"source": mid, "target": dest, "kind": "link"})
    return {"nodes": nodes, "links": links,
            "machine": LOCAL_MACHINE,
            "counts": {"memories": sum(1 for n in nodes if n["kind"] == "memory"),
                       "projects": sum(1 for n in nodes if n["kind"] == "project"),
                       "links": sum(1 for l in links if l["kind"] == "link")}}


FETCH_TTL = 60  # seconds: a network round trip per `sto status` is the whole cost


def _stale_fetch_ref(ref: str, ttl=FETCH_TTL) -> bool:
    """Same idea as `_stale_fetch`, per remote: git touches the packed/loose
    ref file of a remote when it fetches it, so upstream and origin get their
    own clock instead of shadowing each other through FETCH_HEAD."""
    try:
        import time as _t
        code, out = _git("for-each-ref", "--format=%(refname)", ref)
        if code != 0 or not out.strip():
            return True
        stamps = [p.stat().st_mtime for p in
                  ((REPO_ROOT / ".git" / r.strip()) for r in out.splitlines() if r.strip())
                  if p.exists()]
        if not stamps:
            # `git gc` packs the loose refs away and runs on its own: without
            # this the answer was "stale" forever and the 30 min TTL turned
            # into a fetch on every home repaint.
            packed = REPO_ROOT / ".git" / "packed-refs"
            stamps = [packed.stat().st_mtime] if packed.exists() else []
        return not stamps or _t.time() - max(stamps) > ttl
    except (OSError, ValueError):
        return True


def _stale_fetch(ttl=FETCH_TTL) -> bool:
    """Has it been long enough since the last `git fetch` to bother again?

    git stamps .git/FETCH_HEAD on every fetch, so the answer is already on
    disk and survives process boundaries — which is what matters, since each
    `sto <cmd>` is a new process that used to fetch from scratch.

    ponytail: FETCH_HEAD is shared by every remote, so a fetch of `upstream`
    also holds origin off for a minute. One stat() beats the `for-each-ref`
    subprocess `_stale_fetch_ref` needs, and a 60 s window costs nobody
    anything — press `f` on the home if you want it now.
    """
    try:
        import time as _t
        return _t.time() - (REPO_ROOT / ".git" / "FETCH_HEAD").stat().st_mtime > ttl
    except OSError:
        return True


def sync_status(fetch=True, force=False) -> dict:
    """`force` skips the FETCH_TTL window: a fetch nobody asked for can wait a
    minute, but one somebody pressed a key for cannot — it would flash
    "fetching…" and show the same numbers back."""
    code, remote = _git("remote", "get-url", "origin")
    if code != 0:
        return {"remote": None, "branch": None, "ahead": 0, "behind": 0,
                "dirty": False, "machine": LOCAL_MACHINE, "fetchError": None}
    fetch_error = None
    if fetch and (force or _stale_fetch()):
        fcode, fout = _git("fetch", "--quiet", "origin")
        if fcode != 0:
            fetch_error = fout or "fetch failed"
    _, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    ahead = behind = 0
    code, counts = _git("rev-list", "--left-right", "--count", f"origin/{branch}...HEAD")
    if code == 0 and counts:
        try:
            behind, ahead = (int(x) for x in counts.split())
        except ValueError:
            pass
    _, porcelain = _git("status", "--porcelain")
    return {"remote": remote, "branch": branch, "ahead": ahead, "behind": behind,
            "dirty": bool(porcelain), "machine": LOCAL_MACHINE, "fetchError": fetch_error}


def _conflict_msg(out: str) -> str:
    """`git merge` prints one `Auto-merging <file>` line per file it touched and
    the CONFLICT lines last, so a truncated head of the output names everything
    except what actually broke. Keep the CONFLICT lines."""
    bad = [l.split(" in ", 1)[-1] for l in out.splitlines() if l.startswith("CONFLICT")]
    detail = ", ".join(bad) if bad else out[:400]
    return f"merge conflict, aborted: {detail}"


def sync_pull(progress=None) -> dict:
    """Same `progress` contract as `sync_push`."""
    say = progress or (lambda _step: None)
    say("s_fetch")
    st = sync_status()
    if not st["remote"]:
        return {"error": "no git remote configured"}
    if st["fetchError"]:
        return {"error": f"fetch failed: {st['fetchError']}"}
    if st["behind"] > 0:
        if st["dirty"]:
            return {"error": "working tree has uncommitted changes: commit or stash them first"}
        say("s_merge")
        code, out = _git("merge", "--no-edit", f"origin/{st['branch']}")
        if code != 0:
            _git("merge", "--abort")
            return {"error": _conflict_msg(out)}
    # apply_config runs whether or not there were commits to merge. Having the
    # latest bytes from GitHub is not the point of a pull: the point is that
    # this machine ends up with the same skills, plugins and settings actually
    # installed. A repo that is up to date can still be holding a skill this
    # machine never activated.
    say("s_apply")
    applied = apply_config(get_sync_prefs())
    # import_memory() always runs, even with no new commits to bring down: a
    # project with no local slug only materialises on the first pull after it is
    # opened, and with the repo up to date that pull never reached import_memory().
    say("s_import")
    imported = import_memory()
    for dirs in _memory_dirs().values():
        for d in dirs:
            rebuild_index(d)
    if st["behind"] == 0:
        msg = "already up to date"
        if applied:
            msg += f" · applied {applied} config file(s)"
        if imported:
            msg += f" · {imported} memoria(s)"
        return {"ok": True, "message": msg, "status": st}
    msg = f"pulled {st['behind']} commit(s)"
    if applied:
        msg += f" · applied {applied} config file(s)"
    if imported:
        msg += f" · {imported} memoria(s)"
    return {"ok": True, "message": msg, "status": sync_status(fetch=False)}


# ── The badge in Claude Code's status line ──────────────────────────────
# settings.json holds exactly one `statusLine`, so installing ours by
# overwriting is how somebody loses the badge they already had. Instead the
# command we install is a wrapper: it runs whatever was there, prints its
# output, and appends the STO badge. Turning it off puts the old one back.

UI_PREFS = CLAUDE_DIR / "sto-ui.json"
SETTINGS = CLAUDE_DIR / "settings.json"


def _ui_prefs() -> dict:
    try:
        return json.loads(UI_PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_ui_prefs(d: dict) -> None:
    try:
        UI_PREFS.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass


def statusline_cmd() -> str:
    return f'python "{Path(__file__).parent / "statusline.py"}"'


def badge_status() -> dict:
    """{on, other} — is the badge installed, and what it is chained in front of."""
    try:
        conf = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        conf = {}
    current = (conf.get("statusLine") or {}).get("command", "")
    return {"on": current == statusline_cmd(),
            "other": _ui_prefs().get("statusline_chain", "") if current == statusline_cmd()
            else current}


def set_badge(on: bool) -> dict:
    """Install or remove the badge, never losing the status line that was there."""
    try:
        conf = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except OSError:
        conf = {}
    except ValueError:
        return {"error": f"{SETTINGS} is not valid JSON"}
    mine, prefs = statusline_cmd(), _ui_prefs()
    current = (conf.get("statusLine") or {}).get("command", "")
    if on:
        if current != mine:
            prefs["statusline_chain"] = current   # "" when there was none
            _write_ui_prefs(prefs)
        conf["statusLine"] = {"type": "command", "command": mine}
    else:
        old = prefs.pop("statusline_chain", "")
        _write_ui_prefs(prefs)
        if old:
            conf["statusLine"] = {"type": "command", "command": old}
        else:
            conf.pop("statusLine", None)
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(conf, indent=2), encoding="utf-8")
    except OSError as e:
        return {"error": str(e)}
    return {"ok": True, "on": on}


# ── Updates from upstream (the OS itself, not your knowledge) ───────────
# `origin` is YOUR repo: code plus the knowledge only you have. `upstream` is
# where the OS is published. Keeping them apart is what makes an update safe:
# upstream has never held a single file under knowledge/memory, so a merge
# cannot touch your memories — git has nothing to bring there.

UPSTREAM_URL = os.environ.get(
    "STO_UPSTREAM", "https://github.com/SimonOcampo1/braingent-sto.git")
UPSTREAM = "upstream"


def _upstream_url() -> str:
    """The configured `upstream`, or the published one if there is none yet."""
    code, url = _git("remote", "get-url", UPSTREAM)
    return url.strip() if code == 0 and url.strip() else UPSTREAM_URL


def _upstream_branch() -> str:
    code, out = _git("rev-parse", "--abbrev-ref", f"{UPSTREAM}/HEAD")
    name = out.strip().split("/")[-1] if code == 0 else ""
    return name or "main"


def update_status(fetch=True, force=False) -> dict:
    """{available, url, linked, log, error} — how far behind the OS you are.

    `linked` is false when your repo and upstream share no commit: that is the
    case for a repo that was copied instead of forked, and until it is grafted
    once (`update_link`) no merge can be a normal three-way one.

    `force` skips the fetch TTL. Every explicit ask passes it: with a release
    published five minutes after the last fetch, `u` answered "already on the
    latest version" off a stale ref and there was no way to make it look.
    """
    url = _upstream_url()
    code, _ = _git("remote", "get-url", UPSTREAM)
    if code != 0:
        add, out = _git("remote", "add", UPSTREAM, url)
        if add != 0:
            return {"available": 0, "url": url, "linked": False, "log": [],
                    "error": out[:200]}
    # 30 min and not the usual 60 s: an OS release is not something you race
    # to, and this runs on every home repaint.
    if fetch and (force or _stale_fetch_ref(f"refs/remotes/{UPSTREAM}", ttl=1800)):
        fcode, fout = _git("fetch", "--quiet", UPSTREAM)
        if fcode != 0:
            return {"available": 0, "url": url, "linked": False, "log": [],
                    "error": fout[:200] or "fetch failed"}
    branch = _upstream_branch()
    ref = f"{UPSTREAM}/{branch}"
    linked = _git("merge-base", "HEAD", ref)[0] == 0
    code, out = _git("log", "--oneline", "--no-decorate", "-20", f"HEAD..{ref}")
    log = [l for l in out.splitlines() if l.strip()] if code == 0 else []
    code, n = _git("rev-list", "--count", f"HEAD..{ref}")
    try:
        available = int(n.strip())
    except ValueError:
        available = len(log)
    return {"available": available, "url": url, "linked": linked, "log": log,
            "error": None}


def update_link() -> dict:
    """One-time graft for a repo that was copied instead of forked.

    Records upstream as an ancestor while keeping every local file as it is
    (`-X ours`), so from here on `update_apply` is an ordinary merge. Without
    it git refuses: the two histories have no commit in common.
    """
    st = update_status(force=True)
    if st["error"]:
        return {"error": st["error"]}
    if st["linked"]:
        return {"ok": True, "message": "already linked to upstream"}
    if sync_status(fetch=False)["dirty"]:
        return {"error": "working tree has uncommitted changes: commit or stash them first"}
    ref = f"{UPSTREAM}/{_upstream_branch()}"
    code, out = _git("merge", "--allow-unrelated-histories", "-X", "ours",
                     "--no-edit", "-m", f"chore: link this repo to {UPSTREAM}", ref)
    if code != 0:
        _git("merge", "--abort")
        return {"error": f"link failed, nothing changed: {out[:400]}"}
    return {"ok": True, "message": "linked to upstream; `sto update` works from now on"}


def update_apply(progress=None) -> dict:
    """Merge the published OS into this repo. Your knowledge is not in its way."""
    say = progress or (lambda _step: None)
    say("s_fetch")
    st = update_status(force=True)
    if st["error"]:
        return {"error": st["error"]}
    if not st["linked"]:
        return {"error": "this repo shares no history with upstream: run `sto update --link` once"}
    if st["available"] == 0:
        return {"ok": True, "message": "already on the latest version"}
    if sync_status(fetch=False)["dirty"]:
        return {"error": "working tree has uncommitted changes: commit or stash them first"}
    say("s_merge")
    ref = f"{UPSTREAM}/{_upstream_branch()}"
    code, out = _git("merge", "--no-edit", ref)
    if code != 0:
        _git("merge", "--abort")
        return {"error": _conflict_msg(out)}
    return {"ok": True, "message": f"updated · {st['available']} commit(s)",
            "available": st["available"]}


def sync_stage(progress=None) -> dict:
    """Export to the working tree and stage: {paths, sessions, config, memory}.

    The `export_*` calls are local, idempotent copies with no network: running
    them to preview is exactly what the push was going to do anyway. If nobody
    commits afterwards, the files stay staged and ready for the next push.

    `paths` is limited to `knowledge`/`vault` even when other work is staged in
    the index (say a `git add scripts/…` mid-task): the `diff --cached` that
    builds the list uses the same pathspec `sync_push` will commit, so preview
    and commit always describe the same set.
    """
    say = progress or (lambda _step: None)
    say("s_sessions")
    exported = export_sessions()
    say("s_config")
    cfg = export_config(get_sync_prefs())
    say("s_memory")
    mem = export_memory()
    say("s_add")
    _git("add", "-A", "--", "knowledge", "vault")
    _, staged = _git("diff", "--cached", "--name-only", "--", "knowledge", "vault")
    return {"paths": [p for p in staged.splitlines() if p.strip()],
            "sessions": exported, "config": cfg, "memory": mem,
            "activate": 0, "memories": 0}  # the export already ran: git sees it all


def sync_incoming() -> dict:
    """{paths, error} — which files a pull would bring. It fetches, applies nothing."""
    st = sync_status()
    if not st["remote"]:
        return {"paths": [], "error": "no git remote configured"}
    if st["fetchError"]:
        return {"paths": [], "error": f"fetch failed: {st['fetchError']}"}
    # three dots, not two: `HEAD..origin/x` diffs the two trees and also returns
    # the files you changed, so while ahead it showed your own work as "this is
    # coming down to you". `HEAD...origin/x` starts from the merge base and
    # returns only what the remote added.
    code, out = _git("diff", "--name-only", f"HEAD...origin/{st['branch']}")
    if code != 0:
        return {"paths": [], "error": out[:200]}
    return {"paths": [p for p in out.splitlines() if p.strip()], "error": None,
            "activate": apply_config(get_sync_prefs(), dry=True),
            "memories": import_memory(dry=True)}


def sync_push(progress=None) -> dict:
    """`progress("s_…")` is called at the start of each step: it is what the TUI
    paints live while the push runs on a thread."""
    say = progress or (lambda _step: None)
    st0 = sync_status()
    if not st0["remote"]:
        return {"error": "no git remote configured"}
    stage = sync_stage(progress)
    exported, exported_cfg, exported_mem = (stage["sessions"], stage["config"],
                                            stage["memory"])
    if stage["paths"]:
        say("s_commit")
        code, out = _git("commit", "-m", f"knowledge: sync from {LOCAL_MACHINE}",
                         "--", "knowledge", "vault")
        if code != 0:
            return {"error": f"commit failed: {out[:400]}"}
    st = sync_status(fetch=False)
    if st["behind"] > 0:
        return {"error": f"remote has {st['behind']} new commit(s): pull first",
                "needsPull": True, "status": st}
    if st["ahead"] == 0:
        return {"ok": True, "message": "nothing to push", "exported": exported, "status": st}
    say("s_push")
    code, out = _git("push", "origin", st["branch"])
    if code != 0:
        return {"error": f"push failed: {out[:400]}"}
    msg = f"pushed {st['ahead']} commit(s)"
    if exported_cfg:
        msg += f" · {exported_cfg} config file(s)"
    if exported_mem:
        msg += f" · {exported_mem} memoria(s)"
    return {"ok": True, "message": msg,
            "exported": exported, "status": sync_status(fetch=False)}


import re
import shutil
import subprocess
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

USAGE_TTL = 60      # seconds; the OAuth limits are one cheap https call
DETAIL_TTL = 900    # seconds; `npx -y ccusage` costs ~7s per call, twice
CACHE_DIR = REPO_ROOT / ".sto-cache"
USAGE_CACHE = CACHE_DIR / "usage.json"
_usage_cache: dict = {"ts": 0.0, "data": None}
_usage_lock = threading.Lock()


def _ccusage(args: list[str]):
    npx = shutil.which("npx")
    if not npx:
        return None
    try:
        r = subprocess.run([npx, "-y", "ccusage", *args, "--json"],
                           capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _oauth_usage():
    """Real plan-quota percentages + reset times from the same endpoint the
    Claude Code /usage panel uses, authenticated with the local OAuth token.
    Token never leaves this machine. Returns a list of limits or None."""
    import urllib.request
    try:
        cred = json.loads((CLAUDE_DIR / ".credentials.json").read_text(encoding="utf-8"))
        tok = cred["claudeAiOauth"]["accessToken"]
    except (OSError, ValueError, KeyError):
        return None
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={"Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
    except Exception:
        return None  # offline / token expired → frontend falls back to estimates
    out = []
    for lim in d.get("limits") or []:
        scope = lim.get("scope") or {}
        model = (scope.get("model") or {}).get("display_name")
        out.append({"kind": lim.get("kind"), "label": model,
                    "percent": lim.get("percent"), "resetsAt": lim.get("resets_at")})
    return out or None


def _read_usage_cache() -> dict:
    """The on-disk half of the cache. In-process caching alone was useless for
    the CLI: every `sto` is a fresh process, so every `sto status` paid the
    full ccusage bill again."""
    try:
        return json.loads(USAGE_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_usage_cache(d: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        USAGE_CACHE.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass  # ponytail: without the cache it still works, only slower


def usage_snapshot(detail: bool = True) -> dict:
    """Quota limits (OAuth, one https call) + spend detail (ccusage, ~14s).

    `detail=False` skips ccusage entirely and serves whatever detail the cache
    still holds. The TUI header and the home only paint `limits`, so they have
    no business spawning `npx` twice and freezing the loop for fifteen seconds.
    """
    now = time.time()
    with _usage_lock:
        cached = _usage_cache["data"] or _read_usage_cache().get("data")
        ts = _usage_cache["ts"] or (_read_usage_cache().get("ts") or 0.0)
        if cached is not None and now - ts < USAGE_TTL:
            if not detail or now - (cached.get("detailTs") or 0.0) < DETAIL_TTL:
                _usage_cache.update(ts=ts, data=cached)
                return cached
        data = dict(cached or {})
        data["limits"] = _oauth_usage() or (cached or {}).get("limits")
        if detail and now - (data.get("detailTs") or 0.0) >= DETAIL_TTL:
            since = (date.today() - timedelta(days=6)).strftime("%Y%m%d")
            blocks = _ccusage(["blocks", "--active"])
            daily = _ccusage(["daily", "--since", since])
            blk_list = (blocks or {}).get("blocks") or []
            data["block"] = blk_list[0] if blk_list else None
            data["daily"] = (daily or {}).get("daily", [])
            data["error"] = (None if (blocks is not None or daily is not None)
                             else "ccusage unavailable")
            data["detailTs"] = now
        data.setdefault("block", None)
        data.setdefault("daily", [])
        data.setdefault("error", None)
        _usage_cache.update(ts=now, data=data)
        _write_usage_cache({"ts": now, "data": data})
        return data


_DETAIL_RE = re.compile(r"^/api/sessions/([^/?]+)$")
_SKILL_RE = re.compile(r"^/api/skills/([^/?]+)$")
_SKILL_EXPORT_RE = re.compile(r"^/api/skills/([^/?]+)/export$")


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/api/sessions":
                return self._json(list_sessions())
            if self.path == "/api/skills":
                return self._json(list_skills())
            if self.path == "/api/machines":
                return self._json(list_machines())
            if self.path == "/api/usage":
                return self._json(usage_snapshot())
            if self.path == "/api/sync/status":
                return self._json(sync_status())
            if self.path == "/api/config/modules":
                return self._json({"modules": config_status()})
            if self.path == "/api/memory":
                return self._json(list_memory())
            if self.path.startswith("/api/sessions/search?"):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
                return self._json(search_sessions(q))
            if self.path == "/api/graph":
                try:
                    body = GRAPH_JSON.read_bytes()
                except OSError:
                    return self._json(
                        {"error": "graph.json not found — run: graphify update ."}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            m = _DETAIL_RE.match(self.path)
            if m:
                p = find_path_by_id(unquote(m.group(1)))
                if p is None:
                    return self._json({"error": "not found"}, 404)
                return self._json(session_timeline(p))
            m = _SKILL_EXPORT_RE.match(self.path)
            if m:
                sid = unquote(m.group(1))
                blob = export_skill_zip(sid)
                if blob is None:
                    return self._json({"error": "not found"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{sid.split(":", 1)[-1]}.zip"')
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                return self.wfile.write(blob)
            m = _SKILL_RE.match(self.path)
            if m:
                s = get_skill(unquote(m.group(1)))
                return self._json(s) if s else self._json({"error": "not found"}, 404)
            self._json({"error": "not found"}, 404)
        except ConnectionError:
            pass  # client went away mid-response; nothing to answer
        except Exception as e:  # never leak a stack trace to the client
            try:
                self._json({"error": str(e)}, 500)
            except ConnectionError:
                pass

    def do_POST(self):
        try:
            if self.path == "/api/exit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown).start()
                return
            if self.path == "/api/sync/pull":
                r = sync_pull()
            elif self.path == "/api/sync/push":
                r = sync_push()
            elif self.path == "/api/config/modules":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                mods = set_sync_prefs(list(body.get("modules", [])))
                r = {"ok": True, "enabled": mods, "modules": config_status()}
            elif self.path == "/api/skills/plugin":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                r = plugin_cmd(str(body.get("action", "")), str(body.get("plugin", "")))
            else:
                return self._json({"error": "not found"}, 404)
            self._json(r, 200 if "error" not in r else 409)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def do_DELETE(self):
        try:
            m = _SKILL_RE.match(self.path)
            if not m:
                return self._json({"error": "not found"}, 404)
            err = delete_skill(unquote(m.group(1)))
            self._json({"ok": True} if err is None else {"error": err},
                       200 if err is None else 409)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def log_message(self, *args):
        pass  # ponytail: quiet; add logging if debugging the server


def main():
    port = int(os.environ.get("STO_SESSIONS_PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"sessions_server on http://127.0.0.1:{port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    # ponytail: the subcommands live in `sto` (cli.py), which is what translates
    # and paints; only the server stayed here so there are not two CLIs.
    if len(sys.argv) > 1:
        sys.exit("commands live in `sto` (scripts/cli.py) — this only starts the server")
    main()
