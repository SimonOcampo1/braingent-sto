# braingent-sto UI — design brief

Design intent for the braingent-sto shell (Overview, Sessions, Skills, Graph,
Routines, Usage). Reuse this visual language for the next slices (run-skill
buttons, terminal).

## Register

product

## Users

A solo developer who uses Claude Code daily. Reviews past AI sessions to understand what was accomplished, trace decisions, and audit tool use. Context: same workstation as their editor, likely evening or focused-work hours, dark screen environment. Primary tasks: glance at the Overview dashboard for current state (usage, routines, recent work), then drill into a session and read the full conversation.

## Product Purpose

braingent-sto — a read-only dashboard over data that already exists on disk: Claude Code session logs (`~/.claude/projects/**/*.jsonl`), installed skills (`~/.claude/skills` + plugins), the graphify knowledge graph, Hermes cron routines, and token usage (ccusage). Sessions render as a full back-and-forth conversation: user prompts right, Claude prose left (markdown + LaTeX), tool calls grouped into collapsible activity runs with their key parameter, image attachments inline, errors visible. The UI is intentionally thin; the motor (skills, Hermes, memoria) lives outside it.

## Brand Personality

Precise, minimal, focused. The tool should disappear into the data. No personality performance — it is an instrument, not a product. Warm graphite surfaces with a copper accent (a nod to Claude) instead of the reflexive dev-tool blue.

## Anti-references

- Generic SaaS dashboards (Mixpanel-style, big-number hero cards)
- Bubbly consumer apps (rounded everything, gradient text, confetti)
- Over-decorated admin panels (Ant Design defaults, Bootstrap admin themes)
- Consumer chat apps (avatar circles, read receipts, chrome competing with content) — the conversation view is asymmetric and role-tinted, but stays an instrument

## Design Principles

1. Data is the UI — the session content is the product; chrome serves it, never competes with it.
2. Density by default — a developer scanning 50+ sessions wants rows, not cards. Compact > spacious.
3. Instrument, not app — visual vocabulary borrowed from devtools (VS Code, GitHub), not consumer SaaS.
4. State clarity — every interactive element must have legible default/hover/selected/loading/error states.
5. Dark by default — same screen as their editor; the ambient context forces dark mode.
6. Overview first — the landing view integrates usage, sessions, routines, and graph into one glanceable surface; deep views stay single-purpose.

## Accessibility & Inclusion

WCAG AA minimum. Keyboard navigation for the session list (↑↓ moves selection; selected row scrolls into view). Sufficient contrast on dark bg (4.5:1+ for body text). No motion except short state transitions (150ms).
