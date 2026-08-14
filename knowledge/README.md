# knowledge/

What `sto push` writes and `sto pull` reads. Empty in a fresh clone; it fills
up the first time you push.

```
knowledge/
├── sessions/<machine>/      # Claude Code transcripts, trimmed and redacted
├── memory/<project>/<machine>/   # the memories, plain markdown with frontmatter
└── config/                  # the ~/.claude modules you chose to sync
    ├── claude-md/  settings/  keybindings/
    ├── skills/  agents/  hooks/
    └── plugins/             # marketplaces + installed plugins manifest
```

Everything here is plain text on purpose: you can read it, `grep` it, edit it
by hand and roll it back with `git revert`. Keep the repo **private** — these
are your transcripts.
