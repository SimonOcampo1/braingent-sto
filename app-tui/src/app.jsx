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
import { execFile } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Box, Text, render, useApp, useInput } from "ink";

import { ACCENTS, Key, Rule, Wordmark } from "./theme.jsx";
import Home from "./home.jsx";
import { Memories, Sessions } from "./lists.jsx";
import { Config, Help, configRows, isActionable } from "./panels.jsx";

const PORT = process.env.STO_SESSIONS_PORT || "8765";
const API = `http://127.0.0.1:${PORT}/api`;
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** How wide and how tall to draw. `process.stdout.columns` is undefined when
 *  the render is piped rather than shown — which is how a screenshot gets
 *  taken — so the environment gets a say before the fallback. */
const termWidth = () => process.stdout.columns || Number(process.env.COLUMNS) || 100;
const termRows = () => process.stdout.rows || Number(process.env.LINES) || 40;

const HOME = 0, SESSIONS = 1, MEMORY = 2, CONFIG = 3, HELP = 4;
const TABS = [
  { key: "1", id: "home", label: "tab_home" },
  { key: "2", id: "sessions", label: "tab_sessions", api: "/sessions" },
  { key: "3", id: "memory", label: "tab_memory", api: "/memory" },
  { key: "4", id: "config", label: "tab_config" },
  { key: "5", id: "help", label: "tab_help" },
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
          <Text inverse bold> {x.key} </Text>
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

function Actions({ d, t, accent, flash, tab }) {
  const s = d.sync;
  if (flash) return <Box paddingX={1}><Text color="yellow">{flash}</Text></Box>;
  return (
    <Box paddingX={1} flexWrap="wrap">
      <Key k="p" label={`PUSH ${s.toPush}`} on={s.toPush > 0 || s.ahead > 0} accent={accent} />
      <Key k="l" label={`PULL ${s.toPull}`} on={s.toPull > 0 || s.behind > 0} accent={accent} />
      <Key k="f" label="FETCH" accent={accent} />
      <Key k="g" label={t("graph_button")} accent={accent} />
      {/* the navigation keys only where there is something to navigate */}
      {(tab === SESSIONS || tab === MEMORY || tab === CONFIG) &&
        <Key k="↑↓" label={t("col_when")} accent={accent} />}
      {tab === MEMORY && <Key k="←→" label={t("col_project")} accent={accent} />}
      {tab === CONFIG && <Key k="↵" label={t("k_change")} accent={accent} />}
      <Key k="r" label={t("k_reload")} accent={accent} />
      <Key k="q" label={t("k_quit")} accent={accent} />
    </Box>
  );
}

/** Nothing runs until you answer. The counts are the ones already on the home;
 *  the per-file manifest lives in the stdlib TUI, and this shows exactly what
 *  it knows instead of implying it checked more. */
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

/** Run a `sto` subcommand and hand back whatever it printed.
 *
 * `sto graph --memory` already knows how to build the memory graph and find a
 * chrome-less browser for it, and its answer — including "graphify-out is
 * missing" — is the only thing the user needs to see. Firing it detached and
 * throwing the output away is why "the graph does not open" looked like
 * nothing happening at all.
 */
function sto(args) {
  return new Promise((resolve) => {
    execFile(process.platform === "win32" ? "python" : "python3",
             [path.join(REPO, "scripts", "cli.py"), ...args],
             { cwd: REPO, windowsHide: true },
             (err, out, errOut) =>
               resolve(String(out || errOut || (err && err.message) || "").trim()));
  });
}

function App() {
  const { exit } = useApp();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(true);
  // STO_TUI_TAB is how a screen other than the home gets captured: piped into
  // a file there is no keyboard to press `2` with. Same reason as COLUMNS.
  const [tab, setTab] = useState(Number(process.env.STO_TUI_TAB) || HOME);
  const [rows, setRows] = useState({});             // per-tab payloads, lazily
  const [sel, setSel] = useState([0, 0, 0, 1, 0]);  // one cursor per tab
  const [memSel, setMemSel] = useState(0);
  const [confirm, setConfirm] = useState(null);
  const [flash, setFlash] = useState("");
  const [size, setSize] = useState({ w: termWidth(), h: termRows() });
  const alive = useRef(true);

  const say = useCallback((msg) => {
    setFlash(msg);
    setTimeout(() => alive.current && setFlash(""), 4000);
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

  const cfgRows = d ? configRows(d) : [];
  const list = d ? (rows[TABS[tab].id] || []) : [];
  const groups = tab === MEMORY ? list : [];
  const mems = groups[sel[MEMORY]] ? groups[sel[MEMORY]].memories : [];

  const at = (i, delta, total) => setSel((s) => {
    const next = [...s];
    next[i] = Math.max(0, Math.min(total - 1, next[i] + delta));
    return next;
  });

  function move(delta) {
    if (tab === SESSIONS) return at(SESSIONS, delta, list.length);
    if (tab === MEMORY) {
      return setMemSel((m) => Math.max(0, Math.min(mems.length - 1, m + delta)));
    }
    if (tab !== CONFIG) return;
    // the headings and the always-synced rows are not stops: landing on one
    // leaves a cursor that `↵` does nothing with
    setSel((s) => {
      const next = [...s];
      let i = next[CONFIG];
      for (let step = 0; step < cfgRows.length; step++) {
        i += delta > 0 ? 1 : -1;
        if (i < 0 || i >= cfgRows.length) return s;
        if (isActionable(cfgRows[i])) { next[CONFIG] = i; return next; }
      }
      return s;
    });
  }

  async function post(url, body) {
    const r = await fetch(API + url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const out = await r.json().catch(() => ({}));
    if (out.error) say(out.error);
    load();
  }

  function change() {
    const row = cfgRows[sel[CONFIG]];
    if (!row) return;
    if (row.kind === "accent") {
      const codes = d.prefs.accents.map(([, c]) => c);
      return post("/prefs", { accent: codes[(codes.indexOf(d.prefs.accent) + 1) % codes.length] });
    }
    if (row.kind === "lang") {
      const ls = d.prefs.langs;
      return post("/prefs", { lang: ls[(ls.indexOf(d.prefs.lang) + 1) % ls.length] });
    }
    if (row.kind === "badge") return post("/prefs", { badge: !d.prefs.badge });
    if (row.kind === "module") {
      const on = new Set(d.modules.filter((m) => m.enabled).map((m) => m.id));
      on.has(row.id) ? on.delete(row.id) : on.add(row.id);
      return post("/config/modules", { modules: [...on] });
    }
  }

  async function run(what) {
    setConfirm(null);
    say("…");
    try {
      const r = await fetch(`${API}/sync/${what}`, { method: "POST" });
      const out = await r.json();
      say(out.error || out.message || "ok");
    } catch (e) {
      say(String(e.message));
    }
    load();
  }

  useInput(
    (input, key) => {
      if (confirm) {
        if (input === "y") run(confirm);
        else if (key.escape || input === "n") setConfirm(null);
        return;
      }
      const digit = TABS.findIndex((x) => x.key === input);
      if (digit >= 0) { setTab(digit); return; }
      // Tab always walks the tab bar. It used to change project inside the
      // memories screen, so the one key that is supposed to mean the same
      // thing everywhere stopped meaning it two screens in.
      if (key.tab) {
        setTab((x) => (x + (key.shift ? TABS.length - 1 : 1)) % TABS.length);
        return;
      }
      if (key.upArrow) return move(-1);
      if (key.downArrow) return move(1);
      if (key.pageUp) return move(-10);
      if (key.pageDown) return move(10);
      if (tab === MEMORY && (key.leftArrow || key.rightArrow)) {
        at(MEMORY, key.rightArrow ? 1 : -1, groups.length);
        setMemSel(0);
        return;
      }
      if (key.return && tab === CONFIG) return change();
      if (input === "q") exit();
      if (input === "r") { setRows({}); load(); }
      if (input === "f") load(true);
      if (input === "p" && d) setConfirm("push");
      if (input === "l" && d) setConfirm("pull");
      if (input === "g") {
        say(t("graph_opening"));
        sto(["graph", "--memory"]).then((out) => out && say(out));
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
  const viewport = Math.max(3, size.h - 14);

  return (
    <Box flexDirection="column" width={size.w}>
      <Header d={d} width={size.w} t={t} accent={accent} />
      {tab === HOME && size.h > 22 && (
        <Box paddingX={1} marginTop={1}><Wordmark width={size.w} accent={accent} /></Box>
      )}
      <Tabs tab={tab} t={t} accent={accent} busy={busy} />

      {tab === HOME && <Home d={d} t={t} accent={accent} width={size.w} />}
      {tab === SESSIONS && (
        <Sessions rows={list} sel={sel[SESSIONS]} size={viewport} t={t} accent={accent}
                  width={size.w} />
      )}
      {tab === MEMORY && (
        <Memories groups={groups} sel={sel[MEMORY]} memSel={memSel} size={viewport}
                  t={t} accent={accent} width={size.w} />
      )}
      {tab === CONFIG && (
        <Config d={d} t={t} accent={accent} width={size.w} sel={sel[CONFIG]} rows={cfgRows} />
      )}
      {tab === HELP && <Help d={d} t={t} accent={accent} width={size.w} />}

      <Box marginTop={1}><Rule n={size.w} /></Box>
      {confirm
        ? <Confirm what={confirm} d={d} t={t} accent={accent} />
        : <Actions d={d} t={t} accent={accent} flash={flash} tab={tab} />}
    </Box>
  );
}

render(<App />);
