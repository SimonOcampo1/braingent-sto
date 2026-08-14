import { useEffect, useState } from "react";
import DashboardPanel from "./DashboardPanel";
import SessionsPanel from "./SessionsPanel";
import SkillsPanel from "./SkillsPanel";
import {
  ACCENTS, FONTS, applyTheme, loadSettings, saveSettings, type ThemeSettings,
} from "./theme";

const VIEWS = [
  { id: "dashboard", label: "Dashboard", glyph: "⌂" },
  { id: "sessions", label: "Sessions", glyph: "❯" },
  { id: "skills", label: "Skills", glyph: "◆" },
] as const;
export type ViewId = (typeof VIEWS)[number]["id"];

const DARK_LEVELS = ["Dark", "Deeper", "OLED"] as const;

function Segment<T extends string | number>({
  options, value, onChange, label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex items-center gap-1 bg-surface-overlay rounded-full p-1">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={[
            "flex-1 rounded-full px-3 py-1.5 text-[11.5px] font-medium transition-colors duration-150",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
            o.value === value ? "bg-accent-surface text-accent" : "text-fg-muted hover:text-fg",
          ].join(" ")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<ViewId>("dashboard");
  const [settings, setSettings] = useState<ThemeSettings>(loadSettings);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    applyTheme(settings);
    saveSettings(settings);
  }, [settings]);

  const update = (patch: Partial<ThemeSettings>) => setSettings((s) => ({ ...s, ...patch }));
  // remount views on theme change so canvas colors (graph bg) pick up new vars
  const themeKey = `${settings.mode}-${settings.level}-${settings.hue}-${settings.font}`;

  return (
    <div className="relative h-screen bg-surface text-fg font-sans overflow-hidden">
      {/* ── Active view (full bleed; floating chrome sits on top) ── */}
      <div className="absolute inset-0" key={themeKey}>
        {view === "dashboard" && <DashboardPanel />}
        {view === "sessions" && <SessionsPanel />}
        {view === "skills" && <SkillsPanel />}
      </div>

      {/* ── Settings popover ── */}
      {settingsOpen && (
        <div className="absolute bottom-[76px] left-1/2 -translate-x-1/2 w-[360px] bg-surface-raised/95 backdrop-blur-sm border border-border rounded-2xl px-5 py-4 select-none space-y-4">
          <div>
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-fg-faint mb-2">
              Theme
            </p>
            <Segment
              label="Theme mode"
              options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]}
              value={settings.mode}
              onChange={(mode) => update({ mode })}
            />
            {settings.mode === "dark" && (
              <div className="mt-2">
                <Segment
                  label="Dark intensity"
                  options={DARK_LEVELS.map((l, i) => ({ value: i as 0 | 1 | 2, label: l }))}
                  value={settings.level}
                  onChange={(level) => update({ level })}
                />
              </div>
            )}
          </div>

          <div>
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-fg-faint mb-2">
              Accent
            </p>
            <div role="radiogroup" aria-label="Accent color" className="flex items-center gap-2.5">
              {ACCENTS.map((a) => {
                const active = settings.hue === a.hue;
                return (
                  <button
                    key={a.hue}
                    role="radio"
                    aria-checked={active}
                    aria-label={a.name}
                    title={a.name}
                    onClick={() => update({ hue: a.hue })}
                    className={[
                      "w-7 h-7 rounded-full transition-transform duration-150",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
                      active ? "ring-2 ring-fg scale-110" : "hover:scale-105",
                    ].join(" ")}
                    style={{
                      background: `oklch(${settings.mode === "dark" ? "0.71 0.14" : "0.52 0.15"} ${a.hue})`,
                    }}
                  />
                );
              })}
            </div>
          </div>

          <div>
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-fg-faint mb-2">
              Font
            </p>
            <Segment
              label="UI font"
              options={(Object.keys(FONTS) as ThemeSettings["font"][]).map((f) => ({
                value: f,
                label: FONTS[f].label,
              }))}
              value={settings.font}
              onChange={(font) => update({ font })}
            />
          </div>
        </div>
      )}

      {/* ── Unified floating dock: brand · nav · settings · status ── */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center bg-surface-raised/90 backdrop-blur-sm border border-border rounded-full pl-6 pr-5 py-1.5 select-none">
        {/* text-box trim: the box is cap-height → stable optical centring in any font */}
        <div className="flex items-center gap-2.5 pr-5">
          <span className="text-[20px] font-semibold tracking-[-0.01em] text-fg [text-box:trim-both_cap_alphabetic]">
            STO
          </span>
          <span className="text-[10px] font-mono uppercase tracking-[0.26em] text-accent whitespace-nowrap [text-box:trim-both_cap_alphabetic]">
            agentic os
          </span>
        </div>

        <nav aria-label="Main" className="flex items-center gap-1 border-l border-border pl-4">
          {VIEWS.map((v) => {
            const active = view === v.id;
            return (
              <button
                key={v.id}
                onClick={() => setView(v.id)}
                aria-current={active ? "page" : undefined}
                className={[
                  "flex items-center gap-2 rounded-full px-4 py-2 text-[12.5px] font-medium leading-none",
                  "transition-colors duration-150",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
                  active
                    ? "bg-accent-surface text-accent"
                    : "text-fg-muted hover:text-fg hover:bg-surface-overlay",
                ].join(" ")}
              >
                <span
                  aria-hidden
                  className={["font-mono text-[13px] leading-none", active ? "text-accent" : "text-fg-faint"].join(" ")}
                >
                  {v.glyph}
                </span>
                {v.label}
              </button>
            );
          })}
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            aria-expanded={settingsOpen}
            aria-label="Settings"
            className={[
              "rounded-full px-3 py-2 text-[13px] font-mono leading-none",
              "transition-colors duration-150",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
              settingsOpen
                ? "bg-accent-surface text-accent"
                : "text-fg-faint hover:text-fg hover:bg-surface-overlay",
            ].join(" ")}
          >
            ⚙
          </button>
          <button
            onClick={() => {
              if (!confirm("¿Cerrar el servidor?")) return;
              fetch("/api/exit", { method: "POST" }).catch(() => {});
            }}
            aria-label="Salir"
            title="Salir — detiene el servidor"
            className={[
              "flex items-center justify-center rounded-full px-3 py-2",
              "transition-colors duration-150",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
              "text-fg-faint hover:text-danger hover:bg-surface-overlay",
            ].join(" ")}
          >
            {/* SVG en vez de ⏻: el glifo cae en fuente fallback y queda desalineado */}
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.4" strokeLinecap="round" aria-hidden>
              <path d="M12 3v9" />
              <path d="M18.4 6.6a9 9 0 1 1-12.8 0" />
            </svg>
          </button>
        </nav>

        <p className="text-[10px] font-mono text-fg-faint whitespace-nowrap [text-box:trim-both_cap_alphabetic] border-l border-border pl-4 ml-3">
          local · 127.0.0.1
        </p>
      </div>
    </div>
  );
}
