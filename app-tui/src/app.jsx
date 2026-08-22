/**
 * The Ink front-end of the STO TUI: the same facts `sto ui` paints, laid out
 * the way the prototype draws them.
 *
 * It owns no rules. Every number, every string and the accent colour come from
 * the API, which is the same Python the terminal TUI reads — so the two cannot
 * drift on what "to push" counts or which side of a parity a skill falls on.
 * This app decides how it looks and what a key does, and nothing else.
 *
 * It is optional. `sto ui` runs on Python stdlib whether or not Node exists on
 * the machine; this is the flavour you pick, not the one you need.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Box, Text, render, useApp, useInput } from "ink";

import { ACCENTS, Key, Rule, Wordmark } from "./theme.jsx";
import Home, { WIDE } from "./home.jsx";
import { Memories, Sessions } from "./lists.jsx";

const PORT = process.env.STO_SESSIONS_PORT || "8765";
const API = `http://127.0.0.1:${PORT}/api`;
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** How wide and how tall to draw. `process.stdout.columns` is undefined when
 *  the render is piped rather than shown — which is how a screenshot gets
 *  taken — so the environment gets a say before the fallback. */
const termWidth = () => process.stdout.columns || Number(process.env.COLUMNS) || 100;
const termRows = () => process.stdout.rows || Number(process.env.LINES) || 40;

const TABS = [
  { key: "1", id: "home", label: "tab_home" },
  { key: "2", id: "sessions", label: "tab_sessions", api: "/sessions" },
  { key: "3", id: "memory", label: "tab_memory", api: "/memory" },
];

// ── the chrome ──

function Header({ d, width, t, accent }) {
  const repo = (d.sync.remote || "").replace(/^https:\/\//, "").replace(/\.git$/, "");
  const bits = [
    [null, "braingent STO"],
    width >= 84 && ["repo", repo],
    ["agent", d.agent],
    [t("col_machine"), d.machine],
  ].filter(Boolean);
  return (
    <Box flexDirection="column">
      <Box paddingX={1}>
        {bits.map(([label, value], i) => (
          <Box key={i}>
            {/* a dim pipe between segments, not three spaces: at this density
                whitespace alone reads as one long sentence */}
            {i > 0 && <Text dimColor>{"  │  "}</Text>}
            {label && <Text dimColor>{label} </Text>}
            <Text bold={i === 0} color={i === 0 ? accent : undefined}>{value}</Text>
          </Box>
        ))}
      </Box>
      <Rule n={width} />
    </Box>
  );
}

function Tabs({ tab, t, accent, busy }) {
  return (
    <Box paddingX={1} marginY={1}>
      {TABS.map((x, i) => (
        <Box key={x.id} marginRight={3}>
          <Text inverse={i === tab} bold={i === tab} dimColor={i !== tab}> {x.key} </Text>
          <Text color={i === tab ? accent : undefined} bold={i === tab} dimColor={i !== tab}>
            {" " + t(x.label)}
          </Text>
        </Box>
      ))}
      <Box flexGrow={1} justifyContent="flex-end">
        <Text color="yellow">{busy ? "⟳" : " "}</Text>
      </Box>
    </Box>
  );
}

function Actions({ d, t, accent, flash }) {
  const s = d.sync;
  if (flash) return <Box paddingX={1}><Text color="yellow">{flash}</Text></Box>;
  return (
    <Box paddingX={1} flexWrap="wrap">
      <Key k="p" label={`PUSH ${s.toPush}`} on={s.toPush > 0 || s.ahead > 0} accent={accent} />
      <Key k="l" label={`PULL ${s.toPull}`} on={s.toPull > 0 || s.behind > 0} accent={accent} />
      <Key k="f" label="FETCH" accent={accent} />
      <Key k="g" label={t("graph_button")} accent={accent} />
      <Key k="r" label={t("k_reload")} accent={accent} />
      <Key k="q" label={t("k_quit")} accent={accent} />
    </Box>
  );
}

/** Nothing runs until you answer. The counts are the ones already on the home;
 *  the per-file manifest lives in the stdlib TUI, and this says so by showing
 *  exactly what it knows instead of implying it checked more. */
function Confirm({ what, d, t, accent }) {
  const s = d.sync;
  const [n, parts] = what === "push" ? [s.toPush, s.pushParts] : [s.toPull, s.pullParts];
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="yellow"
         paddingX={2} paddingY={1} marginX={1}>
      <Text bold color="yellow">{what === "push" ? "▲ PUSH" : "▼ PULL"} · {n}</Text>
      <Box marginTop={1} flexDirection="column">
        {(parts.length ? parts : [t("nothing")]).map((p) => (
          <Text key={p} dimColor>{p}</Text>
        ))}
      </Box>
      <Box marginTop={1}>
        <Key k="y" label={what.toUpperCase()} accent={accent} />
        <Key k="Esc" label={t("k_quit")} accent={accent} />
      </Box>
    </Box>
  );
}

// ── the app ──

function App() {
  const { exit } = useApp();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(true);
  const [tab, setTab] = useState(Number(process.env.STO_TUI_TAB) || 0);
  const [rows, setRows] = useState({});          // per-tab payloads, fetched lazily
  const [sel, setSel] = useState([0, 0, 0]);     // one cursor per tab
  const [memSel, setMemSel] = useState(0);
  const [confirm, setConfirm] = useState(null);
  const [flash, setFlash] = useState("");
  const [size, setSize] = useState({ w: termWidth(), h: termRows() });
  const alive = useRef(true);

  const say = useCallback((msg) => {
    setFlash(msg);
    setTimeout(() => alive.current && setFlash(""), 2500);
  }, []);

  const load = useCallback(async (fetchRemote = false) => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/home${fetchRemote ? "?fetch=1" : ""}`);
      if (!r.ok) throw new Error(String(r.status));
      setD(await r.json());
      setErr(null);
    } catch (e) {
      setErr(e.message);
    }
    setBusy(false);
  }, []);

  // a list tab pays for its data the first time it is opened, not on start-up:
  // /memory walks every memory in the repo and the home never needs it
  const loadTab = useCallback(async (i) => {
    const spec = TABS[i];
    if (!spec.api || rows[spec.id]) return;
    setBusy(true);
    try {
      const r = await fetch(API + spec.api);
      const data = await r.json();
      setRows((prev) => ({ ...prev, [spec.id]: data }));
    } catch { /* the screen shows empty; the home still works */ }
    setBusy(false);
  }, [rows]);

  useEffect(() => { load(); return () => { alive.current = false; }; }, [load]);
  useEffect(() => { loadTab(tab); }, [tab, loadTab]);
  useEffect(() => {
    const on = () => setSize({ w: termWidth(), h: termRows() });
    process.stdout.on("resize", on);
    return () => process.stdout.off("resize", on);
  }, []);

  const move = (delta, total) => {
    if (tab === 2 && size.w >= 90) {
      // on the memories screen the arrows walk the memories of the project and
      // Tab changes project: the right-hand list is the one you came to read
      setMemSel((m) => Math.max(0, Math.min(total - 1, m + delta)));
      return;
    }
    setSel((s) => {
      const next = [...s];
      next[tab] = Math.max(0, Math.min(total - 1, next[tab] + delta));
      return next;
    });
  };

  async function run(what) {
    setConfirm(null);
    say(t("s_" + (what === "push" ? "push" : "pull")) || "…");
    try {
      const r = await fetch(`${API}/sync/${what}`, { method: "POST" });
      const out = await r.json();
      say(out.error || out.message || "ok");
    } catch (e) {
      say(String(e.message));
    }
    load();
  }

  const list = d ? (rows[TABS[tab].id] || []) : [];
  const groups = tab === 2 ? list : [];
  const mems = groups[sel[2]] ? groups[sel[2]].memories : [];

  useInput(
    (input, key) => {
      if (confirm) {
        if (input === "y") run(confirm);
        else if (key.escape || input === "n") setConfirm(null);
        return;
      }
      const digit = TABS.findIndex((x) => x.key === input);
      if (digit >= 0) return setTab(digit);
      if (key.tab) {
        if (tab === 2) setSel((s) => {
          const next = [...s];
          next[2] = (next[2] + 1) % Math.max(1, groups.length);
          return next;
        });
        else setTab((x) => (x + 1) % TABS.length);
        setMemSel(0);
        return;
      }
      if (key.upArrow) return move(-1, tab === 2 ? mems.length : list.length);
      if (key.downArrow) return move(1, tab === 2 ? mems.length : list.length);
      if (key.pageUp) return move(-10, tab === 2 ? mems.length : list.length);
      if (key.pageDown) return move(10, tab === 2 ? mems.length : list.length);
      if (input === "q") exit();
      if (input === "r") { setRows({}); load(); }
      if (input === "f") load(true);
      if (input === "p" && d) setConfirm("push");
      if (input === "l" && d) setConfirm("pull");
      if (input === "g") {
        // the graph is a real window, and `sto graph --open` is what already
        // knows how to find a chrome-less browser and fall back to the default
        say(t("graph_opening"));
        spawn(process.platform === "win32" ? "python" : "python3",
              [path.join(REPO, "scripts", "cli.py"), "graph", "--open"],
              { detached: true, stdio: "ignore", cwd: REPO }).unref();
      }
    },
    // piped into a file there is no raw mode to put stdin into, and Ink throws
    // rather than degrade. Rendering one frame to a pipe is how the screen gets
    // captured, so it has to survive not having a keyboard.
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
  const accent = ACCENTS[d.accent] || "cyan";
  // the chrome costs a fixed number of rows; whatever is left is the list's
  const viewport = Math.max(3, size.h - (tab === 0 ? 0 : 14));

  return (
    <Box flexDirection="column" width={size.w}>
      <Header d={d} width={size.w} t={t} accent={accent} />
      {tab === 0 && size.h > 26 && (
        <Box paddingX={1} marginTop={1}><Wordmark width={size.w} accent={accent} /></Box>
      )}
      <Tabs tab={tab} t={t} accent={accent} busy={busy} />

      {tab === 0 && <Home d={d} t={t} accent={accent} width={size.w} />}
      {tab === 1 && (
        <Sessions rows={list} sel={sel[1]} size={viewport} t={t} accent={accent}
                  width={size.w} />
      )}
      {tab === 2 && (
        <Memories groups={groups} sel={sel[2]} memSel={memSel} size={viewport}
                  t={t} accent={accent} width={size.w} />
      )}

      <Box marginTop={1}><Rule n={size.w} /></Box>
      {confirm
        ? <Confirm what={confirm} d={d} t={t} accent={accent} />
        : <Actions d={d} t={t} accent={accent} flash={flash} />}
    </Box>
  );
}

render(<App />);
