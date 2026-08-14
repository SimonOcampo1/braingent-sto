import { useEffect, useMemo, useRef, useState } from "react";
import type { SessionMeta, SessionDetail, TimelineItem, Machines } from "./types";
import { fetchSessions, fetchSession, fetchMachines } from "./api";
import Markdown from "./Markdown";

/** Device silhouette for a machine: laptop has a hinge base, desktop a stand. */
function DeviceIcon({ type }: { type?: string }) {
  return (
    <svg viewBox="0 0 16 16" className="w-[11px] h-[11px] shrink-0" fill="none"
         stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" aria-hidden>
      {type === "laptop" ? (
        <>
          <rect x="3" y="3.5" width="10" height="7" rx="1" />
          <path d="M1.5 12.5h13" />
        </>
      ) : (
        <>
          <rect x="2.5" y="3" width="11" height="7.5" rx="1" />
          <path d="M6 13.5h4M8 10.5v3" />
        </>
      )}
    </svg>
  );
}

/** Machine identity chip: device icon + hostname. */
function MachineChip({ name, machines }: { name: string; machines: Machines }) {
  const info = machines[name];
  return (
    <span
      className="inline-flex items-center gap-1 bg-surface-overlay text-fg-faint rounded px-1.5 py-px text-[9.5px] font-mono leading-[1.4]"
      title={info?.local ? `${name} · this machine` : `synced from ${name}`}
    >
      <DeviceIcon type={info?.type} />
      {name}
    </span>
  );
}

/** Human name for a Claude Code project dir (path encoded with dashes). */
export function shortProject(p: string): string {
  const m = p.match(/Projects-(.+)$/);
  if (m) return m[1];
  const parts = p.split("-").filter(Boolean);
  return parts.slice(-3).join("-") || p;
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <p className="text-[34px] leading-none font-semibold tracking-[-0.02em] text-fg tabular-nums">
        {value}
      </p>
      <p className="mt-1.5 text-[10.5px] uppercase tracking-[0.14em] text-fg-faint">{label}</p>
    </div>
  );
}

/** 14-day activity rhythm for a set of sessions. */
function Spark({ list, tall = false }: { list: SessionMeta[]; tall?: boolean }) {
  const days = 14;
  const now = new Date();
  now.setHours(24, 0, 0, 0); // end of today
  const end = now.getTime() / 1000;
  const buckets = Array(days).fill(0);
  for (const s of list) {
    const i = days - 1 - Math.floor((end - s.mtime) / 86400);
    if (i >= 0 && i < days) buckets[i]++;
  }
  const max = Math.max(...buckets, 1);
  return (
    <div className={["flex items-end gap-[3px]", tall ? "h-12" : "h-8"].join(" ")} aria-hidden>
      {buckets.map((n, i) => (
        <div
          key={i}
          className={["flex-1 rounded-[2px]", n > 0 ? "bg-accent" : "bg-surface-overlay"].join(" ")}
          style={{ height: `${n > 0 ? Math.max(18, (n / max) * 100) : 10}%`, opacity: n > 0 ? 0.45 + 0.55 * (n / max) : 1 }}
        />
      ))}
    </div>
  );
}

function relTime(mtimeSec: number): string {
  const diff = Date.now() / 1000 - mtimeSec;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(mtimeSec * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Consecutive tool/error items collapse into one activity group. */
type ChatBlock =
  | { kind: "message"; item: Extract<TimelineItem, { role: "user" | "assistant" }> }
  | { kind: "image"; item: Extract<TimelineItem, { role: "image" }> }
  | { kind: "activity"; items: Extract<TimelineItem, { role: "tool" | "error" }>[] };

function toBlocks(timeline: TimelineItem[]): ChatBlock[] {
  const blocks: ChatBlock[] = [];
  for (const it of timeline) {
    if (it.role === "tool" || it.role === "error") {
      const last = blocks[blocks.length - 1];
      if (last?.kind === "activity") last.items.push(it);
      else blocks.push({ kind: "activity", items: [it] });
    } else if (it.role === "image") {
      blocks.push({ kind: "image", item: it });
    } else {
      blocks.push({ kind: "message", item: it });
    }
  }
  return blocks;
}

/** Param blocks tinted by meaning: removals red, additions jade, code neutral. */
const PARAM_TINT: Record<string, string> = {
  old_string: "border-danger-surface bg-danger-surface/40",
  new_string: "border-tool-surface bg-tool-surface/40",
  content: "border-tool-surface bg-tool-surface/40",
};
const INLINE_PARAMS = new Set(["file_path", "path", "pattern", "url", "glob", "type", "description", "skill", "query", "subject"]);
const PARAM_ORDER = ["file_path", "path", "command", "pattern", "url", "old_string", "new_string", "content"];

function ToolRow({ it }: { it: Extract<TimelineItem, { role: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const input = it.input ?? {};
  const keys = Object.keys(input).sort(
    (a, b2) =>
      (PARAM_ORDER.indexOf(a) + 1 || 99) - (PARAM_ORDER.indexOf(b2) + 1 || 99),
  );
  const expandable = keys.length > 0;

  return (
    <li className="text-[11.5px] font-mono leading-relaxed">
      <button
        onClick={() => expandable && setOpen(!open)}
        aria-expanded={expandable ? open : undefined}
        disabled={!expandable}
        className={[
          "flex items-baseline gap-2 w-full text-left rounded px-1 py-0.5",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
          expandable ? "hover:bg-surface-overlay transition-colors duration-150 cursor-pointer" : "cursor-default",
        ].join(" ")}
      >
        {expandable && (
          <span
            aria-hidden
            className={["shrink-0 text-fg-faint text-[10px] transition-transform duration-150", open ? "rotate-90" : ""].join(" ")}
          >
            ▸
          </span>
        )}
        <span className="shrink-0 text-tool">{it.tool}</span>
        {it.detail && (
          <span className="text-fg-faint truncate" title={it.detail}>
            {it.detail}
          </span>
        )}
      </button>
      {open && (
        <div className="ml-5 mt-1 mb-2 space-y-1.5 select-text">
          {keys.map((k) => {
            const v = input[k];
            if (INLINE_PARAMS.has(k) && v.length <= 120)
              return (
                <p key={k} className="text-[11px] leading-relaxed">
                  <span className="text-fg-faint">{k}</span>{" "}
                  <span className="text-fg-muted break-all">{v}</span>
                </p>
              );
            return (
              <div key={k}>
                <p className="text-[10px] uppercase tracking-[0.1em] text-fg-faint mb-0.5">{k}</p>
                <pre
                  className={[
                    "text-[11px] leading-[1.6] text-fg-muted rounded-md border px-3 py-2 overflow-x-auto whitespace-pre-wrap break-words max-h-72 overflow-y-auto",
                    PARAM_TINT[k] ?? "border-border bg-surface-raised",
                  ].join(" ")}
                >
                  {v}
                </pre>
              </div>
            );
          })}
        </div>
      )}
    </li>
  );
}

function ActivityGroup({ items }: { items: Extract<TimelineItem, { role: "tool" | "error" }>[] }) {
  const tools = items.filter((i) => i.role === "tool").length;
  const errors = items.length - tools;
  const [open, setOpen] = useState(items.length <= 3);

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="inline-flex items-center gap-2 text-[11px] font-mono text-fg-faint hover:text-fg-muted transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent rounded px-1 py-0.5"
      >
        <span className={["transition-transform duration-150", open ? "rotate-90" : ""].join(" ")}>
          ▸
        </span>
        {tools > 0 && <span className="text-tool">{tools} tool call{tools !== 1 ? "s" : ""}</span>}
        {errors > 0 && <span className="text-danger">{errors} error{errors !== 1 ? "s" : ""}</span>}
      </button>
      {open && (
        <ul className="mt-1 ml-4 space-y-0.5">
          {items.map((it, i) =>
            it.role === "tool" ? (
              <ToolRow key={i} it={it} />
            ) : (
              <li key={i} className="text-[11.5px] font-mono leading-relaxed">
                <span className="text-danger">✕ {it.text || "tool error"}</span>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}

function SessionCard({ s, onOpen, machines, localName }: {
  s: SessionMeta; onOpen: (s: SessionMeta) => void; machines: Machines; localName: string;
}) {
  return (
    <button
      onClick={() => onOpen(s)}
      className="text-left bg-surface-raised border border-border rounded-xl px-4 py-3.5 hover:border-border-strong hover:bg-surface-overlay transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
    >
      <p className="text-[13px] font-medium text-fg leading-snug line-clamp-2">{s.title}</p>
      <div className="mt-2.5 flex items-center gap-1.5 text-[11px] font-mono text-fg-faint tabular-nums">
        <span className="truncate">{shortProject(s.project)}</span>
        {(s.machine ?? localName) && (
          <MachineChip name={s.machine ?? localName} machines={machines} />
        )}
        <span className="ml-auto shrink-0">{relTime(s.mtime)}</span>
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-[11px] font-mono text-fg-faint tabular-nums">
        <span>{s.n_prompts}p</span>
        <span>{s.n_tools}t</span>
        {s.errors > 0 && <span className="text-danger">{s.errors} err</span>}
      </div>
    </button>
  );
}

export default function SessionsPanel({ focusId }: { focusId?: string | null }) {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SessionMeta[] | null>(null);
  const [searching, setSearching] = useState(false);

  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [machines, setMachines] = useState<Machines>({});
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    fetchSessions()
      .then((s) => { setSessions(s); setReady(true); })
      .catch((e) => setLoadError(String(e)));
    fetchMachines().then(setMachines).catch(() => {});
  }, []);

  const localName = useMemo(
    () => Object.keys(machines).find((m) => machines[m].local) ?? "",
    [machines],
  );

  // deep link from elsewhere
  useEffect(() => {
    if (!focusId || !sessions.length) return;
    const s = sessions.find((x) => x.id === focusId);
    if (s) {
      setActiveProject(s.project);
      setSelected(s.id);
    }
  }, [focusId, sessions]);

  // debounced content search
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(() => {
      fetch(`/api/sessions/search?q=${encodeURIComponent(q)}`)
        .then((r) => r.json())
        .then((d) => { setResults(d); setSearching(false); })
        .catch(() => setSearching(false));
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    setDetailError(null);
    const controller = new AbortController();
    fetchSession(selected, controller.signal)
      .then(setDetail)
      .catch((e: unknown) => {
        if (e instanceof Error && e.name === "AbortError") return;
        setDetailError(String(e));
      });
    return () => controller.abort();
  }, [selected]);

  const projects = useMemo(() => {
    const by = new Map<string, SessionMeta[]>();
    for (const s of sessions) {
      if (!by.has(s.project)) by.set(s.project, []);
      by.get(s.project)!.push(s);
    }
    return [...by.entries()]; // most-recent-first by insertion
  }, [sessions]);

  const projectSessions = useMemo(
    () => (activeProject ? sessions.filter((s) => s.project === activeProject) : []),
    [sessions, activeProject],
  );

  // machines this project's repo has been worked on from (local + synced)
  const projectMachines = useMemo(
    () => [...new Set(projectSessions.map((s) => s.machine ?? localName).filter(Boolean))],
    [projectSessions, localName],
  );

  // ↑↓ inside a project
  useEffect(() => {
    if (!activeProject) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (!projectSessions.length) return;
      const idx = selected ? projectSessions.findIndex((s) => s.id === selected) : -1;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelected(projectSessions[Math.min(idx + 1, projectSessions.length - 1)].id);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelected(projectSessions[Math.max(idx - 1, 0)].id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeProject, projectSessions, selected]);

  useEffect(() => {
    if (!selected || !listRef.current) return;
    listRef.current.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  function openFromCard(s: SessionMeta) {
    setQuery("");
    setResults(null);
    setActiveProject(s.project);
    setSelected(s.id);
  }

  if (loadError)
    return (
      <div className="h-full bg-surface flex items-center justify-center">
        <p className="bg-danger-surface text-danger text-[12px] font-mono rounded px-4 py-2.5">
          Error: {loadError}
        </p>
      </div>
    );

  /* ── Project drill-in: list + conversation ── */
  if (activeProject) {
    return (
      <div className="grid grid-cols-[320px_1fr] h-full bg-surface text-fg font-sans select-none">
        <aside className="flex flex-col bg-surface-raised border-r border-border overflow-hidden">
          <div className="shrink-0 flex items-center gap-2 px-3 py-2.5 border-b border-border">
            <button
              onClick={() => { setActiveProject(null); setSelected(null); setDetail(null); }}
              aria-label="Back to projects"
              className="shrink-0 rounded-md px-1.5 py-0.5 text-[13px] text-fg-muted hover:bg-surface-overlay hover:text-fg transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
            >
              ←
            </button>
            <span className="text-[12px] font-mono font-medium text-fg truncate">
              {shortProject(activeProject)}
            </span>
            <span className="ml-auto text-[11px] font-mono text-fg-faint tabular-nums">
              {projectSessions.length}
            </span>
          </div>
          <ul ref={listRef} role="listbox" aria-label="Session list" className="flex-1 overflow-y-auto pb-20">
            {projectSessions.map((s) => {
              const isSelected = selected === s.id;
              return (
                <li key={s.id} role="option" aria-selected={isSelected}>
                  <button
                    onClick={() => setSelected(s.id)}
                    className={[
                      "w-full text-left px-3 py-2.5 border-b border-border",
                      "transition-colors duration-150",
                      "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-accent",
                      isSelected ? "bg-accent-surface" : "hover:bg-surface-overlay",
                    ].join(" ")}
                  >
                    <p
                      className={[
                        "text-[13px] font-medium leading-snug truncate",
                        isSelected ? "text-accent" : "text-fg",
                      ].join(" ")}
                    >
                      {s.title}
                    </p>
                    <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-fg-faint leading-none tabular-nums">
                      <span>{relTime(s.mtime)}</span>
                      <span className="text-border-strong">·</span>
                      <span>{s.n_prompts}p</span>
                      <span className="text-border-strong">·</span>
                      <span>{s.n_tools}t</span>
                      {s.errors > 0 && (
                        <>
                          <span className="text-border-strong">·</span>
                          <span className="text-danger font-medium">{s.errors} err</span>
                        </>
                      )}
                      {(s.machine ?? localName) && (
                        <span className="ml-auto">
                          <MachineChip name={s.machine ?? localName} machines={machines} />
                        </span>
                      )}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        <main className="overflow-y-auto bg-surface select-text">
          {!selected && (
            <div className="h-full flex flex-col items-center justify-center gap-2 px-8 text-center">
              <p className="text-[14px] font-medium text-fg-muted">No session selected</p>
              <p className="text-[12px] text-fg-faint leading-relaxed max-w-[26ch]">
                Pick a session or use ↑ ↓ to navigate.
              </p>
            </div>
          )}
          {selected && !detail && !detailError && (
            <div className="p-8 max-w-[820px] mx-auto space-y-3 animate-pulse" aria-label="Loading conversation">
              <div className="h-14 bg-surface-overlay rounded-lg w-2/3 ml-auto" />
              <div className="h-3 bg-surface-overlay rounded w-1/4" />
              <div className="h-24 bg-surface-overlay rounded-lg w-5/6" />
              <div className="h-14 bg-surface-overlay rounded-lg w-1/2 ml-auto" />
            </div>
          )}
          {selected && detailError && (
            <div className="p-8">
              <p className="bg-danger-surface text-danger text-[12px] font-mono rounded px-4 py-2.5">
                Error: {detailError}
              </p>
            </div>
          )}
          {detail && (
            <Conversation
              detail={detail}
              machineName={
                (selected && (sessions.find((s) => s.id === selected)?.machine ?? localName)) || ""
              }
              machines={machines}
              shared={projectMachines.length > 1}
            />
          )}
        </main>
      </div>
    );
  }

  /* ── Landing: search + project tiles ── */
  const showResults = query.trim().length >= 2;

  return (
    <div className="h-full overflow-y-auto bg-surface select-none">
      <div className="px-10 py-7 pb-28 max-w-[1500px]">
        <div className="flex items-center gap-5 pb-6">
          <h1 className="text-[17px] font-semibold text-fg leading-none">Sessions</h1>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search prompts and content across every session…"
            aria-label="Search sessions"
            className="search-input flex-1 max-w-xl"
          />
        </div>

        {/* Stats strip */}
        <div className="flex items-end gap-10 pb-7 mb-7 border-b border-border">
          <Stat label="sessions" value={ready ? sessions.length : "…"} />
          <Stat label="projects" value={ready ? projects.length : "…"} />
          <Stat label="errors" value={ready ? sessions.reduce((a, s) => a + s.errors, 0) : "…"} />
          <Stat
            label="synced"
            value={ready ? sessions.filter((s) => s.machine).length : "…"}
          />
          <div className="flex-1 max-w-[360px] ml-auto self-end">
            <Spark list={sessions} />
            <p className="mt-1.5 text-[10.5px] uppercase tracking-[0.14em] text-fg-faint text-right">
              14-day activity
            </p>
          </div>
        </div>

        {showResults ? (
          <>
            <p className="text-[11px] font-mono text-fg-faint mb-3" role="status">
              {searching ? "searching…" : `${results?.length ?? 0} match${(results?.length ?? 0) === 1 ? "" : "es"}`}
            </p>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
              {(results ?? []).map((s) => (
                <SessionCard key={s.id} s={s} onOpen={openFromCard} machines={machines} localName={localName} />
              ))}
            </div>
          </>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
            {projects.map(([proj, list], idx) => {
              const errs = list.reduce((a, s) => a + s.errors, 0);
              const projMachines = [...new Set(list.map((s) => s.machine ?? localName).filter(Boolean))];
              const featured = idx === 0;
              return (
                <button
                  key={proj}
                  onClick={() => setActiveProject(proj)}
                  className={[
                    "group text-left bg-surface-raised border border-border rounded-xl px-5 py-4",
                    "hover:border-accent transition-colors duration-150",
                    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
                    featured ? "sm:col-span-2" : "",
                  ].join(" ")}
                >
                  <div className="flex items-baseline gap-2">
                    <p className="text-[13px] font-mono font-medium text-fg truncate group-hover:text-accent transition-colors duration-150">
                      {shortProject(proj)}
                    </p>
                    {featured && (
                      <span className="shrink-0 text-[9.5px] font-mono uppercase tracking-[0.12em] bg-accent-surface text-accent rounded px-1.5 py-px">
                        latest
                      </span>
                    )}
                    <span className="ml-auto shrink-0 text-[11px] font-mono text-fg-faint tabular-nums">
                      {relTime(list[0].mtime)}
                    </span>
                  </div>
                  <div className="mt-3 flex items-end gap-5">
                    <p
                      className={[
                        "leading-none font-semibold tracking-[-0.02em] text-fg tabular-nums",
                        featured ? "text-[46px]" : "text-[34px]",
                      ].join(" ")}
                    >
                      {list.length}
                      <span className="text-[12px] text-fg-faint font-normal ml-1.5">
                        session{list.length !== 1 ? "s" : ""}
                      </span>
                    </p>
                    <div className="flex-1 min-w-0">
                      <Spark list={list} tall={featured} />
                    </div>
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-[11px] font-mono text-fg-faint tabular-nums">
                    {errs > 0 ? <span className="text-danger">{errs} err</span> : <span>clean</span>}
                    {projMachines.map((m) => (
                      <MachineChip key={m} name={m} machines={machines} />
                    ))}
                    {projMachines.length > 1 && (
                      <span
                        className="text-[9.5px] uppercase tracking-[0.12em] bg-accent-surface text-accent rounded px-1.5 py-px"
                        title="Same repo, sessions from more than one machine"
                      >
                        shared
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
            {ready && projects.length === 0 && (
              <p className="text-[12px] text-fg-faint">No sessions found.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Conversation({ detail, machineName, machines, shared }: {
  detail: SessionDetail; machineName: string; machines: Machines; shared: boolean;
}) {
  const blocks = useMemo(() => toBlocks(detail.timeline), [detail]);
  return (
    <div className="px-8 py-6 max-w-[820px] mx-auto">
      <div className="mb-6 pb-3 border-b border-border flex items-center justify-between gap-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.10em] text-fg-faint truncate">
          {detail.project}
        </p>
        <div className="flex items-center gap-2 shrink-0">
          {machineName && <MachineChip name={machineName} machines={machines} />}
          {shared && (
            <span
              className="text-[9.5px] font-mono uppercase tracking-[0.12em] bg-accent-surface text-accent rounded px-1.5 py-px"
              title="This repo has sessions from more than one machine"
            >
              shared
            </span>
          )}
          <p className="text-[11px] font-mono text-fg-faint tabular-nums">
            {detail.timeline.length} events
          </p>
        </div>
      </div>
      <div className="space-y-4 pb-28">
        {blocks.map((b, i) => {
          if (b.kind === "activity") return <ActivityGroup key={i} items={b.items} />;
          if (b.kind === "image")
            return (
              <div key={i} className="flex justify-end">
                <img
                  src={`data:${b.item.media_type};base64,${b.item.data}`}
                  alt="attachment"
                  className="max-w-[420px] max-h-[320px] rounded-lg border border-border object-contain"
                />
              </div>
            );
          if (b.item.role === "user")
            return (
              <div key={i} className="flex justify-end">
                <div className="max-w-[78%] bg-user-surface border border-accent-surface rounded-lg rounded-br-sm px-4 py-3">
                  <Markdown>{b.item.text}</Markdown>
                </div>
              </div>
            );
          return (
            <div key={i} className="max-w-[92%]">
              <p className="text-[10px] font-mono uppercase tracking-[0.14em] text-fg-faint mb-1">
                claude
              </p>
              <Markdown>{b.item.text}</Markdown>
            </div>
          );
        })}
      </div>
    </div>
  );
}
