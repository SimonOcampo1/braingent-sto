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
        "cmd_update": "trae las actualizaciones del OS (no toca tus memorias)",
        "cmd_badge": "la badge de STO en la status line de Claude Code",
        "cli_badge_hint": "`sto badge --install`, o el toggle en `sto ui` › Config",
        "cli_badge_active": "activa en la status line de Claude Code",
        "cli_badge_chained": "encadenada con: {cmd}",
        "cli_badge_installed": "badge instalada · reabrí Claude Code para verla",
        "cli_badge_removed": "badge sacada · volvió la status line anterior",
        "badge_row": "Badge en Claude Code", "badge_on": "activa",
        "badge_off": "apagada", "flash_badge": "badge: {state}",
        "cli_update_none": "el OS ya está en la última versión",
        "cli_update_available": "hay {n} actualización(es) del OS",
        "cli_update_hint": "`sto update --apply` para traerlas",
        "cli_update_unlinked": "este repo no comparte historia con upstream",
        "cli_update_link_hint": "`sto update --link` una sola vez y después `sto update` anda solo",
        "cli_update_failed": "no se pudo consultar upstream: {e}",
        "update_available": "actualización del OS",
        "update_apply_key": "[u] actualizar",
        "updating": "actualizando el OS…",
        "cmd_memory": "las memorias del repo",
        "cmd_forget": "saca algo del repo sin tocar esta máquina",
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
        "guide_open": "Guía de setup", "guide_close": "cerrar la guía",
        "guide_hint": "primera vez, máquina nueva y updates",
        "sec_prefs": "Preferencias",

        "no_usage": "sin datos de uso", "resets_at": "resetea {h}",
        "n_sessions": "sesiones", "n_projects": "proyectos",
        "n_memories": "memorias", "n_skills": "skills", "n_machines": "máquinas",
        "n_vault": "vault", "n_activate": "activar",
        "activate_hint": "config que todavía no está instalada acá",
        "one_session": "sesión", "one_memory": "memoria",
        "loading": "cargando…",
        "dirty": "sucio", "clean": "limpio", "never_synced": "sin sincronizar",
        "all_synced": "todo sincronizado",
        "ago_now": "recién", "ago_min": "hace {n} min",
        "ago_hour": "hace {n} h", "ago_day": "hace {n} d",
        "ago_never": "nunca",
        "checked": "comprobado {ago}", "last_sync": "Último sync",
        "inspect_hint": "↵ para ver el contenido de cada módulo",
        "to_push": "Para subir", "to_pull": "Para bajar",
        "nothing": "nada", "files": "archivos",
        "sec_contents": "{mod} · {n} · {agent}",
        "delete_title": "Borrar {what}", "delete_warning":
            "se elimina de esta máquina; vuelve con un pull si está en el repo",
        "not_deletable": "{id}: no se borra desde acá",
        "deleted": "borrado: {id}", "empty": "no hay nada acá",
        "st_both": "en ambos", "st_local": "solo acá", "st_repo": "solo en el repo",
        "st_gone": "borrada en el repo",
        "forget_title": "Sacar {what} del repo",
        "bring_title": "Traer {what} del repo a esta máquina",
        "bring_backup": "si ya existía algo, queda respaldado en ~/.claude/.sto-backup/",
        "brought": "traída: {id}",
        "forget_keeps_local": "tu copia en esta máquina no se toca",
        "forget_travels": "el borrado viaja en el próximo PUSH · la otra máquina decide",
        "forgotten": "fuera del repo: {id} · ahora PUSH",
        "module_off": "(no sincroniza)",
        "local_only": "solo acá, no viajó",
        "in_repo_not_installed": "en el repo, no instalada",
        "plugin_missing": "plugin que falta acá",
        "all_synced": "todo sincronizado",
        "local": "local", "in_repo": "en repo", "this_one": "esta",
        "last_activity": "última actividad · {d}",
        "row_prompt": "1 prompt", "row_prompts": "{n} prompts",
        "row_tool": "1 tool", "row_tools": "{n} tools",

        "accent_color": "Color de acento", "language": "Idioma",
        "syncing": "sincroniza", "not_syncing": "no sincroniza",
        "always_syncing": "siempre sincroniza",
        "n_in_repo": "{n} en repo", "no_remote": "todavía no configurado",
        "r_origin": "tuyo · memorias, sesiones y config",
        "r_upstream": "el motor · de acá vienen las updates",
        "sub_first_time": "Primera vez · hacer tuyo este clon",
        "where_steps": "Los 5 pasos se corren acá adentro, en la carpeta que"
                       " clonaste. El repo nuevo de GitHub NO se clona: solo"
                       " hace falta su URL.",
        "step1": "1. github.com/new → repo PRIVADO y vacío, sin README. Copiá su URL.",
        "step2": "2. git remote rename origin upstream      (el público pasa a ser upstream)",
        "step3": "3. git remote add origin <URL del paso 1>  (el tuyo pasa a ser origin)",
        "step3b": "4. git push -u origin main                 (sube el código a tu repo)",
        "step3c": "5. PUSH acá, o `sto push`                  (sube tus memorias y config)",
        "sub_each_machine": "En cada máquina más",
        "where_more": "Acá sí clonás: el que clonás es TU repo privado, no el público.",
        "step4": "1. git clone <URL de tu repo privado>   ·   cd al clon",
        "step5": "2. powershell -File scripts/install_sto_cli.ps1",
        "step6": "3. PULL · trae e instala lo de las otras máquinas",
        "step6b": "4. PUSH · sube las memorias que esta máquina ya tenía",
        "step6c": "tus memorias locales sin publicar nunca se pisan en un PULL",
        "sub_updates": "Actualizar el OS",
        "step7": "u acá, o `sto update --apply` · mergea upstream",
        "step8": "tus memorias no están en upstream, así que un merge no puede pisarlas",
        "step9": "si el repo se armó copiando archivos: `sto update --link`, una sola vez",
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

        "k_home": " ↑↓ mover  ↵ abrir  Tab sección  p push  l pull  f fetch  u update  q salir",
        "update_safe": "solo código: tus memorias no están en upstream",
        "update_restart": "actualizado · cerrá y reabrí sto ui para usar la versión nueva",
        "unlinked_short": "repo sin enlazar a upstream",
        "unlinked_key": "`sto update --link` (una vez)",
        "k_module": " ↑↓ mover  a traer  d borrar  R del repo  Tab sección  q salir",
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
        "cmd_update": "bring OS updates down (never touches your memories)",
        "cmd_badge": "the STO badge in Claude Code's status line",
        "cli_badge_hint": "`sto badge --install`, or the toggle in `sto ui` › Config",
        "cli_badge_active": "live in Claude Code's status line",
        "cli_badge_chained": "chained with: {cmd}",
        "cli_badge_installed": "badge installed · reopen Claude Code to see it",
        "cli_badge_removed": "badge removed · the previous status line is back",
        "badge_row": "Badge in Claude Code", "badge_on": "on",
        "badge_off": "off", "flash_badge": "badge: {state}",
        "cli_update_none": "the OS is already on the latest version",
        "cli_update_available": "{n} OS update(s) available",
        "cli_update_hint": "`sto update --apply` to bring them down",
        "cli_update_unlinked": "this repo shares no history with upstream",
        "cli_update_link_hint": "run `sto update --link` once and `sto update` works from then on",
        "cli_update_failed": "could not reach upstream: {e}",
        "update_available": "OS update",
        "update_apply_key": "[u] update",
        "updating": "updating the OS…",
        "cmd_memory": "the memories in the repo",
        "cmd_forget": "drop something from the repo without touching this machine",
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
        "guide_open": "Setup guide", "guide_close": "close the guide",
        "guide_hint": "first time, new machine and updates",
        "sec_prefs": "Preferences",

        "no_usage": "no usage data", "resets_at": "resets {h}",
        "n_sessions": "sessions", "n_projects": "projects",
        "n_memories": "memories", "n_skills": "skills", "n_machines": "machines",
        "n_vault": "vault", "n_activate": "to activate",
        "activate_hint": "config the repo carries and this machine has not installed",
        "one_session": "session", "one_memory": "memory",
        "loading": "loading…",
        "dirty": "dirty", "clean": "clean", "never_synced": "never synced",
        "all_synced": "everything in sync",
        "ago_now": "just now", "ago_min": "{n} min ago",
        "ago_hour": "{n} h ago", "ago_day": "{n} d ago",
        "ago_never": "never",
        "checked": "checked {ago}", "last_sync": "Last sync",
        "inspect_hint": "↵ to see what each module holds",
        "to_push": "To push", "to_pull": "To pull",
        "nothing": "nothing", "files": "files",
        "sec_contents": "{mod} · {n} · {agent}",
        "delete_title": "Delete {what}", "delete_warning":
            "removed from this machine; comes back on pull if it is in the repo",
        "not_deletable": "{id}: cannot be deleted from here",
        "deleted": "deleted: {id}", "empty": "nothing here",
        "st_both": "in both", "st_local": "only here", "st_repo": "only in the repo",
        "st_gone": "dropped in the repo",
        "forget_title": "Drop {what} from the repo",
        "bring_title": "Bring {what} from the repo to this machine",
        "bring_backup": "anything already there is backed up under ~/.claude/.sto-backup/",
        "brought": "brought: {id}",
        "forget_keeps_local": "your copy on this machine is untouched",
        "forget_travels": "the deletion travels on the next PUSH · the other machine decides",
        "forgotten": "out of the repo: {id} · PUSH now",
        "module_off": "(not syncing)",
        "local_only": "local only, never pushed",
        "in_repo_not_installed": "in repo, not installed",
        "plugin_missing": "plugin missing here",
        "all_synced": "all in sync",
        "local": "local", "in_repo": "in repo", "this_one": "this one",
        "last_activity": "last activity · {d}",
        "row_prompt": "1 prompt", "row_prompts": "{n} prompts",
        "row_tool": "1 tool", "row_tools": "{n} tools",

        "accent_color": "Accent color", "language": "Language",
        "syncing": "syncing", "not_syncing": "not syncing",
        "always_syncing": "always synced",
        "n_in_repo": "{n} in repo", "no_remote": "not set up yet",
        "r_origin": "yours · memories, sessions and config",
        "r_upstream": "the engine · where updates come from",
        "sub_first_time": "First time · make this clone yours",
        "where_steps": "All 5 steps run right here, in the folder you cloned."
                       " The new GitHub repo is never cloned: you only need"
                       " its URL.",
        "step1": "1. github.com/new → empty PRIVATE repo, no README. Copy its URL.",
        "step2": "2. git remote rename origin upstream      (the public one becomes upstream)",
        "step3": "3. git remote add origin <URL from step 1> (yours becomes origin)",
        "step3b": "4. git push -u origin main                 (pushes the code to your repo)",
        "step3c": "5. PUSH here, or `sto push`                (pushes your memories and config)",
        "sub_each_machine": "On every other machine",
        "where_more": "Here you do clone — and what you clone is YOUR private repo, not the public one.",
        "step4": "1. git clone <URL of your private repo>   ·   cd into it",
        "step5": "2. powershell -File scripts/install_sto_cli.ps1",
        "step6": "3. PULL · brings and installs what the other machines have",
        "step6b": "4. PUSH · uploads the memories this machine already had",
        "step6c": "a PULL never overwrites local memories you have not published yet",
        "sub_updates": "Updating the OS",
        "step7": "u here, or `sto update --apply` · merges upstream",
        "step8": "your memories are not in upstream, so a merge cannot overwrite them",
        "step9": "repo built by copying files instead of cloning: `sto update --link`, once",
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

        "k_home": " ↑↓ move  ↵ open  Tab section  p push  l pull  f fetch  u update  q quit",
        "update_safe": "code only: your memories are not in upstream",
        "update_restart": "updated · close and reopen sto ui to run the new version",
        "unlinked_short": "repo not linked to upstream",
        "unlinked_key": "`sto update --link` (once)",
        "k_module": " ↑↓ move  a bring  d delete  R from repo  Tab section  q quit",
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
        "cli_mem_repair_none": "no hay memorias mal archivadas en esta máquina",
        "cli_mem_repair_hint": "`sto memory repair --apply` para moverlas · después PUSH",
        "cli_mem_repaired": "{n} proyecto(s) re-archivado(s) · ahora PUSH",
        "cli_forget_usage": "sto forget <skill|config|plugin|memory>:<nombre> [--apply]",
        "cli_forget_hint": "no se borró nada · repetí con --apply · después PUSH",
        "cli_forget_done": "{n} archivo(s) fuera del repo · el borrado viaja en el próximo PUSH",
        "cli_forget_keeps_local": "tu copia local queda intacta",
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
        "cli_mem_repair_none": "no memories are misfiled on this machine",
        "cli_mem_repair_hint": "`sto memory repair --apply` to move them · then PUSH",
        "cli_mem_repaired": "{n} project(s) re-filed · PUSH now",
        "cli_forget_usage": "sto forget <skill|config|plugin|memory>:<name> [--apply]",
        "cli_forget_hint": "nothing removed · re-run with --apply · then PUSH",
        "cli_forget_done": "{n} file(s) out of the repo · the deletion travels on the next PUSH",
        "cli_forget_keeps_local": "your local copy is untouched",
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
