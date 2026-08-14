import { useEffect, useMemo, useState } from "react";
import type { SkillMeta, SkillDetail } from "./types";
import { fetchSkills, fetchSkill } from "./api";
import Markdown from "./Markdown";

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

/** Deterministic monogram tile: hue hashed from the skill name. */
function Monogram({ name, size = 34 }: { name: string; size?: number }) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return (
    <span
      aria-hidden
      className="shrink-0 grid place-items-center rounded-lg font-mono font-semibold"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.44,
        background: `oklch(0.30 0.06 ${h})`,
        color: `oklch(0.85 0.10 ${h})`,
      }}
    >
      {name[0]?.toUpperCase() ?? "?"}
    </span>
  );
}

export default function SkillsPanel({ focusId }: { focusId?: string | null }) {
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(focusId ?? null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null); // card or reader delete/uninstall pending
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [installName, setInstallName] = useState("");
  const [installMsg, setInstallMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [installing, setInstalling] = useState(false);

  function reload() {
    fetchSkills()
      .then((s) => { setSkills(s); setReady(true); })
      .catch((e) => setLoadError(String(e)));
  }

  useEffect(() => {
    reload();
    const t = setInterval(reload, 60_000); // stay in sync with installs/deletes elsewhere
    window.addEventListener("focus", reload);
    return () => { clearInterval(t); window.removeEventListener("focus", reload); };
  }, []);

  useEffect(() => {
    if (focusId) setSelected(focusId);
  }, [focusId]);

  useEffect(() => {
    setConfirmId(null);
    setActionMsg(null);
    if (!selected) {
      setDetail(null);
      return;
    }
    setDetail(null);
    setDetailError(null);
    const controller = new AbortController();
    fetchSkill(selected, controller.signal)
      .then(setDetail)
      .catch((e: unknown) => {
        if (e instanceof Error && e.name === "AbortError") return;
        setDetailError(String(e));
      });
    return () => controller.abort();
  }, [selected]);

  async function runPlugin(action: "install" | "uninstall", plugin: string) {
    const setMsg = action === "install" ? setInstallMsg : setActionMsg;
    const setBusyFn = action === "install" ? setInstalling : setBusy;
    setBusyFn(true);
    setMsg(null);
    try {
      const r = await fetch("/api/skills/plugin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, plugin }),
      });
      const d = await r.json();
      if (d.error) setMsg({ ok: false, text: d.error });
      else {
        setMsg({ ok: true, text: d.output || "done" });
        reload();
        if (action === "uninstall") setSelected(null);
      }
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusyFn(false);
      setConfirmId(null);
    }
  }

  async function deleteSkill(id: string) {
    setBusy(true);
    setActionMsg(null);
    try {
      const r = await fetch(`/api/skills/${encodeURIComponent(id)}`, { method: "DELETE" });
      const d = await r.json();
      if (d.error) setActionMsg({ ok: false, text: d.error });
      else {
        reload();
        if (selected === id) setSelected(null);
      }
    } catch (e) {
      setActionMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
      setConfirmId(null);
    }
  }

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const pool = q
      ? skills.filter(
          (s) =>
            s.name.toLowerCase().includes(q) ||
            s.source.toLowerCase().includes(q) ||
            s.description.toLowerCase().includes(q),
        )
      : skills;
    const by = new Map<string, SkillMeta[]>();
    for (const s of pool) {
      if (!by.has(s.source)) by.set(s.source, []);
      by.get(s.source)!.push(s);
    }
    return [...by.entries()].sort((a, b) =>
      a[0] === "personal" ? -1 : b[0] === "personal" ? 1 : a[0].localeCompare(b[0]),
    );
  }, [skills, filter]);

  const stats = useMemo(() => {
    const personal = skills.filter((s) => s.source === "personal").length;
    const sources = new Set(skills.map((s) => s.source));
    sources.delete("personal");
    return { total: skills.length, personal, plugin: skills.length - personal, plugins: sources.size };
  }, [skills]);

  if (loadError)
    return (
      <div className="h-full bg-surface flex items-center justify-center">
        <p className="bg-danger-surface text-danger text-[12px] font-mono rounded px-4 py-2.5">
          Error: {loadError}
        </p>
      </div>
    );

  /* ── Reader: markdown column + sticky action sidebar ── */
  if (selected) {
    return (
      <div className="h-full overflow-y-auto bg-surface select-text">
        <div className="px-10 py-6 pb-28 max-w-[1240px] mx-auto grid grid-cols-[minmax(0,1fr)_260px] gap-10">
          <div>
            <div className="flex items-center gap-3 pb-4 mb-6 border-b border-border select-none">
              <button
                onClick={() => setSelected(null)}
                aria-label="Back to skills"
                className="shrink-0 rounded-md px-2 py-1 text-[13px] text-fg-muted hover:bg-surface-overlay hover:text-fg transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
              >
                ← skills
              </button>
              {detail && (
                <h1 className="text-[17px] font-semibold font-mono text-fg">{detail.name}</h1>
              )}
            </div>
            {!detail && !detailError && <p className="text-[12px] text-fg-faint">Loading…</p>}
            {detailError && (
              <p className="bg-danger-surface text-danger text-[12px] font-mono rounded px-4 py-2.5">
                Error: {detailError}
              </p>
            )}
            {detail && <Markdown>{detail.body}</Markdown>}
          </div>

          {detail && (
            <aside className="select-none">
              <div className="sticky top-6 space-y-5">
                <div className="bg-surface-raised border border-border rounded-xl px-4 py-4">
                  <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-fg-faint mb-2">
                    About
                  </p>
                  <p className="text-[12px] text-fg-muted leading-relaxed select-text">
                    {detail.description || "No description."}
                  </p>
                  <dl className="mt-3 pt-3 border-t border-border space-y-1.5 text-[11px] font-mono">
                    <div className="flex justify-between gap-3">
                      <dt className="text-fg-faint">source</dt>
                      <dd className="text-fg-muted">{detail.source}</dd>
                    </div>
                    <div>
                      <dt className="text-fg-faint">path</dt>
                      <dd className="text-fg-muted break-all mt-0.5 select-text">{detail.path}</dd>
                    </div>
                  </dl>
                </div>

                <div className="bg-surface-raised border border-border rounded-xl px-4 py-4 space-y-2">
                  <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-fg-faint mb-1">
                    Actions
                  </p>
                  <a
                    href={`/api/skills/${encodeURIComponent(detail.id)}/export`}
                    download
                    className="block text-center rounded-md px-3 py-2 text-[12px] font-medium bg-surface-overlay text-fg hover:bg-accent-surface hover:text-accent transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
                  >
                    Export .zip
                  </a>
                  {detail.source === "personal" ? (
                    confirmId === detail.id ? (
                      <button
                        onClick={() => deleteSkill(detail.id)}
                        disabled={busy}
                        className="w-full rounded-md px-3 py-2 text-[12px] font-medium bg-danger-surface text-danger focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-danger disabled:opacity-40"
                      >
                        {busy ? "Deleting…" : "Confirm delete"}
                      </button>
                    ) : (
                      <button
                        onClick={() => setConfirmId(detail.id)}
                        className="w-full rounded-md px-3 py-2 text-[12px] font-medium bg-surface-overlay text-danger hover:bg-danger-surface transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-danger"
                      >
                        Delete skill
                      </button>
                    )
                  ) : confirmId === detail.id ? (
                    <button
                      onClick={() => runPlugin("uninstall", detail.source)}
                      disabled={busy}
                      className="w-full rounded-md px-3 py-2 text-[12px] font-medium bg-danger-surface text-danger focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-danger disabled:opacity-40"
                    >
                      {busy ? "Uninstalling…" : `Confirm uninstall`}
                    </button>
                  ) : (
                    <button
                      onClick={() => setConfirmId(detail.id)}
                      className="w-full rounded-md px-3 py-2 text-[12px] font-medium bg-surface-overlay text-danger hover:bg-danger-surface transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-danger"
                    >
                      Uninstall plugin {detail.source}
                    </button>
                  )}
                  {actionMsg && (
                    <p
                      role="status"
                      className={[
                        "text-[11px] font-mono leading-relaxed break-words pt-1",
                        actionMsg.ok ? "text-tool" : "text-danger",
                      ].join(" ")}
                    >
                      {actionMsg.text}
                    </p>
                  )}
                </div>
              </div>
            </aside>
          )}
        </div>
      </div>
    );
  }

  /* ── Landing: stats + search + grouped card grid ── */
  return (
    <div className="h-full overflow-y-auto bg-surface select-none">
      <div className="px-10 py-7 pb-28 max-w-[1500px]">
        <div className="flex items-center gap-5 pb-5">
          <h1 className="text-[17px] font-semibold text-fg leading-none">Skills</h1>
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search name, source or description…"
            aria-label="Search skills"
            className="search-input flex-1 max-w-xl"
          />
          <div className="flex items-center gap-2 ml-auto">
            <input
              value={installName}
              onChange={(e) => setInstallName(e.target.value)}
              placeholder="plugin@marketplace"
              aria-label="Plugin to install"
              className="w-56 bg-surface-raised border border-border text-fg text-[12px] font-mono rounded-lg px-3 py-2 placeholder:text-fg-faint focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <button
              onClick={() => installName.trim() && runPlugin("install", installName.trim())}
              disabled={installing || !installName.trim()}
              className="rounded-lg px-3.5 py-2 text-[12px] font-medium bg-accent-surface text-accent transition-colors duration-150 hover:bg-surface-overlay focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {installing ? "Installing…" : "Install"}
            </button>
          </div>
        </div>
        {installMsg && (
          <p
            role="status"
            className={[
              "mb-4 text-[11px] font-mono leading-relaxed break-words",
              installMsg.ok ? "text-tool" : "text-danger",
            ].join(" ")}
          >
            {installMsg.text}
          </p>
        )}

        {/* Stats strip */}
        <div className="flex items-end gap-10 pb-7 mb-7 border-b border-border">
          <Stat label="installed" value={ready ? stats.total : "…"} />
          <Stat label="personal" value={ready ? stats.personal : "…"} />
          <Stat label="from plugins" value={ready ? stats.plugin : "…"} />
          <Stat label="plugins" value={ready ? stats.plugins : "…"} />
        </div>

        {actionMsg && (
          <p
            role="status"
            className={[
              "mb-4 text-[11px] font-mono leading-relaxed break-words",
              actionMsg.ok ? "text-tool" : "text-danger",
            ].join(" ")}
          >
            {actionMsg.text}
          </p>
        )}

        {groups.map(([source, list]) => (
          <section key={source} className="mb-8">
            <div className="flex items-baseline gap-2.5 mb-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-faint">
                {source}
              </h2>
              <span className="text-[11px] font-mono text-fg-faint tabular-nums">{list.length}</span>
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
              {list.map((s) => (
                <div
                  key={s.id}
                  className="group flex flex-col bg-surface-raised border border-border rounded-xl px-4 pt-3.5 pb-2.5 hover:border-accent transition-colors duration-150"
                >
                  <button
                    onClick={() => setSelected(s.id)}
                    className="flex items-start gap-3 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent rounded"
                  >
                    <Monogram name={s.name} />
                    <span className="min-w-0">
                      <p className="text-[13px] font-mono font-medium text-fg truncate group-hover:text-accent transition-colors duration-150">
                        {s.name}
                      </p>
                      <p className="mt-1 text-[11.5px] text-fg-faint leading-relaxed line-clamp-2 min-h-[2em]">
                        {s.description || "No description."}
                      </p>
                    </span>
                  </button>
                  <div className="mt-2.5 pt-2 border-t border-border flex items-center gap-1">
                    <a
                      href={`/api/skills/${encodeURIComponent(s.id)}/export`}
                      download
                      className="rounded px-1.5 py-0.5 text-[10.5px] font-mono text-fg-faint hover:text-fg hover:bg-surface-overlay transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
                    >
                      export
                    </a>
                    {s.source === "personal" &&
                      (confirmId === s.id ? (
                        <button
                          onClick={() => deleteSkill(s.id)}
                          disabled={busy}
                          className="rounded px-1.5 py-0.5 text-[10.5px] font-mono bg-danger-surface text-danger focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-danger disabled:opacity-40"
                        >
                          {busy ? "deleting…" : "confirm?"}
                        </button>
                      ) : (
                        <button
                          onClick={() => setConfirmId(s.id)}
                          className="rounded px-1.5 py-0.5 text-[10.5px] font-mono text-fg-faint hover:text-danger hover:bg-danger-surface transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-danger"
                        >
                          delete
                        </button>
                      ))}
                    <span className="ml-auto text-[10px] font-mono text-fg-faint">{s.source}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
        {ready && groups.length === 0 && (
          <p className="text-[12px] text-fg-faint">No skills match.</p>
        )}
      </div>
    </div>
  );
}
