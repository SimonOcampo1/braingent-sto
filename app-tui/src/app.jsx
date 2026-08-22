/**
 * The Ink front-end of the STO home: the same facts `sto ui` paints, laid out
 * as the prototype draws them.
 *
 * It owns no rules. Every number, every string and the accent colour come from
 * `GET /api/home`, which is the same Python `ui.home_lines()` reads — so the
 * two front-ends cannot drift on what "to push" counts or which side of a
 * parity a skill falls on. This file decides how it looks and nothing else.
 *
 * It is optional. `sto ui` runs on Python stdlib whether or not Node exists on
 * the machine; this is the flavour you pick, not the one you need.
 */
import React, { useEffect, useState } from "react";
import { Box, Text, render, useApp, useInput } from "ink";

const PORT = process.env.STO_SESSIONS_PORT || "8765";
const API = `http://127.0.0.1:${PORT}/api/home`;

// ── the wordmark ──
// Block Elements (U+2580–259F), the same glyphs `ui.py` draws by hand. They are
// fixed width in Unicode; an "ambiguous-width" character would throw the block
// off because the width maths counts code points, not columns.
const GLYPHS = {
  S: ["▄████▄", "██  ▀▀", "▀████▄", "▄▄  ██", "▀████▀"],
  T: ["██████", "  ██  ", "  ██  ", "  ██  ", "  ██  "],
  O: ["▄████▄", "██  ██", "██  ██", "██  ██", "▀████▀"],
  B: ["█████▄", "██  ██", "█████▄", "██  ██", "█████▀"],
  R: ["█████▄", "██  ██", "█████▀", "██ ▀█▄", "██  ██"],
  A: ["▄████▄", "██  ██", "██████", "██  ██", "██  ██"],
  I: ["██████", "  ██  ", "  ██  ", "  ██  ", "██████"],
  N: ["██▄ ██", "████ █", "██▀███", "██ ▀██", "██  ██"],
  G: ["▄████▄", "██  ▀▀", "██ ███", "██  ██", "▀████▀"],
  E: ["██████", "██    ", "█████ ", "██    ", "██████"],
  " ": ["  ", "  ", "  ", "  ", "  "],
};
const block = (word) =>
  [0, 1, 2, 3, 4].map((r) => [...word].map((ch) => GLYPHS[ch][r]).join(" "));
const FULL = block("BRAINGENT STO");
const SHORT = block("STO");

// `sto ui` stores the accent as a raw SGR code; Ink wants a name.
const ACCENTS = { 36: "cyan", 32: "green", 35: "magenta", 34: "blue", 33: "yellow", 31: "red" };

function Wordmark({ width, accent }) {
  // three tiers, like the terminal one: the whole name is ~90 columns and a
  // wordmark cut in half is worse than a smaller wordmark
  if (width >= FULL[0].length + 4)
    return (
      <Box flexDirection="column">
        {FULL.map((l, i) => (
          <Text key={i} color={accent}>{l}</Text>
        ))}
      </Box>
    );
  if (width >= SHORT[0].length + 4)
    return (
      <Box flexDirection="column">
        <Text bold>braingent</Text>
        {SHORT.map((l, i) => (
          <Text key={i} color={accent}>{l}</Text>
        ))}
      </Box>
    );
  return <Text color={accent} bold>braingent STO</Text>;
}

// ── pieces ──

function Panel({ title, accent, children, ...rest }) {
  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="gray"
      paddingX={1}
      {...rest}
    >
      <Text color={accent} bold>{title}</Text>
      <Box flexDirection="column" marginTop={1}>{children}</Box>
    </Box>
  );
}

/** `label:` in dim, the value hard against a fixed column so a stack aligns. */
function Field({ label, width = 14, children }) {
  return (
    <Box>
      <Box width={width}><Text dimColor>{label}</Text></Box>
      {children}
    </Box>
  );
}

function Bar({ pct, width = 14, accent }) {
  const n = Math.max(0, Math.min(width, Math.round(((pct || 0) * width) / 100)));
  return (
    <Text>
      <Text color={accent}>{"█".repeat(n)}</Text>
      <Text dimColor>{"░".repeat(width - n)}</Text>
    </Text>
  );
}

/** The four parity states of the prototype, as one dot. */
const DOT = { both: ["●", "green"], local: ["◐", "yellow"], repo: ["◑", "blue"], none: ["○", "gray"] };

function Dot({ local, repo }) {
  const key = local === repo ? (local === 0 ? "none" : "both") : local > repo ? "local" : "repo";
  const [glyph, colour] = DOT[key];
  return <Text color={colour}>{glyph}</Text>;
}

/** A key cap: reverse video, the way the prototype draws the footer. */
function Key({ k, label }) {
  return (
    <Box marginRight={2}>
      <Text inverse bold> {k} </Text>
      <Text dimColor> {label}</Text>
    </Box>
  );
}

function Cell({ w, children, align = "flex-start" }) {
  return <Box width={w} justifyContent={align}>{children}</Box>;
}

// ── the home ──

const SIDE = 34;   // the left column; below WIDE the two stack instead
const WIDE = 92;   // and the whole grid becomes one column

/** The Δ columns of the prototype: how many items only one side has.
 *
 * `skills` is the only module where the engine knows this by name, so it is
 * the only one that gets an exact answer; for the rest the difference between
 * the two file counts is the honest approximation, and it is what the terminal
 * TUI already shows as `148 local · 149 in repo`.
 */
function deltas(m, d) {
  if (m.id === "skills") return [d.localOnly.length, d.repoOnly.length];
  return [Math.max(0, m.localFiles - m.repoFiles), Math.max(0, m.repoFiles - m.localFiles)];
}

function Home({ d, t, accent, width, busy }) {
  const sync = d.sync;
  const wide = width >= WIDE;
  // one number for "how much of this machine is in the repo": the share of
  // items that both sides hold, over everything either side holds
  const totals = d.modules.reduce(
    (a, m) => {
      const [dl, dr] = deltas(m, d);
      return { same: a.same + Math.min(m.localFiles, m.repoFiles), drift: a.drift + dl + dr };
    },
    { same: 0, drift: 0 }
  );
  const parity = totals.same + totals.drift === 0
    ? 100
    : Math.round((100 * totals.same) / (totals.same + totals.drift));

  // `Δ L` / `Δ R` and not the words: the two labels wrap at this width, and
  // the product already spells these two sides `[L]` and `[R]` inside a module
  const cols = [
    [17, "flex-start", ""],
    [8, "flex-end", t("local")],
    [9, "flex-end", t("in_repo")],
    [6, "flex-end", "Δ L"],
    [6, "flex-end", "Δ R"],
    [4, "center", ""],
  ];

  return (
    <Box flexDirection="column" width={width}>
      {/* the three facts a header owes: which machine, where it syncs, which
          agent it reads. The name is the wordmark's job, not this line's. */}
      <Box justifyContent="space-between" paddingX={1}>
        <Text>
          <Text dimColor>machine </Text>
          <Text bold>{d.machine}</Text>
        </Text>
        {wide && (
          <Text dimColor>
            {(sync.remote || "").replace(/^https:\/\//, "").replace(/\.git$/, "")}
          </Text>
        )}
        <Text>
          <Text dimColor>agent </Text>
          <Text color={accent}>{d.agent}</Text>
          {busy ? <Text color="yellow"> ●</Text> : null}
        </Text>
      </Box>

      <Box paddingX={1} marginTop={1}>
        <Wordmark width={width} accent={accent} />
      </Box>

      {/* two rows of two, not two columns: stacked columns leave the panels of
          the shorter one floating against nothing, which is what the grid of
          the prototype does not do */}
      <Box
        marginTop={1}
        width="100%"
        flexDirection={wide ? "row" : "column"}
        gap={1}
        alignItems={wide ? "stretch" : undefined}
      >
        <Panel title={t("sec_sync")} accent={accent} width={wide ? SIDE : undefined} flexShrink={0}>
          {/* the count and what it is made of on adjacent lines: the number is
              the one the button carries, the words under it are why */}
          {[["to_push", sync.toPush, sync.pushParts],
            ["to_pull", sync.toPull, sync.pullParts]].map(([k, n, parts]) => (
            <Box key={k} flexDirection="column" marginBottom={1}>
              <Field label={t(k)}>
                <Text color={n ? accent : undefined} bold={!!n}>{n}</Text>
              </Field>
              {/* one per line and not joined: the rail is 34 columns and a
                  joined list wraps mid-item, with the tail unindented */}
              {(parts.length ? parts : [t("nothing")]).map((part) => (
                <Text key={part} dimColor>{"  " + part}</Text>
              ))}
            </Box>
          ))}
          <Field label={t("last_sync")}><Text>{sync.lastSync}</Text></Field>
          <Box>
            <Text color={accent}>↑{sync.ahead} ↓{sync.behind}</Text>
            <Text dimColor> · </Text>
            <Text color={sync.dirty ? "yellow" : "green"}>
              {sync.dirty ? t("dirty") : t("clean")}
            </Text>
          </Box>
          <Text dimColor>{t("checked", { ago: sync.checkedAgo })}</Text>
          {!!d.update.available && (
            <Text color="green">▲ {t("update_available")}: {d.update.available}</Text>
          )}
        </Panel>

        <Panel title={t("sec_parity")} accent={accent} flexGrow={1}>
          <Box>
            {cols.map(([w, align, label], i) => (
              <Cell key={i} w={w} align={align}><Text dimColor>{label}</Text></Cell>
            ))}
          </Box>
          {d.modules.map((m) => {
            const [dl, dr] = deltas(m, d);
            return (
              <Box key={m.id}>
                <Cell w={cols[0][0]}>
                  <Text dimColor={!m.enabled}>{m.id}</Text>
                </Cell>
                <Cell w={cols[1][0]} align="flex-end"><Text>{m.localFiles}</Text></Cell>
                <Cell w={cols[2][0]} align="flex-end"><Text>{m.repoFiles}</Text></Cell>
                <Cell w={cols[3][0]} align="flex-end">
                  <Text color={dl ? "yellow" : undefined} dimColor={!dl}>{dl || "·"}</Text>
                </Cell>
                <Cell w={cols[4][0]} align="flex-end">
                  <Text color={dr ? "green" : undefined} dimColor={!dr}>{dr || "·"}</Text>
                </Cell>
                <Cell w={cols[5][0]} align="center">
                  <Dot local={m.localFiles} repo={m.repoFiles} />
                </Cell>
              </Box>
            );
          })}
          {/* the legend only when something is out of parity: on a tidy repo it
              would be four states none of which are on screen */}
          {/* the legend only when a row on this table is out of parity. `gone`
              is deliberately not part of the test: it counts skills git saw
              deleted at some point, and none of them is a row here — it would
              light up four states on a screen showing none of them. */}
          {d.modules.some((m) => deltas(m, d).some(Boolean)) && (
            <Box marginTop={1}>
              {/* one Text and not a wrapping row of them: `gap` between flex
                  children of a bordered box costs a blank line per wrap */}
              <Text>
                {[["●", "green", "st_both"], ["◐", "yellow", "st_local"],
                  ["◑", "blue", "st_repo"], ["✕", "red", "st_gone"]].map(([g, c, k], i) => (
                  <Text key={k}>
                    {i ? "   " : ""}
                    <Text color={c}>{g}</Text>
                    <Text dimColor> {t(k)}</Text>
                  </Text>
                ))}
              </Text>
            </Box>
          )}
        </Panel>
      </Box>

      <Box
        marginTop={1}
        width="100%"
        flexDirection={wide ? "row" : "column"}
        gap={1}
        alignItems={wide ? "stretch" : undefined}
      >
        <Panel title={t("sec_usage")} accent={accent} width={wide ? SIDE : undefined} flexShrink={0}>
          {/* name and reset above, bar below: side by side the longest label
              pushes the bar past the panel and Ink shortens the bar to fit,
              so two limits end up drawn on two different scales */}
          {(d.usage.limits || []).map((l, i) => (
            <Box key={i} flexDirection="column" marginBottom={i ? 0 : 1}>
              <Box justifyContent="space-between">
                <Text dimColor>{(l.label || l.kind || "?").replace(/_/g, " ")}</Text>
                <Text dimColor>{l.resets}</Text>
              </Box>
              <Box>
                <Bar pct={l.percent} accent={accent} width={22} />
                <Text color="yellow">{String(l.percent ?? 0).padStart(4)}%</Text>
              </Box>
            </Box>
          ))}
          {(d.usage.limits || []).length === 0 && <Text dimColor>{t("no_usage")}</Text>}
        </Panel>

        <Panel title={t("sec_general")} accent={accent} flexGrow={1}>
          <Box>
            <Box width={17}><Text dimColor>{t("st_both")}</Text></Box>
            <Bar pct={parity} accent={accent} width={20} />
            <Text color="yellow">{String(parity).padStart(4)}%</Text>
          </Box>
          <Box marginTop={1} gap={2} flexWrap="wrap">
            {d.counters.map((c) => (
              <Text key={c.key}>
                <Text color={accent} bold>{c.n}</Text>
                <Text dimColor> {t(c.key)}</Text>
              </Text>
            ))}
          </Box>
          <Box marginTop={1}>
            <Box width={17}><Text dimColor>{t("sec_machines")}</Text></Box>
            <Text>
              {d.machines.map((m) => m.name + (m.local ? ` (${t("this_one")})` : "")).join(" · ")}
            </Text>
          </Box>
          <Box>
            <Box width={17}><Text dimColor>{t("sec_always")}</Text></Box>
            <Text>
              {Object.entries(d.knowledge)
                .map(([k, n]) => `${n} ${t("n_" + k, {}) || k}`)
                .join(" · ")}
            </Text>
          </Box>
        </Panel>
      </Box>

      <Box marginTop={1} paddingX={1} flexWrap="wrap">
        <Key k="p" label="PUSH" />
        <Key k="l" label="PULL" />
        <Key k="f" label="FETCH" />
        <Key k="r" label={t("k_reload")} />
        <Key k="q" label={t("k_quit")} />
      </Box>
    </Box>
  );
}

// ── shell ──

/** How wide to draw. `process.stdout.columns` is undefined when the render is
 *  piped rather than shown, which is exactly how a screenshot gets taken, so
 *  `COLUMNS` gets a say before the fallback. */
const termWidth = () =>
  process.stdout.columns || Number(process.env.COLUMNS) || 100;

function App() {
  const { exit } = useApp();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(true);
  const [width, setWidth] = useState(termWidth());

  async function load(fetchRemote = false) {
    setBusy(true);
    try {
      const r = await fetch(API + (fetchRemote ? "?fetch=1" : ""));
      if (!r.ok) throw new Error(`${r.status}`);
      setD(await r.json());
      setErr(null);
    } catch (e) {
      setErr(e.message);
    }
    setBusy(false);
  }

  useEffect(() => { load(); }, []);
  useEffect(() => {
    const on = () => setWidth(termWidth());
    process.stdout.on("resize", on);
    return () => process.stdout.off("resize", on);
  }, []);

  // isActive: piped into a file there is no raw mode to put stdin into, and
  // Ink throws rather than degrade. Rendering one frame to a pipe is how the
  // screen gets captured, so it has to survive not having a keyboard.
  useInput(
    (input) => {
      if (input === "q") exit();
      if (input === "r") load();
      if (input === "f") load(true);
    },
    { isActive: Boolean(process.stdin.isTTY) }
  );

  if (err)
    return (
      <Box flexDirection="column" padding={1}>
        <Text color="red">no server on {API} — {err}</Text>
        <Text dimColor>start it with: python scripts/sessions_server.py</Text>
      </Box>
    );
  if (!d) return <Text dimColor>loading…</Text>;

  const t = (key, vars) => {
    let s = d.strings[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
    return s;
  };
  return (
    <Home d={d} t={t} accent={ACCENTS[d.accent] || "cyan"} width={width} busy={busy} />
  );
}

render(<App />);
