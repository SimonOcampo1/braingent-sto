import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import type { UsageSnapshot, UsageDay } from "./types";
import { fetchUsage } from "./api";
import { nodeProject, type GraphData } from "./Graph3D";

const Graph3D = lazy(() => import("./Graph3D"));

type ConfigModule = { id: string; localFiles: number; repoFiles: number; enabled: boolean };
type SyncStatus = {
  remote: string | null; branch: string | null; ahead: number; behind: number;
  dirty: boolean; machine: string; fetchError: string | null;
};

const fmtTokens = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M`
  : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);

const dayTokens = (d: UsageDay) =>
  d.inputTokens + d.outputTokens + d.cacheCreationTokens + d.cacheReadTokens;

const fmtClock = (ms: number) =>
  new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <section
      className={[
        "bg-surface-raised/90 border border-border rounded-xl px-5 py-4",
        className,
      ].join(" ")}
    >
      {children}
    </section>
  );
}

function Head({ label, action }: { label: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between mb-2.5">
      <h2 className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-fg-faint">
        {label}
      </h2>
      {action}
    </div>
  );
}

export default function DashboardPanel() {
  const [usage, setUsage] = useState<UsageSnapshot | null>(null);
  const [configMods, setConfigMods] = useState<ConfigModule[]>([]);
  const [configOpen, setConfigOpen] = useState(false);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [project, setProject] = useState<string | null>(null);
  const [busy, setBusy] = useState<"pull" | "push" | null>(null);
  const [syncMsg, setSyncMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let alive = true;
    const refresh = () => {
      fetchUsage().then((d) => alive && setUsage(d)).catch(() => {});
      fetch("/api/config/modules").then((r) => r.json()).then((d) => alive && setConfigMods(d.modules)).catch(() => {});
      fetch("/api/sync/status").then((r) => r.json()).then((d) => alive && setSync(d)).catch(() => {});
    };
    refresh();
    fetch("/api/graph").then((r) => (r.ok ? r.json() : null)).then((d) => alive && setGraph(d)).catch(() => {});
    const t = setInterval(refresh, 60_000); // matches server-side ccusage cache TTL
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => { alive = false; clearInterval(t); window.removeEventListener("focus", onFocus); };
  }, []);

  async function runSync(op: "pull" | "push") {
    setBusy(op);
    setSyncMsg(null);
    try {
      const r = await fetch(`/api/sync/${op}`, { method: "POST" });
      const d = await r.json();
      if (d.error) setSyncMsg({ ok: false, text: d.error });
      else setSyncMsg({ ok: true, text: d.message ?? "done" });
      if (d.status) setSync(d.status);
      else fetch("/api/sync/status").then((x) => x.json()).then(setSync).catch(() => {});
    } catch (e) {
      setSyncMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function toggleModule(id: string) {
    const next = configMods.map((m) => (m.id === id ? { ...m, enabled: !m.enabled } : m));
    setConfigMods(next); // optimistic
    try {
      const r = await fetch("/api/config/modules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modules: next.filter((m) => m.enabled).map((m) => m.id) }),
      });
      const d = await r.json();
      if (d.modules) setConfigMods(d.modules);
    } catch {
      setConfigMods(configMods); // revert
    }
  }

  const projects = useMemo(() => {
    if (!graph) return [];
    const counts = new Map<string, number>();
    for (const n of graph.nodes) {
      const p = nodeProject(n);
      counts.set(p, (counts.get(p) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [graph]);

  const filteredGraph = useMemo<GraphData | null>(() => {
    if (!graph) return null;
    if (!project) return graph;
    const keep = new Set(
      graph.nodes.filter((n) => nodeProject(n) === project).map((n) => n.id),
    );
    return {
      // clone nodes: the force engine mutates them, sharing breaks re-filtering
      nodes: graph.nodes.filter((n) => keep.has(n.id)).map((n) => ({ ...n })),
      links: graph.links
        .map((l) => ({
          ...l,
          source: typeof l.source === "object" ? (l.source as { id: string }).id : l.source,
          target: typeof l.target === "object" ? (l.target as { id: string }).id : l.target,
        }))
        .filter((l) => keep.has(l.source) && keep.has(l.target)),
    };
  }, [graph, project]);

  const b = usage?.block ?? null;
  const blockPct = b
    ? Math.min(100, Math.round(((Date.now() - Date.parse(b.startTime)) /
        (Date.parse(b.endTime) - Date.parse(b.startTime))) * 100))
    : null;
  const days = usage?.daily ?? [];
  const todayISO = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  })();
  const today = days.find((d) => d.period === todayISO); // never show yesterday as "today"
  const maxDay = Math.max(...days.map(dayTokens), 1);

  // Weekly window (Mon 00:00 local) + per-model aggregates across ALL models
  const weekStart = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime();
  }, []);
  const weekEnd = weekStart + 7 * 86_400_000;
  const weekPct = Math.min(100, Math.round(((Date.now() - weekStart) / (7 * 86_400_000)) * 100));
  // Real plan quota (same endpoint Claude Code's /usage uses); null → estimate
  const limits = usage?.limits ?? null;
  const sessionLim = limits?.find((l) => l.kind === "session") ?? null;
  const weekAllLim = limits?.find((l) => l.kind === "weekly_all") ?? null;
  const scopedLim = limits?.find((l) => l.kind === "weekly_scoped") ?? null;
  const isEstimate = limits === null;

  const fmtReset = (iso: string) => {
    const d = new Date(iso);
    const sameDay = d.toDateString() === new Date().toDateString();
    return sameDay
      ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" }) +
        " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  const barColor = (pct: number) => (pct >= 90 ? "bg-danger" : "bg-accent");

  const weekAgg = useMemo(() => {
    const perModel = new Map<string, { tokens: number; cost: number }>();
    let tokens = 0, cost = 0;
    for (const d of days) {
      if (new Date(`${d.period}T00:00`).getTime() < weekStart) continue;
      for (const mb of d.modelBreakdowns ?? []) {
        const t = mb.inputTokens + mb.outputTokens + mb.cacheCreationTokens + mb.cacheReadTokens;
        const cur = perModel.get(mb.modelName) ?? { tokens: 0, cost: 0 };
        cur.tokens += t;
        cur.cost += mb.cost;
        perModel.set(mb.modelName, cur);
        tokens += t;
        cost += mb.cost;
      }
    }
    const models = [...perModel.entries()].sort((a, b2) => b2[1].tokens - a[1].tokens);
    const fable = models.filter(([m]) => /fable|mythos/i.test(m))
      .reduce((a, [, v]) => ({ tokens: a.tokens + v.tokens, cost: a.cost + v.cost }),
              { tokens: 0, cost: 0 });
    return { tokens, cost, models, fable };
  }, [days, weekStart]);
  const fableShare = weekAgg.tokens ? weekAgg.fable.tokens / weekAgg.tokens : 0;

  return (
    <div className="relative h-full bg-surface overflow-hidden">
      {/* ── Graph, the centerpiece ── */}
      <div className="absolute inset-0">
        {filteredGraph ? (
          <Suspense fallback={null}>
            <Graph3D data={filteredGraph} showSearch searchPosition="center" />
          </Suspense>
        ) : (
          <div className="h-full flex items-center justify-center text-[12px] text-fg-faint">
            graph.json not generated: run `graphify update .`
          </div>
        )}
      </div>

      {/* ── Left: graph projects + knowledge sync ── */}
      <div className="absolute left-4 top-4 bottom-[76px] w-[240px] flex flex-col gap-3 pointer-events-none">
        <Panel className="pointer-events-auto flex-1 overflow-y-auto min-h-0">
          <Head label="Projects" />
          <ul className="space-y-0.5 select-none">
            <li>
              <button
                onClick={() => setProject(null)}
                aria-pressed={project === null}
                className={[
                  "w-full flex items-baseline justify-between rounded-md px-2 py-1.5 text-[12.5px] transition-colors duration-150",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
                  project === null
                    ? "bg-accent-surface text-accent font-medium"
                    : "text-fg-muted hover:bg-surface-overlay hover:text-fg",
                ].join(" ")}
              >
                All
                <span className="text-[11px] font-mono text-fg-faint tabular-nums">
                  {graph?.nodes.length ?? 0}
                </span>
              </button>
            </li>
            {projects.map(([p, count]) => {
              const active = project === p;
              return (
                <li key={p}>
                  <button
                    onClick={() => setProject(active ? null : p)}
                    aria-pressed={active}
                    className={[
                      "w-full flex items-baseline justify-between gap-2 rounded-md px-2 py-1.5 text-[12.5px] transition-colors duration-150",
                      "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
                      active
                        ? "bg-accent-surface text-accent font-medium"
                        : "text-fg-muted hover:bg-surface-overlay hover:text-fg",
                    ].join(" ")}
                  >
                    <span className="font-mono truncate">{p}</span>
                    <span className="text-[11px] font-mono text-fg-faint tabular-nums shrink-0">
                      {count}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {filteredGraph && (
            <p className="mt-3 pt-2 border-t border-border text-[10px] font-mono text-fg-faint tabular-nums">
              {filteredGraph.nodes.length} nodes · {filteredGraph.links.length} edges
            </p>
          )}
        </Panel>

        {/* Sync */}
        <Panel className="pointer-events-auto">
          <Head label="Knowledge sync" />
          {sync && (
            <p className="text-[11px] font-mono text-fg-muted tabular-nums mb-2.5">
              {sync.remote ? (
                <>
                  <span className={sync.behind > 0 ? "text-accent" : ""}>{sync.behind}↓</span>
                  {" · "}
                  <span className={sync.ahead > 0 ? "text-accent" : ""}>{sync.ahead}↑</span>
                  {sync.dirty && <span className="text-danger"> · dirty</span>}
                  <span className="text-fg-faint"> · {sync.machine}</span>
                </>
              ) : (
                "no remote configured"
              )}
            </p>
          )}
          <div className="flex gap-2">
            <button
              onClick={() => runSync("pull")}
              disabled={busy !== null || !sync?.remote}
              className={[
                "flex-1 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors duration-150",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
                "disabled:opacity-40 disabled:cursor-not-allowed",
                sync && sync.behind > 0
                  ? "bg-accent-surface text-accent"
                  : "bg-surface-overlay text-fg-muted hover:text-fg",
              ].join(" ")}
            >
              {busy === "pull" ? "Pulling…" : `Pull${sync && sync.behind > 0 ? ` (${sync.behind})` : ""}`}
            </button>
            <button
              onClick={() => runSync("push")}
              disabled={busy !== null || !sync?.remote || (sync?.behind ?? 0) > 0}
              title={sync && sync.behind > 0 ? "Pull first: remote has new commits" : undefined}
              className="flex-1 rounded-md px-3 py-1.5 text-[12px] font-medium bg-surface-overlay text-fg-muted hover:text-fg transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {busy === "push" ? "Pushing…" : "Push"}
            </button>
          </div>
          {syncMsg && (
            <p
              role="status"
              className={[
                "mt-2 text-[11px] font-mono leading-relaxed break-words",
                syncMsg.ok ? "text-tool" : "text-danger",
              ].join(" ")}
            >
              {syncMsg.text}
            </p>
          )}

          {/* Config modules: pick what ~/.claude config rides along */}
          <div className="mt-3 pt-2.5 border-t border-border">
            <button
              onClick={() => setConfigOpen(!configOpen)}
              aria-expanded={configOpen}
              className="group w-full flex items-center gap-2.5 rounded-md px-1.5 py-1.5 hover:bg-surface-overlay transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
              title="Enabled modules ride Push/Pull. Credentials and settings.local never sync; overwrites are backed up to ~/.claude/.sto-backup."
            >
              <span
                aria-hidden
                className={[
                  "text-accent text-[13px] leading-none transition-transform duration-150",
                  configOpen ? "rotate-90" : "",
                ].join(" ")}
              >
                ▸
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-muted group-hover:text-fg transition-colors duration-150">
                Config sync
              </span>
              <span className="ml-auto text-[10px] font-mono text-fg-faint tabular-nums">
                {configMods.filter((m) => m.enabled).length}/{configMods.length}
                {" · "}
                {configMods.filter((m) => m.enabled).reduce((a, m) => a + m.localFiles, 0)} files
              </span>
            </button>
            {configOpen && (
              <ul className="mt-1.5 space-y-0.5">
                {configMods.map((m) => (
                  <li key={m.id}>
                    <label className="flex items-center gap-2 text-[11.5px] font-mono cursor-pointer rounded px-1 py-0.5 hover:bg-surface-overlay transition-colors duration-150">
                      <input
                        type="checkbox"
                        checked={m.enabled}
                        onChange={() => toggleModule(m.id)}
                        className="accent-[var(--color-accent)]"
                      />
                      <span className={m.enabled ? "text-fg" : "text-fg-muted"}>{m.id}</span>
                      <span className="ml-auto text-[10px] text-fg-faint tabular-nums">
                        {m.localFiles} local · {m.repoFiles} repo
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Panel>
      </div>

      {/* ── Right: usage ── */}
      <div className="absolute right-4 top-4 bottom-[76px] w-[340px] flex flex-col gap-3 pointer-events-none">
        <Panel className="pointer-events-auto overflow-y-auto min-h-0">
          <Head
            label="Usage"
            action={
              isEstimate ? (
                <span className="text-[10px] font-mono text-fg-faint" title="Plan quota unavailable: showing time-elapsed estimates">
                  est.
                </span>
              ) : undefined
            }
          />
          <div className="grid grid-cols-2 gap-x-5">
            <div>
              <p className="text-[10.5px] uppercase tracking-[0.14em] text-fg-faint">session · 5h</p>
              <p className="text-[46px] leading-none font-semibold tracking-[-0.03em] text-fg tabular-nums mt-1">
                {sessionLim ? sessionLim.percent : (blockPct ?? "—")}
                <span className="text-[20px] text-fg-muted font-medium">%</span>
              </p>
              <div
                role="progressbar"
                aria-valuenow={sessionLim?.percent ?? blockPct ?? 0}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="5h session quota used"
                className="h-1.5 bg-surface-overlay rounded mt-2 overflow-hidden"
              >
                <div
                  className={`h-full rounded ${barColor(sessionLim?.percent ?? blockPct ?? 0)}`}
                  style={{ width: `${sessionLim?.percent ?? blockPct ?? 0}%` }}
                />
              </div>
              <p className="text-[11px] font-mono text-fg-faint tabular-nums mt-1.5">
                {sessionLim
                  ? <>resets {fmtReset(sessionLim.resetsAt)}{b && <> · ${b.costUSD.toFixed(2)}</>}</>
                  : b
                    ? <>${b.costUSD.toFixed(2)} · resets {fmtClock(Date.parse(b.endTime))}</>
                    : "no active block"}
              </p>
            </div>
            <div>
              <p className="text-[10.5px] uppercase tracking-[0.14em] text-fg-faint">week · all models</p>
              <p className="text-[46px] leading-none font-semibold tracking-[-0.03em] text-fg tabular-nums mt-1">
                {weekAllLim ? weekAllLim.percent : weekPct}
                <span className="text-[20px] text-fg-muted font-medium">%</span>
              </p>
              <div
                role="progressbar"
                aria-valuenow={weekAllLim?.percent ?? weekPct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Weekly quota used, all models"
                className="h-1.5 bg-surface-overlay rounded mt-2 overflow-hidden"
              >
                <div
                  className={`h-full rounded ${barColor(weekAllLim?.percent ?? weekPct)}`}
                  style={{ width: `${weekAllLim?.percent ?? weekPct}%` }}
                />
              </div>
              <p className="text-[11px] font-mono text-fg-faint tabular-nums mt-1.5">
                resets {weekAllLim
                  ? fmtReset(weekAllLim.resetsAt)
                  : new Date(weekEnd).toLocaleDateString(undefined, { weekday: "short", day: "numeric" }) + " 00:00"}
              </p>
            </div>
          </div>

          <p className="text-[11px] font-mono text-fg-faint tabular-nums mt-2">
            {fmtTokens(weekAgg.tokens)} · ${weekAgg.cost.toFixed(2)} all models this week
          </p>

          {/* Fable's own weekly quota (separate bucket on the plan) */}
          <div className="mt-3.5">
            <div className="flex items-baseline justify-between">
              <p className="text-[10.5px] uppercase tracking-[0.14em] text-fg-faint">
                {(scopedLim?.label ?? "fable").toLowerCase()} · week
              </p>
              <p className="text-[16px] font-semibold font-mono text-fg tabular-nums">
                {scopedLim ? scopedLim.percent : Math.round(fableShare * 100)}
                <span className="text-[11px] text-fg-muted font-medium">%</span>
              </p>
            </div>
            <div
              role="progressbar"
              aria-valuenow={scopedLim?.percent ?? Math.round(fableShare * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Fable weekly quota used"
              className="h-1.5 bg-surface-overlay rounded mt-1.5 overflow-hidden"
            >
              <div
                className={`h-full rounded ${scopedLim && scopedLim.percent >= 90 ? "bg-danger" : "bg-tool"}`}
                style={{ width: `${scopedLim?.percent ?? fableShare * 100}%` }}
              />
            </div>
            <p className="text-[11px] font-mono text-fg-faint tabular-nums mt-1">
              {fmtTokens(weekAgg.fable.tokens)} · ${weekAgg.fable.cost.toFixed(2)}
              {scopedLim && <> · resets {fmtReset(scopedLim.resetsAt)}</>}
            </p>
          </div>

          {weekAgg.models.length > 0 && (
            <ul className="mt-3 space-y-0.5">
              {weekAgg.models.slice(0, 4).map(([m, v]) => (
                <li key={m} className="flex items-baseline gap-2 text-[11px] font-mono tabular-nums">
                  <span className="text-fg-muted truncate">{m.replace(/^claude-/, "")}</span>
                  <span className="ml-auto text-fg-faint shrink-0">
                    {fmtTokens(v.tokens)} · ${v.cost.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="grid grid-cols-2 gap-x-6 mt-4">
            <div>
              <p className="text-[10.5px] uppercase tracking-[0.14em] text-fg-faint">today</p>
              <p className="text-[24px] leading-tight font-semibold tracking-[-0.02em] text-fg tabular-nums">
                {today ? fmtTokens(dayTokens(today)) : "—"}
              </p>
              <p className="text-[11px] font-mono text-fg-faint tabular-nums">
                {today ? `$${today.totalCost.toFixed(2)}` : ""}
              </p>
            </div>
            <div>
              <p className="text-[10.5px] uppercase tracking-[0.14em] text-fg-faint">7 days</p>
              <p className="text-[24px] leading-tight font-semibold tracking-[-0.02em] text-fg tabular-nums">
                {fmtTokens(days.reduce((a, d) => a + dayTokens(d), 0))}
              </p>
              <p className="text-[11px] font-mono text-fg-faint tabular-nums">
                ${days.reduce((a, d) => a + d.totalCost, 0).toFixed(2)}
              </p>
            </div>
          </div>
          {days.length > 1 && (
            <div className="flex items-end gap-1 h-7 mt-3" aria-hidden>
              {days.map((d) => (
                <div
                  key={d.period}
                  title={`${d.period}: ${fmtTokens(dayTokens(d))}`}
                  className="flex-1 bg-tool-surface rounded-sm"
                  style={{ height: `${Math.max(10, (dayTokens(d) / maxDay) * 100)}%` }}
                />
              ))}
            </div>
          )}
        </Panel>

      </div>
    </div>
  );
}
