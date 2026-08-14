/** Theme engine: everything is CSS variables, so switching = restyling :root. */

export type ThemeSettings = {
  mode: "light" | "dark";
  /** dark intensity: 0 = graphite (default), 1 = deeper, 2 = OLED black */
  level: 0 | 1 | 2;
  /** accent hue in OKLCH degrees */
  hue: number;
  font: "archivo" | "system" | "mono";
};

export const DEFAULTS: ThemeSettings = { mode: "dark", level: 0, hue: 55, font: "archivo" };
const KEY = "sto-theme";

export const ACCENTS: { name: string; hue: number }[] = [
  { name: "copper", hue: 55 },
  { name: "coral", hue: 25 },
  { name: "gold", hue: 95 },
  { name: "jade", hue: 165 },
  { name: "azul", hue: 245 },
  { name: "violeta", hue: 305 },
];

export const FONTS: Record<ThemeSettings["font"], { label: string; stack: string }> = {
  archivo: { label: "Archivo", stack: '"Archivo Variable", system-ui, sans-serif' },
  system: { label: "System", stack: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
  mono: { label: "Mono", stack: '"JetBrains Mono Variable", ui-monospace, monospace' },
};

export function loadSettings(): ThemeSettings {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
  } catch {
    return DEFAULTS;
  }
}

export function saveSettings(s: ThemeSettings) {
  localStorage.setItem(KEY, JSON.stringify(s));
}

// surface, raised, overlay, border, border-strong, code-bg lightness per dark level
const DARK_L: [number, number, number, number, number, number][] = [
  [0.14, 0.172, 0.225, 0.28, 0.36, 0.115],
  [0.10, 0.135, 0.19, 0.245, 0.33, 0.08],
  [0.0, 0.075, 0.135, 0.205, 0.30, 0.045], // OLED: true black canvas
];
const GRAPH_BG = ["#161310", "#0c0a08", "#000000", "#f3efe9"]; // three.js can't parse oklch

export function applyTheme(s: ThemeSettings) {
  const r = document.documentElement.style;
  const set = (k: string, v: string) => r.setProperty(k, v);
  const h = s.hue;

  if (s.mode === "dark") {
    const [su, ra, ov, bo, bs, code] = DARK_L[s.level];
    const chroma = s.level === 2 ? 0 : 0.006; // OLED base stays pure black
    set("--color-surface", `oklch(${su} ${chroma} 70)`);
    set("--color-surface-raised", `oklch(${ra} 0.008 70)`);
    set("--color-surface-overlay", `oklch(${ov} 0.010 70)`);
    set("--color-border", `oklch(${bo} 0.012 70)`);
    set("--color-border-strong", `oklch(${bs} 0.014 70)`);
    set("--color-code", `oklch(${code} 0.006 70)`);
    set("--color-fg", "oklch(0.93 0.006 80)");
    set("--color-fg-muted", "oklch(0.67 0.010 75)");
    set("--color-fg-faint", "oklch(0.47 0.010 75)");
    set("--color-accent", `oklch(0.71 0.14 ${h})`);
    set("--color-accent-surface", `oklch(${s.level === 2 ? 0.17 : 0.215} 0.040 ${h})`);
    set("--color-user-surface", `oklch(${s.level === 2 ? 0.15 : 0.195} 0.028 ${h})`);
    set("--color-tool", "oklch(0.70 0.10 165)");
    set("--color-tool-surface", `oklch(${s.level === 2 ? 0.15 : 0.195} 0.028 165)`);
    set("--color-danger", "oklch(0.66 0.20 25)");
    set("--color-danger-surface", `oklch(${s.level === 2 ? 0.16 : 0.20} 0.035 25)`);
    set("--graph-bg", GRAPH_BG[s.level]);
  } else {
    set("--color-surface", "oklch(0.975 0.004 80)");
    set("--color-surface-raised", "oklch(0.945 0.006 80)");
    set("--color-surface-overlay", "oklch(0.90 0.008 80)");
    set("--color-border", "oklch(0.86 0.010 80)");
    set("--color-border-strong", "oklch(0.76 0.012 80)");
    set("--color-code", "oklch(0.93 0.006 80)");
    set("--color-fg", "oklch(0.24 0.010 75)");
    set("--color-fg-muted", "oklch(0.46 0.012 75)");
    set("--color-fg-faint", "oklch(0.60 0.010 75)");
    set("--color-accent", `oklch(0.52 0.15 ${h})`);
    set("--color-accent-surface", `oklch(0.90 0.05 ${h})`);
    set("--color-user-surface", `oklch(0.92 0.035 ${h})`);
    set("--color-tool", "oklch(0.45 0.10 165)");
    set("--color-tool-surface", "oklch(0.90 0.04 165)");
    set("--color-danger", "oklch(0.53 0.20 25)");
    set("--color-danger-surface", "oklch(0.92 0.04 25)");
    set("--graph-bg", GRAPH_BG[3]);
  }
  set("--font-sans", FONTS[s.font].stack);
}
