import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D from "react-force-graph-3d";
import ForceGraph2D from "react-force-graph-2d";

export type GraphNode = {
  id: string;
  label: string;
  source_file?: string;
  community_name?: string;
  x?: number;
  y?: number;
  z?: number;
  fx?: number;
  fy?: number;
  fz?: number;
};
export type GraphLink = { source: string; target: string; relation?: string };
export type GraphData = { nodes: GraphNode[]; links: GraphLink[] };

// ponytail: layout cache per mode, by node id, module-level — survives remounts
// (theme change, tab switch) so the force sim runs once per graph, not per mount.
const posCache = {
  "3d": new Map<string, { x: number; y: number; z: number }>(),
  "2d": new Map<string, { x: number; y: number; z: number }>(),
};

/** Top-level folder a node comes from ("app", "scripts", …); "root" for loose files. */
export function nodeProject(n: GraphNode): string {
  const f = n.source_file ?? "";
  const i = f.indexOf("/");
  return i === -1 ? "root" : f.slice(0, i);
}

export default function Graph3D({
  data,
  showSearch = true,
  searchPosition = "left",
}: {
  data: GraphData;
  showSearch?: boolean;
  searchPosition?: "left" | "center";
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [screenPos, setScreenPos] = useState<{ x: number; y: number } | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<"3d" | "2d">("3d");
  const [size, setSize] = useState({ w: 800, h: 600 });
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() =>
      setSize({ w: el.clientWidth, h: el.clientHeight }),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Keep the info card glued below the selected node as the camera moves.
  useEffect(() => {
    if (!selected) {
      setScreenPos(null);
      return;
    }
    let raf = 0;
    const tick = () => {
      const c = fgRef.current?.graph2ScreenCoords(
        selected.x ?? 0,
        selected.y ?? 0,
        selected.z ?? 0,
      );
      if (c) setScreenPos({ x: c.x, y: c.y });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [selected]);

  // Apply cached layout (pin nodes) when every node id is known; else unpin so the sim can run.
  const cached = useMemo(() => {
    const cache = posCache[mode];
    const hit = data.nodes.length > 0 && data.nodes.every((n) => cache.has(n.id));
    for (const n of data.nodes) {
      if (hit) {
        const p = cache.get(n.id)!;
        n.x = p.x; n.y = p.y; n.fx = p.x; n.fy = p.y;
        if (mode === "3d") { n.z = p.z; n.fz = p.z; } else { n.fz = undefined; }
      } else {
        n.fx = n.fy = n.fz = undefined;
      }
    }
    return hit;
  }, [data, mode]);

  useEffect(() => {
    if (cached) setReady(true);
  }, [cached, mode]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return data.nodes.filter((n) => n.label.toLowerCase().includes(q)).slice(0, 12);
  }, [query, data]);

  function focusNode(n: GraphNode) {
    setSelected(n);
    setQuery("");
    if (mode === "2d") {
      fgRef.current?.centerAt(n.x ?? 0, n.y ?? 0, 800);
      fgRef.current?.zoom(3, 800);
      return;
    }
    const dist = 120;
    const ratio = 1 + dist / Math.hypot(n.x ?? 1, n.y ?? 1, n.z ?? 1);
    fgRef.current?.cameraPosition(
      { x: (n.x ?? 0) * ratio, y: (n.y ?? 0) * ratio, z: (n.z ?? 0) * ratio },
      { x: n.x ?? 0, y: n.y ?? 0, z: n.z ?? 0 },
      800,
    );
  }

  function switchMode(m: "3d" | "2d") {
    if (m === mode) return;
    setMode(m);
    setReady(false);
    setSelected(null);
  }

  // Props shared by both renderers (same react-force-graph API surface).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const commonProps: any = {
    graphData: data,
    width: size.w,
    height: size.h,
    backgroundColor:
      getComputedStyle(document.documentElement).getPropertyValue("--graph-bg").trim() || "#161310",
    nodeAutoColorBy: "community_name",
    nodeLabel: (n: GraphNode) =>
      `<div style="font:12px 'JetBrains Mono Variable',monospace"><b>${n.label}</b><br/>${n.source_file ?? ""}<br/><i>${n.community_name ?? ""}</i></div>`,
    nodeRelSize: 4,
    // Async sim (cooldown, not warmup) so the main thread stays responsive while the
    // hidden layout computes; frozen afterwards. Cached layouts skip the sim entirely.
    warmupTicks: 0,
    cooldownTicks: cached ? 0 : 120,
    linkColor: () => "rgba(170,155,140,0.25)",
    linkWidth: 0.5,
    onNodeClick: (n: GraphNode) => focusNode(n),
    onBackgroundClick: () => setSelected(null),
    onEngineStop: () => {
      const cache = posCache[mode];
      for (const n of data.nodes) {
        cache.set(n.id, { x: n.x ?? 0, y: n.y ?? 0, z: n.z ?? 0 });
        n.fx = n.x; n.fy = n.y;
        if (mode === "3d") n.fz = n.z;
      }
      setReady(true);
    },
  };

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      {!ready && (
        <div className="absolute inset-0 z-20 flex items-center justify-center">
          <p className="text-[12px] font-mono text-fg-faint animate-pulse select-none">
            computing graph layout…
          </p>
        </div>
      )}
      <div
        className={`h-full w-full transition-opacity duration-700 ${ready ? "opacity-100" : "opacity-0"}`}
      >
      {mode === "3d" ? (
        <ForceGraph3D ref={fgRef} {...commonProps} nodeResolution={4} showNavInfo={false} />
      ) : (
        <ForceGraph2D ref={fgRef} {...commonProps} />
      )}
      </div>

      {/* Controls hint, baseline-aligned with the dock text */}
      <p className="absolute bottom-4 right-5 h-[46px] flex items-center text-[10px] font-mono text-fg-faint select-none pointer-events-none">
        {mode === "3d" ? "drag rotate · wheel zoom · right-drag pan" : "drag pan · wheel zoom"}
      </p>

      {showSearch && (
        <div
          className={[
            "absolute top-3 w-80 select-none",
            searchPosition === "center" ? "left-1/2 -translate-x-1/2" : "left-3",
          ].join(" ")}
        >
          <div className="flex items-center gap-2">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search nodes…"
              aria-label="Search graph nodes"
              className="search-input flex-1 min-w-0"
            />
            <div
              role="group"
              aria-label="Graph view mode"
              className="flex shrink-0 rounded-lg border border-border bg-surface-raised/95 shadow-md overflow-hidden"
            >
              {(["3d", "2d"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => switchMode(m)}
                  aria-pressed={mode === m}
                  className={[
                    "px-3 py-2.5 text-[12px] font-mono uppercase transition-colors focus-visible:outline-none",
                    mode === m
                      ? "bg-accent-surface text-accent"
                      : "text-fg-muted hover:text-fg hover:bg-surface-overlay",
                  ].join(" ")}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
          {matches.length > 0 && (
            <ul className="mt-1 bg-surface-raised/95 border border-border rounded-md overflow-hidden">
              {matches.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => focusNode(n)}
                    className="w-full text-left px-2.5 py-1.5 text-[12px] text-fg hover:bg-surface-overlay focus-visible:outline-none focus-visible:bg-surface-overlay"
                  >
                    <span className="font-mono">{n.label}</span>
                    {n.community_name && (
                      <span className="ml-2 text-[10px] text-fg-faint">{n.community_name}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {selected && screenPos && (
        <div
          className="absolute z-10 w-64 bg-surface-raised/95 border border-border rounded-md px-4 py-3 select-text pointer-events-none shadow-lg"
          style={{
            // clamp horizontally so the card never runs off the edges; flip above the node near the bottom
            left: Math.min(Math.max(screenPos.x, 132), size.w - 132),
            top: screenPos.y > size.h - 140 ? undefined : screenPos.y + 14,
            bottom: screenPos.y > size.h - 140 ? size.h - screenPos.y + 14 : undefined,
            transform: "translateX(-50%)",
          }}
        >
          <p className="text-[13px] font-mono font-medium text-fg break-words">{selected.label}</p>
          {selected.source_file && (
            <p className="text-[11px] font-mono text-fg-muted mt-1 break-words">
              {selected.source_file}
            </p>
          )}
          {selected.community_name && (
            <p className="text-[11px] text-fg-faint mt-1">{selected.community_name}</p>
          )}
        </div>
      )}
    </div>
  );
}
