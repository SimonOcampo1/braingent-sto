# STO agenticOS — design system

Tokens live in `src/index.css` under `@theme` (Tailwind v4). OKLCH everywhere;
neutrals tinted toward the accent hue (70–80).

## Color

| Token | Value | Use |
|---|---|---|
| `surface` | oklch(0.14 0.006 70) | app background |
| `surface-raised` | oklch(0.172 0.008 70) | nav rail, list panes |
| `surface-overlay` | oklch(0.225 0.010 70) | hover, inputs, code bg |
| `border` / `border-strong` | oklch(0.28 / 0.36 …) | hairlines / separators |
| `fg` / `fg-muted` / `fg-faint` | 0.93 / 0.67 / 0.47 | text hierarchy |
| `accent` | oklch(0.71 0.14 55) copper | selection, links, primary state only |
| `accent-surface` | oklch(0.215 0.040 55) | selected row bg |
| `user-surface` | oklch(0.195 0.028 55) | chat: user message bg |
| `tool` / `tool-surface` | jade 165 | tool chips, ok states |
| `danger` / `danger-surface` | red 25 | errors |

Strategy: Restrained. Accent ≤10% of any surface; decoration never.

## Typography

**Archivo Variable** for UI and display numbers (tight tracking at large
sizes); **JetBrains Mono Variable** for machine data (ids, params, counts,
labels). Scale ~1.15 for UI text; display numbers jump to 26/64px semibold
with -0.02/-0.03em tracking (5h block %, token totals). Markdown prose
(`.md` class): 13.5px / 1.7, KaTeX for math, code blocks on near-black inset.

## Layout

- 196px nav rail (raised surface) + full-height content view.
- Dashboard: 3D graph fills the surface; floating rounded-xl panels
  (raised/90) anchor left (sessions, sync) and right (usage, skills, routines).
- Sessions: 320px list grouped by project (sticky headers) + centered 820px
  conversation column.
- Graph: 220px project sidebar + canvas.
- Chat: user right (78% max, `user-surface`, rounded-lg with tight br corner),
  assistant left as open prose under a tiny `claude` label, consecutive tool
  calls collapsed into an expandable activity run.

## Motion

150ms color transitions; chevron rotate on expand. Nothing else.

## Theming

All tokens are CSS variables; `src/theme.ts` restyles `:root` at runtime and
persists to localStorage. Settings (⚙ in the dock): light/dark, three dark
intensities (graphite / deeper / OLED true black), six accent hues, three UI
fonts (Archivo / System / Mono). Graph canvas color rides `--graph-bg` (hex,
three.js can't parse oklch); views remount on theme change to repaint it.
