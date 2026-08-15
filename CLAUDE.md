# STO agenticOS

An orchestration layer over Claude Code: engine first (sessions + sync + vault), UI after. Backend: `scripts/sessions_server.py` (pure stdlib). App: `app/` (React). Knowledge: `vault/` (read `vault/CLAUDE.md` for the conventions).

## Language

Code, comments, docstrings and docs are written in English. The TUI and the CLI print in the language configured in `sto ui` (English by default, Spanish available); every user-facing string lives in `scripts/i18n.py` — never hardcode one in `ui.py` or `cli.py`.

## Where code is written

Two clones, one rule: **code changes are made in the public clone** (`../sto-agentic-os-public`, remote `sto-agentic-os`) and reach the private one (`my-agentic-os`) through `sto update`. The private clone commits knowledge — `knowledge/`, `vault/` — and nothing under `scripts/` or `app/`.

It is not bureaucracy: editing the same file in both clones is what produces the merge conflicts `sto update` aborts on, and every fix taken this way is one more real test of the update path users depend on. `tools/build_public.py` stays for repairing drift, not for daily work.

## Knowledge rule

When a significant thread closes in this repo (a bug solved, a decision taken, research with a verdict), save the lesson as a note in `vault/wiki/` (one idea per file, linked) and update `vault/wiki/index.md`. Check the wiki before re-solving something: start from its `index.md`.

## Tests

```
cd scripts && python test_sessions_server.py && python test_dream_extract.py && python test_cli.py && python test_ui.py
```
