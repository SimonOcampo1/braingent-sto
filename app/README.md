# STO agenticOS (frontend)

Dashboard over local data. Views:

- **Dashboard** — single dynamic surface: 3D knowledge graph at the center (project filter sidebar), real plan quota (session/week/Fable % with reset times), consumption detail, and knowledge sync (Pull/Push + config modules).
- **Sessions** — grouped by project; full conversation view: user prompts + Claude prose (markdown + LaTeX), collapsible tool-call runs with params, image attachments, errors. Sessions with no prompt are hidden. Sessions synced from other machines show a hostname chip.
- **Skills** — personal + plugin skills, search, rendered SKILL.md, and token-free management: install/uninstall marketplace plugins (shells `claude plugin …`, package ops only), delete personal skills (confirm step), export any skill as .zip.

## Knowledge sync

One-button, token-free, git-based. **Push** exports local sessions (trimmed to
what the viewer renders, secrets redacted, ≤10MB sources only) into
`knowledge/sessions/<hostname>/`, commits `knowledge/` + `vault/`, and pushes.
**Pull** fetches and merges; push is blocked while behind (pull first), pull is
blocked on a dirty tree, and merge conflicts auto-abort with an error message.
Sessions pulled from other machines appear in the app automatically.

## Config sync (modular)

Pick which parts of `~/.claude` ride the same Push/Pull: `claude-md`,
`settings`, `keybindings`, `skills`, `agents`, `hooks` (checkboxes in the sync
panel; per-machine choice stored in `~/.claude/sto-sync.json`). Push exports
enabled modules into `knowledge/config/` with home paths tokenized as
`{{HOME}}`; Pull applies them for this machine, backing up overwritten files to
`~/.claude/.sto-backup/<timestamp>/`. `.credentials.json` and
`settings.local.json` never sync.

Runs as two processes in dev:

```bash
# 1. backend (serves /api on 127.0.0.1:8765, reads ~/.claude/projects)
cd ../scripts && python sessions_server.py

# 2. frontend (Vite dev server, proxies /api to the backend)
cd app && npm install && npm run dev
```

Open the URL Vite prints. `npm run build` produces a static bundle in `dist/`.

Stack: Vite + React + TypeScript + Tailwind v4. See `PRODUCT.md` for design intent.
