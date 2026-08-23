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

/** The word as rows of half-block characters.
 *
 * Six pixel rows become three character rows: `█` where both halves of the
 * cell are lit, `▀` for the top half only, `▄` for the bottom. The letterforms
 * are the prototype's; what changes is that a banner costs three rows instead
 * of seven, and the screen under it is the point of the screen.
 *
 * The dotted echo that used to outline the letters is gone. At this size `░`
 * is not an outline, it is grit around clean shapes — and next to borders that
 * are a single crisp line it read as the one dirty thing on the page.
 */
function stamp(word) {
  const glyphs = [...word].map((ch) => GLYPHS[ch]);
  const out = [];
  for (let r = 0; r < GLYPHS.B.length; r += 2) {
    let line = "";
    glyphs.forEach((g, i) => {
      const top = g[r], bot = g[r + 1];
      for (let x = 0; x < top.length; x++) {
        const a = top[x] !== " ", b = bot[x] !== " ";
        line += a && b ? "█" : a ? "▀" : b ? "▄" : " ";
      }
      if (i < glyphs.length - 1) line += " ";
    });
    out.push(line);
  }
  return out;
}

// Four tiers: the whole name is ~99 columns and the `STO` block is 23, so
// between them sits every ordinary 80-column terminal — which with two tiers
// got the smallest wordmark and two thirds of the row empty.
const FULL = stamp("BRAINGENT STO");
const MID = stamp("BRAINGENT");
const SHORT = stamp("STO");
const gridWidth = (g) => g[0].length;

export function Wordmark({ width, accent }) {
  // a wordmark cut in half is worse than a smaller wordmark, so the tiers step
  // down instead of clipping
  const grid = [FULL, MID, SHORT].find((g) => width >= gridWidth(g) + 4);
  if (!grid) return <Text color={accent} bold>braingent STO</Text>;
  return (
    <Box flexDirection="column" width={gridWidth(grid)}>
      {grid === SHORT && <Text bold>braingent</Text>}
      {grid.map((line, i) => <Text key={i} color={accent} bold>{line}</Text>)}
      {grid === MID && (
        <Box justifyContent="flex-end"><Text color={accent} bold>S T O</Text></Box>
      )}
    </Box>
  );
}

/** A headline number: the value in the accent, its unit and name beside it.
 *
 * This used to be drawn in a three-row box-drawing face. It was legible and it
 * was wrong — the numbers on this screen are read, not admired, and at three
 * rows each they pushed the actual table off the fold.
 */
export function Stat({ n, label, unit = "", accent, muted = false, width }) {
  return (
    <Box width={width}>
      <Text color={muted ? undefined : accent} dimColor={muted} bold={!muted}>
        {String(n) + unit}
      </Text>
      <Text dimColor>{" " + label}</Text>
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
  const rest = Math.max(0, width - full - (tip ? 1 : 0));
  // The track is painted, not drawn: `░` is a field of dots you can see the
  // terminal through, and next to a border that is one crisp line it reads as
  // the dirty thing on the page. The fill stays a block character so the bar
  // still says something with colour off, and the partial tip sits on the
  // painted track, which is what makes the eighth exact instead of a seam.
  return (
    <Text>
      <Text color={colour}>{"█".repeat(full)}</Text>
      {!!tip && <Text color={colour} backgroundColor="gray">{tip}</Text>}
      <Text backgroundColor="gray">{" ".repeat(rest)}</Text>
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
      {/* the cap is drawn the same whether or not the key would do something:
          it is what tells you a key exists, and PUSH with nothing to push had
          no cap at all — which read as PUSH not being a key on this screen */}
      <Text inverse bold> {k} </Text>
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
