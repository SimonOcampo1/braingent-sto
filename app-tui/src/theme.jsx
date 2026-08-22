/**
 * The pieces every screen is built out of: the wordmark, the panels, the rules,
 * the bars, the key caps, and the two faces of type.
 *
 * Nothing here reads the API or knows what a sync is. If a component needs a
 * string it takes it already translated — the strings live in `i18n.py` and
 * travel in the payload, and this file must not be the place a Spanish or an
 * English word gets written down.
 */
import React from "react";
import { Box, Text } from "ink";

// `sto ui` stores the accent as a raw SGR code; Ink wants a name.
export const ACCENTS = {
  36: "cyan", 32: "green", 35: "magenta", 34: "blue", 33: "yellow", 31: "red",
};

// ── display face: a 7×6 pixel wordmark ──
//
// `ui.py` bevels its glyphs with ▄ and ▀ to buy height out of five rows. The
// prototype's letters are flat-topped pixels — no bevel anywhere — so this set
// is redrawn square and one row taller instead of imported.
//
// Block Elements are fixed width in Unicode, which is the whole reason the
// arithmetic works; an "ambiguous-width" character (▰, any emoji) would count
// as one code point and take two columns.
const GLYPHS = {
  B: ["██████ ", "██   ██", "██████ ", "██   ██", "██   ██", "██████ "],
  R: ["██████ ", "██   ██", "██████ ", "██  ██ ", "██   ██", "██   ██"],
  A: [" █████ ", "██   ██", "██   ██", "███████", "██   ██", "██   ██"],
  I: ["███████", "  ██   ", "  ██   ", "  ██   ", "  ██   ", "███████"],
  N: ["██   ██", "███  ██", "████ ██", "██ ████", "██  ███", "██   ██"],
  G: [" █████ ", "██   ██", "██     ", "██  ███", "██   ██", " █████ "],
  E: ["███████", "██     ", "█████  ", "██     ", "██     ", "███████"],
  T: ["███████", "  ██   ", "  ██   ", "  ██   ", "  ██   ", "  ██   "],
  S: [" ██████", "██     ", "██████ ", "     ██", "     ██", "██████ "],
  O: [" █████ ", "██   ██", "██   ██", "██   ██", "██   ██", " █████ "],
  " ": ["   ", "   ", "   ", "   ", "   ", "   "],
};

/** A word as rows of `"main" | "shadow" | null` cells.
 *
 * The prototype outlines every letter with an echo up and to the right. A
 * terminal cannot draw a hairline, but it can stamp the word a second time one
 * cell up-right in a dim texture and let the bright one land on top. Hence a
 * grid and not six strings: a row mixes the two colours.
 */
function stamp(word) {
  const rows = GLYPHS.B.length;
  const glyphs = [...word].map((ch) => GLYPHS[ch]);
  const w = glyphs.reduce((a, g) => a + g[0].length + 1, 0);
  const grid = Array.from({ length: rows + 1 }, () => Array(w + 1).fill(null));

  const paint = (dr, dc, layer, skip = () => false) => {
    let col = dc;
    for (const g of glyphs) {
      g.forEach((line, r) => {
        [...line].forEach((ch, i) => {
          const y = r + dr, x = col + i;
          if (ch !== " " && !grid[y][x] && !skip(y, x)) grid[y][x] = layer;
        });
      });
      col += g[0].length + 1;
    }
  };

  // the letters first: the echo only gets cells they do not want. The other
  // order eats them — a stroke is two columns wide, so a one-cell offset
  // overlaps it almost entirely and the word comes out a solid slab.
  paint(1, 0, "main");

  // and the counters stay hollow. The hole in a B or an O has to stay empty:
  // filled with echo the letters read as slugs. `inside` is the span each glyph
  // covers on each row, between its own first and last lit column — never
  // across the gap to the next letter, which is where the echo has to show.
  const inside = new Set();
  let col = 0;
  for (const g of glyphs) {
    g.forEach((line, r) => {
      const lo = line.indexOf("█"), hi = line.lastIndexOf("█");
      for (let i = lo + 1; i < hi; i++) inside.add(`${r + 1},${col + i}`);
    });
    col += g[0].length + 1;
  }
  paint(0, 1, "shadow", (y, x) => inside.has(`${y},${x}`));
  return grid;
}

// Four tiers and not two: the whole name is ~101 columns and the `STO` block is
// 25, so between them sits every ordinary 80-column terminal — which with two
// tiers got the smallest wordmark and two thirds of the row empty.
const FULL = stamp("BRAINGENT STO");
const MID = stamp("BRAINGENT");
const SHORT = stamp("STO");
const gridWidth = (g) => g[0].length;

function StampRow({ cells, accent }) {
  const runs = [];
  for (const cell of cells) {
    const last = runs[runs.length - 1];
    // ░ and not █ for the echo: at one cell of offset a solid halo reads as
    // part of the letter, and a lighter texture reads as behind it
    const ch = cell === "main" ? "█" : cell === "shadow" ? "░" : " ";
    if (last && last.layer === cell) last.text += ch;
    else runs.push({ layer: cell, text: ch });
  }
  return (
    <Text>
      {runs.map((r, i) =>
        r.layer === "main" ? <Text key={i} color={accent} bold>{r.text}</Text>
          : r.layer === "shadow" ? <Text key={i} dimColor>{r.text}</Text>
          : <Text key={i}>{r.text}</Text>
      )}
    </Text>
  );
}

export function Wordmark({ width, accent }) {
  // a wordmark cut in half is worse than a smaller wordmark, so the tiers step
  // down instead of clipping
  const grid = [FULL, MID, SHORT].find((g) => width >= gridWidth(g) + 4);
  if (!grid) return <Text color={accent} bold>braingent STO</Text>;
  return (
    <Box flexDirection="column" width={gridWidth(grid)}>
      {grid === SHORT && <Text bold>braingent</Text>}
      {grid.map((cells, i) => <StampRow key={i} cells={cells} accent={accent} />)}
      {grid === MID && (
        <Box justifyContent="flex-end"><Text color={accent} bold>S T O</Text></Box>
      )}
    </Box>
  );
}

// ── text face: three-row digits for the headline numbers ──
//
// Heavy box-drawing and not solid blocks: at three rows a block digit has one
// row per segment and 6 and 8 come out the same shape. These keep the strokes
// distinct while still reading as bold next to the wordmark. They are a second
// register on purpose — the wordmark is the product's name, this is a quantity.
const DIGITS = {
  "0": ["┏━┓", "┃ ┃", "┗━┛"],
  "1": ["╺┓ ", " ┃ ", "╺┻╸"],
  "2": ["╺━┓", "┏━┛", "┗━╸"],
  "3": ["╺━┓", "╺━┫", "╺━┛"],
  "4": ["╻ ╻", "┗━┫", "  ╹"],
  "5": ["┏━╸", "┗━┓", "╺━┛"],
  "6": ["┏━╸", "┣━┓", "┗━┛"],
  "7": ["╺━┓", "  ┃", "  ╹"],
  "8": ["┏━┓", "┣━┫", "┗━┛"],
  "9": ["┏━┓", "┗━┫", "╺━┛"],
};

/** A number in the tall face. `muted` draws a zero as what it is: nothing to do. */
export function BigNum({ value, accent, muted = false, unit = "" }) {
  const chars = [...String(value)].filter((c) => DIGITS[c]);
  const colour = muted ? undefined : accent;
  return (
    <Box>
      <Box flexDirection="column">
        {[0, 1, 2].map((r) => (
          <Text key={r} color={colour} dimColor={muted} bold={!muted}>
            {chars.map((c) => DIGITS[c][r]).join(" ")}
          </Text>
        ))}
      </Box>
      {!!unit && (
        <Box flexDirection="column" justifyContent="flex-end" marginLeft={1}>
          <Text color={colour} dimColor={muted}>{unit}</Text>
        </Box>
      )}
    </Box>
  );
}

// ── bars ──

// One cell is eight columns of resolution. Rounding to whole cells made 4% and
// 11% the same picture on a 14-wide bar, which is the opposite of a gauge.
const EIGHTHS = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"];

export function Bar({ pct, width = 20, accent, warn = 100 }) {
  const exact = Math.max(0, Math.min(1, (pct || 0) / 100)) * width;
  const full = Math.floor(exact);
  const tip = EIGHTHS[Math.floor((exact - full) * 8)];
  const colour = (pct || 0) >= warn ? "red" : accent;
  return (
    <Text>
      <Text color={colour}>{"█".repeat(full) + tip}</Text>
      <Text dimColor>{"░".repeat(Math.max(0, width - full - (tip ? 1 : 0)))}</Text>
    </Text>
  );
}

// ── panels, rules, cells ──

/** A rule of an exact length. Every caller knows its own width — a rule that
 *  fills with `wrap="truncate"` prints an ellipsis at the edge, and one that
 *  grows squeezes whatever shares its row until the text wraps. */
export function Rule({ n, char = "─" }) {
  return <Text dimColor>{char.repeat(Math.max(0, n))}</Text>;
}

/** How much room a panel of this outer width leaves inside: two border
 *  columns and two of padding. */
export const inner = (width) => Math.max(4, width - 4);

/** A titled panel: the title on the first inner row with a rule running to the
 *  edge, which is how the prototype separates a heading from its data. */
export function Panel({ title, accent, width, children, ...rest }) {
  const head = String(title).toUpperCase();
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray"
         paddingX={1} width={width} flexShrink={0} {...rest}>
      <Box>
        <Text color={accent} bold>{head}</Text>
        <Text dimColor> </Text>
        <Rule n={inner(width) - head.length - 1} />
      </Box>
      <Box flexDirection="column" marginTop={1}>{children}</Box>
    </Box>
  );
}

/** `label` dim in a fixed column, value hard against it, so a stack aligns. */
export function Field({ label, width = 14, children }) {
  return (
    <Box>
      {/* clipped to width-1: a label as long as its column leaves no gap and
          runs straight into the value */}
      <Box width={width}><Text dimColor>{clip(label, width - 1)}</Text></Box>
      {children}
    </Box>
  );
}

export function Cell({ w, children, align = "flex-start" }) {
  return <Box width={w} justifyContent={align} flexShrink={0}>{children}</Box>;
}

/** A key cap. `on={false}` says the key is there and would do nothing. */
export function Key({ k, label, on = true, accent }) {
  return (
    <Box marginRight={2}>
      <Text inverse={on} bold={on} dimColor={!on}> {k} </Text>
      <Text color={on ? accent : undefined} dimColor={!on}> {label}</Text>
    </Box>
  );
}

/** One entry of a legend: a coloured glyph and what it means. */
export function Legend({ items }) {
  return (
    <Text>
      {items.map(([glyph, colour, label], i) => (
        <Text key={i}>
          {i ? "   " : ""}
          <Text color={colour}>{glyph}</Text>
          <Text dimColor> {label}</Text>
        </Text>
      ))}
    </Text>
  );
}

// ── formatting ──

/** A unix timestamp as "3 h ago", in whatever language the payload came in.
 *
 * Same buckets as `ui.ago()` on the Python side. Reimplemented and not sent
 * per row because a list of 186 sessions would carry 186 pre-worded strings
 * that go stale the moment the screen sits open for a minute.
 */
export function ago(ts, t) {
  if (!ts) return t("ago_never");
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (secs < 60) return t("ago_now");
  if (secs < 3600) return t("ago_min", { n: Math.floor(secs / 60) });
  if (secs < 86400) return t("ago_hour", { n: Math.floor(secs / 3600) });
  return t("ago_day", { n: Math.floor(secs / 86400) });
}

/** Cut to `n` columns with an ellipsis, so a long title cannot break a table. */
export function clip(s, n) {
  const text = String(s ?? "").replace(/\s+/g, " ").trim();
  return text.length <= n ? text : text.slice(0, Math.max(0, n - 1)) + "…";
}
