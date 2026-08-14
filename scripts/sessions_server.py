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
    """(machine, path) for sessions synced from OTHER machines via the repo."""
    kd = knowledge_dir if knowledge_dir is not None else KNOWLEDGE_SESSIONS
    if not kd.is_dir():
        return []
    out = []
    for machine_dir in sorted(kd.iterdir()):
        if not machine_dir.is_dir() or machine_dir.name == LOCAL_MACHINE:
            continue  # own exports are already listed from ~/.claude/projects
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


CLAUDE_DIR = Path.home() / ".claude"
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
    skills_root = claude_dir / "skills"
    if skills_root.is_dir():
        for d in sorted(skills_root.iterdir()):
            if (d / "SKILL.md").is_file():
                yield "personal", d
    manifest = claude_dir / "plugins" / "installed_plugins.json"
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
    return text.replace("{{HOME}}", home)


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


def export_config(modules, claude_dir=None, repo_config=None, home=None) -> int:
    """Copy enabled config modules into knowledge/config/<module>/, home paths
    tokenized as {{HOME}}, secrets redacted. Returns files written."""
    cd = claude_dir or CLAUDE_DIR
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    home = home or str(Path.home())
    written = 0
    for m in modules:
        if m not in CONFIG_MODULES:
            continue
        if m == "plugins":
            written += export_plugins(claude_dir=cd, repo_config=cfg)
            continue
        dest_root = cfg / m
        for f, rel in _module_files(cd, m):
            out = dest_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if f.suffix.lower() in _TEXT_EXT:
                out.write_text(dx._redact(_tokenize(f.read_text(encoding="utf-8", errors="replace"), home)),
                               encoding="utf-8")
            else:
                out.write_bytes(f.read_bytes())
            written += 1
    return written


def apply_config(modules, claude_dir=None, repo_config=None, home=None) -> int:
    """Write repo config modules into ~/.claude, {{HOME}} resolved for THIS
    machine. Existing files are backed up under ~/.claude/.sto-backup/<ts>/."""
    import shutil as sh
    from datetime import datetime
    cd = claude_dir or CLAUDE_DIR
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    home = home or str(Path.home())
    backup = cd / ".sto-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
    applied = 0
    for m in modules:
        if m == "plugins":
            applied += apply_plugins(claude_dir=cd, repo_config=cfg)
            continue
        src_root = cfg / m
        if m not in CONFIG_MODULES or not src_root.is_dir():
            continue
        for f in sorted(src_root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src_root)
            target = cd / rel
            if target.exists():
                bpath = backup / rel
                bpath.parent.mkdir(parents=True, exist_ok=True)
                sh.copy2(target, bpath)
            target.parent.mkdir(parents=True, exist_ok=True)
            if f.suffix.lower() in _TEXT_EXT:
                target.write_text(_detokenize(f.read_text(encoding="utf-8", errors="replace"), home),
                                  encoding="utf-8")
            else:
                target.write_bytes(f.read_bytes())
            applied += 1
    return applied


def config_status(claude_dir=None, repo_config=None) -> list[dict]:
    cd = claude_dir or CLAUDE_DIR
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    enabled = set(get_sync_prefs())
    out = []
    for m in CONFIG_MODULES:
        if m == "plugins":
            local = len(_local_plugins(cd)[1])
            repo_n = len(_repo_plugins(cfg)[1])
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


def export_plugins(claude_dir=None, repo_config=None) -> int:
    """Write the local plugin manifest into knowledge/config/plugins/. 1 file."""
    cfg = repo_config if repo_config is not None else KNOWLEDGE_CONFIG
    marketplaces, plugins = _local_plugins(claude_dir)
    if not marketplaces and not plugins:
        return 0
    out = cfg / "plugins" / "plugins.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"marketplaces": marketplaces, "plugins": plugins},
                              indent=1), encoding="utf-8")
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


def apply_plugins(claude_dir=None, repo_config=None, runner=None) -> int:
    """Install repo-manifest plugins missing on this machine. Returns installs.
    Never uninstalls: extra local plugins are left alone."""
    run = runner or _claude_plugin
    missing_mk, missing_pl = plugins_to_apply(claude_dir, repo_config)
    for repo in missing_mk.values():
        run("marketplace", "add", repo)
    return sum(1 for p in missing_pl if run("install", p))


# ── Knowledge sync (git-based, zero tokens) ─────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
EXPORT_MAX_BYTES = 10 * 1024 * 1024


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
            name = project_name(jsonl, cwd)
            try:
                marker.write_text(name, encoding="utf-8")
            except OSError:
                pass
            return name
    return slug_dir.name


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


def export_memory(projects_dir=None, dest=None) -> int:
    """Mirror the local memory into knowledge/memory/<project>/<machine>/.

    A real mirror (it deletes what is no longer local) but scoped to this
    machine's folder, so it cannot destroy what another one learned."""
    root = dest if dest is not None else KNOWLEDGE_MEMORY
    written = 0
    for project, dirs in _memory_dirs(projects_dir).items():
        # ponytail: the union of every slug of the project. Deleting a memory
        # in one slug is not enough: the union revives it. Delete it in both.
        src = _newest(dirs)
        if not src:
            continue  # no real memories: do not create an empty folder
        out = root / project / LOCAL_MACHINE
        out.mkdir(parents=True, exist_ok=True)
        for f in out.glob("*.md"):
            if f.name not in src:
                f.unlink()
        for name, f in src.items():
            st = f.stat()
            tgt = out / name
            if tgt.exists() and tgt.stat().st_mtime >= st.st_mtime:
                continue
            tgt.write_text(dx._redact(f.read_text(encoding="utf-8", errors="replace")),
                           encoding="utf-8")
            os.utime(tgt, (st.st_atime, st.st_mtime))  # mtime = detector de cambio
            written += 1
    return written


def import_memory(projects_dir=None, src=None) -> int:
    """Merge knowledge/memory/<project>/*/ into the local memory. Returns writes.

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
                tgt.write_text(win_text, encoding="utf-8")
                os.utime(tgt, (st.st_atime, st.st_mtime))
                written += 1
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


def memory_graph(src=None) -> dict:
    """The repo's memories as a graph: {nodes, links}.

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
            nodes.append({"id": mid, "label": m["slug"], "kind": "memory",
                          "type": m["type"], "machine": m["machine"],
                          "project": proj["project"], "desc": m["description"],
                          "mtime": m["mtime"]})
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


def sync_status(fetch=True) -> dict:
    code, remote = _git("remote", "get-url", "origin")
    if code != 0:
        return {"remote": None, "branch": None, "ahead": 0, "behind": 0,
                "dirty": False, "machine": LOCAL_MACHINE, "fetchError": None}
    fetch_error = None
    if fetch:
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


def sync_pull(progress=None) -> dict:
    """Same `progress` contract as `sync_push`."""
    say = progress or (lambda _step: None)
    say("s_fetch")
    st = sync_status()
    if not st["remote"]:
        return {"error": "no git remote configured"}
    if st["fetchError"]:
        return {"error": f"fetch failed: {st['fetchError']}"}
    applied = 0
    if st["behind"] > 0:
        if st["dirty"]:
            return {"error": "working tree has uncommitted changes: commit or stash them first"}
        say("s_merge")
        code, out = _git("merge", "--no-edit", f"origin/{st['branch']}")
        if code != 0:
            _git("merge", "--abort")
            return {"error": f"merge conflict, aborted: {out[:400]}"}
        say("s_apply")
        applied = apply_config(get_sync_prefs())  # bring enabled ~/.claude modules up to date
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
        if imported:
            msg += f" · {imported} memoria(s)"
        return {"ok": True, "message": msg, "status": st}
    msg = f"pulled {st['behind']} commit(s)"
    if applied:
        msg += f" · applied {applied} config file(s)"
    if imported:
        msg += f" · {imported} memoria(s)"
    return {"ok": True, "message": msg, "status": sync_status(fetch=False)}


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
            "sessions": exported, "config": cfg, "memory": mem}


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
    return {"paths": [p for p in out.splitlines() if p.strip()], "error": None}


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

USAGE_TTL = 60  # seconds
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


def usage_snapshot() -> dict:
    """Real quota limits (OAuth) + consumption detail (ccusage). Cached 60s."""
    with _usage_lock:
        if _usage_cache["data"] is not None and time.time() - _usage_cache["ts"] < USAGE_TTL:
            return _usage_cache["data"]
        since = (date.today() - timedelta(days=6)).strftime("%Y%m%d")
        blocks = _ccusage(["blocks", "--active"])
        daily = _ccusage(["daily", "--since", since])
        blk_list = (blocks or {}).get("blocks") or []
        data = {
            "block": blk_list[0] if blk_list else None,
            "daily": (daily or {}).get("daily", []),
            "limits": _oauth_usage(),
            "error": None if (blocks is not None or daily is not None) else "ccusage unavailable",
        }
        _usage_cache.update(ts=time.time(), data=data)
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
