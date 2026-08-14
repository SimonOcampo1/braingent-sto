"""Every string on screen — TUI and CLI, in English and Spanish.

They live outside `ui.py` because `cli.py` needs them too and `ui` already
imports `cli`: the other way round would be a cycle. The language is picked in
the TUI's config and stored in `sto-ui.json`, per machine — the repo travels
between machines that may want different languages.

Commands (`sto push`, `sto sessions`) are never translated: what changes is
what they print.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # scripts/ is not a package

import sessions_server as srv  # noqa: E402

PREFS = srv.CLAUDE_DIR / "sto-ui.json"  # per machine: does not travel in the repo
LANGS = ["en", "es"]
LANG = "en"          # the default; `load()` overrides it with whatever is saved


STRINGS = {
    "es": {
        "tab_help": "Ayuda",
        "sec_commands": "Comandos de `sto`",
        "cmd_push": "exporta todo y lo sube al repo",
        "cmd_pull": "baja lo del repo y lo aplica en esta máquina",
        "cmd_status": "en qué anda el sync: ahead, behind, sucio",
        "cmd_config": "qué módulos de ~/.claude están sincronizando",
        "cmd_memory": "las memorias del repo",
        "cmd_sessions": "las sesiones, la más reciente primero",
        "cmd_show": "el transcript de una sesión, por el pager",
        "cmd_search": "busca texto en todas las sesiones",
        "cmd_skills": "las skills instaladas, o una entera",
        "cmd_usage": "límites del plan y consumo de los últimos días",
        "cmd_machines": "las máquinas que aportan al repo",
        "cmd_graph": "resumen, vecinos, o --open para la ventana",
        "cmd_ui": "abre esta pantalla",
        "k_help": " ↑↓ mover  Tab sección  q salir",
        "tab_home": "Home", "tab_sessions": "Sesiones",
        "tab_memory": "Memoria", "tab_config": "Config",

        "sec_usage": "Uso", "sec_sync": "Sync", "sec_machines": "Máquinas",
        "sec_parity": "Paridad de config", "sec_always": "Siempre sincronizan",
        "sec_modules": "Módulos de config",
        "sec_remote": "Sincronizar en la nube (GitHub)",
        "sec_prefs": "Preferencias",

        "no_usage": "sin datos de uso", "resets_at": "resetea {h}",
        "n_sessions": "sesiones", "n_projects": "proyectos",
        "n_memories": "memorias", "n_skills": "skills", "n_machines": "máquinas",
        "n_vault": "vault",
        "one_session": "sesión", "one_memory": "memoria",
        "dirty": "sucio", "clean": "limpio", "never_synced": "sin sincronizar",
        "inspect_hint": "↵ para ver el contenido de cada módulo",
        "to_push": "Para subir", "to_pull": "Para bajar",
        "nothing": "nada", "files": "archivos",
        "sec_contents": "{mod} · {n} en esta máquina",
        "delete_title": "Borrar {what}", "delete_warning":
            "se elimina de esta máquina; vuelve con un pull si está en el repo",
        "not_deletable": "{id}: no se borra desde acá",
        "deleted": "borrado: {id}", "empty": "no hay nada acá",
        "module_off": "(no sincroniza)",
        "local_only": "solo acá, no viajó",
        "in_repo_not_installed": "en el repo, no instalada",
        "plugin_missing": "plugin que falta acá",
        "all_synced": "todo sincronizado",
        "local": "local", "in_repo": "en repo", "this_one": "esta",
        "last_activity": "última actividad · {d}",

        "accent_color": "Color de acento", "language": "Idioma",
        "syncing": "sincroniza", "not_syncing": "no sincroniza",
        "always_syncing": "siempre sincroniza",
        "n_in_repo": "{n} en repo", "no_remote": "todavía no configurado",
        "sub_first_time": "Primera vez · subir este repo a tu cuenta",
        "step1": "1. creá un repo privado vacío en github.com/new (sin README)",
        "step2": "2. git remote add origin git@github.com:<vos>/<repo>.git",
        "step3": "3. git push -u origin main",
        "sub_each_machine": "En cada máquina que quieras sincronizar",
        "step4": "1. git clone git@github.com:<vos>/<repo>.git",
        "step5": "2. corré scripts/install_sto_cli.ps1 adentro del clon",
        "step6": "3. desde ahí, PUSH y PULL mantienen las dos máquinas iguales",
        "flash_accent": "acento: {v}", "flash_language": "idioma: {v}",
        "flash_module": "{id}: {state}",
        "flash_always_on": "{id} viaja siempre: no se puede apagar",

        "push_to": "push a origin", "pull_from": "pull de origin",
        "nothing_to_sync": "nada para sincronizar",
        "confirm": "↵ confirmar", "cancel": "Esc cancelar",
        "cancelled": "cancelado", "pushing": "pusheando…",
        "pulling": "puleando…", "done": "listo", "fetching": "fetcheando…",

        "s_sessions": "exportando sesiones", "s_config": "exportando config",
        "s_memory": "exportando memoria", "s_add": "stageando cambios",
        "s_commit": "commiteando", "s_push": "subiendo a origin",
        "s_fetch": "fetcheando origin", "s_merge": "mergeando",
        "s_apply": "aplicando config", "s_import": "importando memoria",

        "graph_button": "GRAFO", "graph_opening": "abriendo el grafo…",
        "no_data": "sin datos", "no_results": "sin resultados",
        "filter": "filtro: {q}", "search_hint": "↵ fijar   Esc limpiar",
        "usage_pct": "uso {p}%",

        "k_home": " ↑↓ mover  ↵ abrir  Tab sección  p push  l pull  q salir",
        "k_module": " ↑↓ mover  d borrar  Esc volver  Tab sección  q salir",
        "k_project": " ↑↓ ↵ entrar  a ver todas  / buscar  Tab sección  q salir",
        "k_list": " ↑↓ ↵ abrir  Esc volver  / buscar  g agentes  q salir",
        "k_memory": " ↑↓ ↵ abrir  Esc volver  / buscar  a todas  g grafo  q salir",
        "k_config": " ↑↓ mover  ↵ cambiar  Tab sección  q salir",
        "k_detail": " ↑↓ PgUp/PgDn scroll  Esc volver  q salir",

        "c_teal": "turquesa", "c_green": "verde", "c_violet": "violeta",
        "c_blue": "azul", "c_yellow": "amarillo", "c_red": "rojo",
    },
    "en": {
        "tab_help": "Help",
        "sec_commands": "`sto` commands",
        "cmd_push": "export everything and push it to the repo",
        "cmd_pull": "pull the repo and apply it on this machine",
        "cmd_status": "where sync stands: ahead, behind, dirty",
        "cmd_config": "which ~/.claude modules are syncing",
        "cmd_memory": "the memories in the repo",
        "cmd_sessions": "the sessions, most recent first",
        "cmd_show": "one session transcript, through the pager",
        "cmd_search": "search text across every session",
        "cmd_skills": "installed skills, or one in full",
        "cmd_usage": "plan limits and the last few days of spend",
        "cmd_machines": "the machines that feed the repo",
        "cmd_graph": "summary, neighbours, or --open for the window",
        "cmd_ui": "opens this screen",
        "k_help": " ↑↓ move  Tab section  q quit",
        "tab_home": "Home", "tab_sessions": "Sessions",
        "tab_memory": "Memory", "tab_config": "Config",

        "sec_usage": "Usage", "sec_sync": "Sync", "sec_machines": "Machines",
        "sec_parity": "Config parity", "sec_always": "Always synced",
        "sec_modules": "Config modules",
        "sec_remote": "Cloud sync (GitHub)",
        "sec_prefs": "Preferences",

        "no_usage": "no usage data", "resets_at": "resets {h}",
        "n_sessions": "sessions", "n_projects": "projects",
        "n_memories": "memories", "n_skills": "skills", "n_machines": "machines",
        "n_vault": "vault",
        "one_session": "session", "one_memory": "memory",
        "dirty": "dirty", "clean": "clean", "never_synced": "never synced",
        "inspect_hint": "↵ to see what each module holds",
        "to_push": "To push", "to_pull": "To pull",
        "nothing": "nothing", "files": "files",
        "sec_contents": "{mod} · {n} on this machine",
        "delete_title": "Delete {what}", "delete_warning":
            "removed from this machine; comes back on pull if it is in the repo",
        "not_deletable": "{id}: cannot be deleted from here",
        "deleted": "deleted: {id}", "empty": "nothing here",
        "module_off": "(not syncing)",
        "local_only": "local only, never pushed",
        "in_repo_not_installed": "in repo, not installed",
        "plugin_missing": "plugin missing here",
        "all_synced": "all in sync",
        "local": "local", "in_repo": "in repo", "this_one": "this one",
        "last_activity": "last activity · {d}",

        "accent_color": "Accent color", "language": "Language",
        "syncing": "syncing", "not_syncing": "not syncing",
        "always_syncing": "always synced",
        "n_in_repo": "{n} in repo", "no_remote": "not set up yet",
        "sub_first_time": "First time · push this repo to your account",
        "step1": "1. create an empty private repo at github.com/new (no README)",
        "step2": "2. git remote add origin git@github.com:<you>/<repo>.git",
        "step3": "3. git push -u origin main",
        "sub_each_machine": "On every machine you want in sync",
        "step4": "1. git clone git@github.com:<you>/<repo>.git",
        "step5": "2. run scripts/install_sto_cli.ps1 inside the clone",
        "step6": "3. from then on, PUSH and PULL keep both machines equal",
        "flash_accent": "accent: {v}", "flash_language": "language: {v}",
        "flash_module": "{id}: {state}",
        "flash_always_on": "{id} always travels: cannot be turned off",

        "push_to": "push to origin", "pull_from": "pull from origin",
        "nothing_to_sync": "nothing to sync",
        "confirm": "↵ confirm", "cancel": "Esc cancel",
        "cancelled": "cancelled", "pushing": "pushing…",
        "pulling": "pulling…", "done": "done", "fetching": "fetching…",

        "s_sessions": "exporting sessions", "s_config": "exporting config",
        "s_memory": "exporting memory", "s_add": "staging changes",
        "s_commit": "committing", "s_push": "pushing to origin",
        "s_fetch": "fetching origin", "s_merge": "merging",
        "s_apply": "applying config", "s_import": "importing memory",

        "graph_button": "GRAPH", "graph_opening": "opening the graph…",
        "no_data": "no data", "no_results": "no results",
        "filter": "filter: {q}", "search_hint": "↵ apply   Esc clear",
        "usage_pct": "usage {p}%",

        "k_home": " ↑↓ move  ↵ open  Tab section  p push  l pull  q quit",
        "k_module": " ↑↓ move  d delete  Esc back  Tab section  q quit",
        "k_project": " ↑↓ ↵ open  a show all  / search  Tab section  q quit",
        "k_list": " ↑↓ ↵ open  Esc back  / search  g agents  q quit",
        "k_memory": " ↑↓ ↵ open  Esc back  / search  a show all  g graph  q quit",
        "k_config": " ↑↓ move  ↵ change  Tab section  q quit",
        "k_detail": " ↑↓ PgUp/PgDn scroll  Esc back  q quit",

        "c_teal": "turquoise", "c_green": "green", "c_violet": "violet",
        "c_blue": "blue", "c_yellow": "yellow", "c_red": "red",
    },
}


# ── CLI strings ──
# Split from the block above only to keep them in sight: `t()` looks them up in
# the same dictionary.
CLI_STRINGS = {
    "es": {
        "cli_commands": "comandos: {names}",
        "cli_bad_args": "uso: sto {cmd} — argumentos inválidos",
        "cli_no_sessions": "sin sesiones — abrí Claude Code en algún proyecto",
        "cli_unknown_project": "proyecto desconocido: {proj} — probá: sto sessions",
        "cli_n_sessions": "{n} sesiones", "cli_1_session": "1 sesión",
        "cli_no_session": "no existe la sesión {id} — probá: sto sessions",
        "cli_ambiguous": "ambiguo: {q}",
        "cli_use_show": "uso: sto show <id> (probá: sto sessions)",
        "cli_blocks": "— {id} · {n} bloques",
        "cli_use_search": "uso: sto search <texto>",
        "cli_no_hits": "sin resultados para {q}",
        "cli_more_hits": "…y {n} más — afiná la búsqueda",
        "cli_no_skills": "sin skills instaladas",
        "cli_no_skill": "no existe la skill {id} — probá: sto skills",
        "cli_did_you_mean": "no existe la skill {id} — ¿quisiste decir?",
        "cli_reset": "resetea",
        "cli_no_usage": "sin datos de uso ({e})",
        "cli_usage_partial": "aviso: {e} — solo se muestran los límites del plan",
        "cli_you": "> vos", "cli_claude": "< claude", "cli_error": "! error",
        "cli_image": "[imagen]",
        "cli_graph_summary": "{n} nodos · {l} aristas · {o} huérfanos",
        "cli_graph_top": "más conectados",
        "cli_graph_none": "no hay nodo que empiece con {q} — probá: sto graph",
        "cli_graph_orphan": "(huérfano: sin aristas)",
        "cli_graph_missing": "falta graphify-out/graph.html — corré: graphify update .",
        "cli_graph_window": "grafo abierto en una ventana — {app}",
        "cli_graph_browser": "grafo abierto en el navegador"
                            " — no encontré Edge/Chrome/Brave para abrirlo sin barras",
        "cli_graph_failed": "no se pudo abrir la ventana: {e}",
        "cli_graph_build_failed": "no se pudo armar el grafo: {e}",
        "cli_mem_synced": "memoria sincronizada · {n} archivos",
        "cli_mem_missing": "no existe {target} — probá: sto memory",
        "cli_use_mem_search": "uso: sto memory search <texto>",
        "cli_n_memories": "{n} memorias", "cli_1_memory": "1 memoria",
        "cli_no_memories": "sin memorias sincronizadas — corré: sto memory sync",
        "cli_modules_on": "sincronizan",
        "cli_modules_off": "no sincronizan",
        "cli_status_remote": "sin remote configurado — mirá `sto ui`, tab Config",
        "cli_status_ahead": "para subir", "cli_status_behind": "para bajar",
        "cli_status_clean": "sin cambios sin commitear",
        "cli_status_dirty": "hay cambios sin commitear",
        "cli_fetch_failed": "no se pudo fetchear: {e}",
    },
    "en": {
        "cli_commands": "commands: {names}",
        "cli_bad_args": "usage: sto {cmd} — invalid arguments",
        "cli_no_sessions": "no sessions — open Claude Code in some project first",
        "cli_unknown_project": "unknown project: {proj} — try: sto sessions",
        "cli_n_sessions": "{n} sessions", "cli_1_session": "1 session",
        "cli_no_session": "no session {id} — try: sto sessions",
        "cli_ambiguous": "ambiguous: {q}",
        "cli_use_show": "usage: sto show <id> (try: sto sessions)",
        "cli_blocks": "— {id} · {n} blocks",
        "cli_use_search": "usage: sto search <text>",
        "cli_no_hits": "no results for {q}",
        "cli_more_hits": "…and {n} more — narrow the search",
        "cli_no_skills": "no skills installed",
        "cli_no_skill": "no skill {id} — try: sto skills",
        "cli_did_you_mean": "no skill {id} — did you mean?",
        "cli_reset": "resets",
        "cli_no_usage": "no usage data ({e})",
        "cli_usage_partial": "note: {e} — showing plan limits only",
        "cli_you": "> you", "cli_claude": "< claude", "cli_error": "! error",
        "cli_image": "[image]",
        "cli_graph_summary": "{n} nodes · {l} edges · {o} orphans",
        "cli_graph_top": "most connected",
        "cli_graph_none": "no node starts with {q} — try: sto graph",
        "cli_graph_orphan": "(orphan: no edges)",
        "cli_graph_missing": "graphify-out/graph.html is missing — run: graphify update .",
        "cli_graph_window": "graph opened in a window — {app}",
        "cli_graph_browser": "graph opened in the browser"
                            " — no Edge/Chrome/Brave found to open it chrome-less",
        "cli_graph_failed": "could not open the window: {e}",
        "cli_graph_build_failed": "could not build the graph: {e}",
        "cli_mem_synced": "memory synced · {n} files",
        "cli_mem_missing": "no such memory: {target} — try: sto memory",
        "cli_use_mem_search": "usage: sto memory search <text>",
        "cli_n_memories": "{n} memories", "cli_1_memory": "1 memory",
        "cli_no_memories": "no memories synced yet — run: sto memory sync",
        "cli_modules_on": "syncing",
        "cli_modules_off": "not syncing",
        "cli_status_remote": "no remote configured — see `sto ui`, Config tab",
        "cli_status_ahead": "to push", "cli_status_behind": "to pull",
        "cli_status_clean": "nothing uncommitted",
        "cli_status_dirty": "uncommitted changes",
        "cli_fetch_failed": "could not fetch: {e}",
    },
}
for _lang, _extra in CLI_STRINGS.items():
    STRINGS[_lang].update(_extra)


def t(key, **kw):
    """The string in the active language. Falls back to English and then to the
    key itself: a missing translation looks ugly, but it does not take the
    frame down."""
    s = STRINGS.get(LANG, {}).get(key) or STRINGS["en"].get(key, key)
    return s.format(**kw) if kw else s


def get_prefs():
    try:
        return json.loads(PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_pref(key, value):
    d = get_prefs()
    d[key] = value
    try:
        PREFS.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass  # ponytail: without persisting it still runs, back to the default on exit
    return value


def set_lang(code):
    global LANG
    LANG = code
    return set_pref("lang", code)


def load():
    """Re-read the language from disk. A value we do not know falls back to the
    default: anyone can edit the file by hand."""
    global LANG
    lang = get_prefs().get("lang")
    LANG = lang if lang in LANGS else LANGS[0]
    return LANG


load()
