/**
 * The two list screens: sessions and memories.
 *
 * Both are the same shape — a table you move through on the left, what the
 * selected row holds on the right — because they answer the same kind of
 * question, and two shapes for that would be two things to learn.
 *
 * The selected row is reverse video across its whole width, which is why every
 * column here has an exact width and the row ends with a pad: Ink refuses a
 * `<Box>` inside a `<Text>`, so a row cannot be wrapped in one highlight — the
 * highlight has to be carried by each cell and then run out to the edge.
 */
import React from "react";
import { Box, Text } from "ink";
import { Field, Panel, Rule, ago, clip, inner } from "./theme.jsx";

/** The slice of a list a viewport `size` tall shows with `sel` inside it.
 *
 * Keeps the cursor off the very edge while there is list left on that side, so
 * you see where you are heading instead of discovering it a row late.
 */
export function slice(sel, total, size) {
  const margin = Math.min(2, Math.floor(size / 4));
  const top = Math.max(0, Math.min(sel - margin, total - size));
  return { top, end: top + size };
}

/** One cell of a highlighted row.
 *
 * Always exactly `w` columns: one character over and the row wraps, which on a
 * reverse-video line shows up as a second highlighted stripe. A right-aligned
 * cell keeps a trailing space — without it the number ends flush against the
 * next column and the two read as one token.
 */
function C({ w, on, dim, color, align = "left", children }) {
  const right = align === "right";
  const text = clip(children, Math.max(0, w - 1));
  const pad = " ".repeat(Math.max(0, w - text.length - (right ? 1 : 0)));
  return (
    <Text inverse={on} dimColor={dim && !on} color={on ? undefined : color}>
      {right ? pad + text + " " : text + pad}
    </Text>
  );
}

function Scrollbar({ top, size, total }) {
  if (total <= size) return <Box width={2} />;
  const h = Math.max(1, Math.round((size * size) / total));
  const at = Math.round((top / (total - size)) * (size - h));
  return (
    <Box flexDirection="column" marginLeft={1} width={1}>
      {Array.from({ length: size }, (_, i) => {
        const on = i >= at && i < at + h;
        return <Text key={i} dimColor={!on}>{on ? "█" : "│"}</Text>;
      })}
    </Box>
  );
}

/** Header row + rule, from a `[width, align, label]` spec. */
function Head({ cols }) {
  return (
    <Box flexDirection="column">
      <Box>
        {cols.map(([w, align, label], i) => (
          <C key={i} w={w} align={align} dim>{label}</C>
        ))}
      </Box>
      <Rule n={cols.reduce((a, c) => a + c[0], 0)} />
    </Box>
  );
}

// ── sessions ──

export function Sessions({ rows, sel, size, t, accent, width }) {
  const wide = width >= 112;
  const detailW = wide ? 38 : 0;
  const listW = width - detailW - (wide ? 2 : 1);
  const avail = inner(listW) - 2;                 // the scrollbar and its air
  const cols = [[11, "left", t("col_when")], [22, "left", t("col_project")],
                [9, "right", t("col_prompts")], [8, "right", t("col_tools")],
                [Math.max(10, avail - 50), "left", t("col_title")]];
  const { top, end } = slice(sel, rows.length, size);
  const cur = rows[sel];

  return (
    <Box gap={1}>
      <Panel title={`${t("tab_sessions")} · ${rows.length}`} accent={accent} width={listW}>
        <Head cols={cols} />
        <Box>
          <Box flexDirection="column" width={avail}>
            {rows.slice(top, end).map((r, i) => {
              const on = top + i === sel;
              return (
                <Box key={r.id}>
                  <C w={cols[0][0]} on={on} dim>{ago(r.mtime, t)}</C>
                  <C w={cols[1][0]} on={on} color={accent}>
                    {r.project}
                  </C>
                  <C w={cols[2][0]} on={on} align="right">{r.n_prompts}</C>
                  <C w={cols[3][0]} on={on} align="right" dim>{r.n_tools}</C>
                  <C w={cols[4][0]} on={on}>{r.title}</C>
                </Box>
              );
            })}
            {!rows.length && <Text dimColor>{t("empty")}</Text>}
          </Box>
          <Scrollbar top={top} size={size} total={rows.length} />
        </Box>
      </Panel>

      {wide && cur && (
        <Panel title={t("sec_detail")} accent={accent} width={detailW}>
          <Field label={t("col_project")} width={11}>
            <Text color={accent} wrap="truncate">{cur.project}</Text>
          </Field>
          <Field label={t("col_machine")} width={11}>
            <Text wrap="truncate">{cur.machine || t("this_one")}</Text>
          </Field>
          <Field label={t("col_when")} width={11}><Text>{ago(cur.mtime, t)}</Text></Field>
          <Box marginY={1}><Rule n={inner(detailW)} /></Box>
          <Field label={t("col_prompts")} width={11}><Text>{cur.n_prompts}</Text></Field>
          <Field label={t("col_tools")} width={11}><Text>{cur.n_tools}</Text></Field>
          <Field label={t("col_errors")} width={11}>
            <Text color={cur.errors ? "red" : undefined} dimColor={!cur.errors}>
              {cur.errors}
            </Text>
          </Field>
          <Box marginY={1}><Rule n={inner(detailW)} /></Box>
          <Text>{clip(cur.title, 400)}</Text>
        </Panel>
      )}
    </Box>
  );
}

// ── memories ──

export function Memories({ groups, sel, memSel, size, t, accent, width }) {
  const wide = width >= 92;
  const listW = wide ? 34 : width - 1;
  const detailW = width - listW - 2;
  const listAvail = inner(listW) - 2;
  const cur = groups[sel];
  const mems = cur ? cur.memories : [];
  const g = slice(sel, groups.length, size);
  const m = slice(memSel, mems.length, size);

  const memAvail = inner(detailW) - 2;
  const cols = [[30, "left", t("col_slug")], [11, "left", t("col_when")],
                [16, "left", t("col_machine")],
                [Math.max(10, memAvail - 57), "left", t("col_desc")]];

  return (
    <Box gap={1}>
      <Panel title={`${t("n_projects")} · ${groups.length}`} accent={accent} width={listW}>
        <Head cols={[[listAvail - 6, "left", t("col_project")], [6, "right", t("col_total")]]} />
        <Box>
          <Box flexDirection="column" width={listAvail}>
            {groups.slice(g.top, g.end).map((x, i) => {
              const on = g.top + i === sel;
              return (
                <Box key={x.project}>
                  <C w={listAvail - 6} on={on} color={accent}>
                    {x.project}
                  </C>
                  <C w={6} on={on} align="right" dim>{x.count}</C>
                </Box>
              );
            })}
            {!groups.length && <Text dimColor>{t("empty")}</Text>}
          </Box>
          <Scrollbar top={g.top} size={size} total={groups.length} />
        </Box>
      </Panel>

      {wide && (
        <Panel title={cur ? clip(cur.project, 40) : t("empty")} accent={accent} width={detailW}>
          {cur && (
            <Box marginBottom={1}>
              <Text dimColor>{t("sec_machines")}: </Text>
              <Text>{cur.machines.join(" · ")}</Text>
            </Box>
          )}
          <Head cols={cols} />
          <Box>
            <Box flexDirection="column" width={memAvail}>
              {mems.slice(m.top, m.end).map((x, i) => {
                const on = m.top + i === memSel;
                return (
                  <Box key={x.slug + x.machine}>
                    <C w={cols[0][0]} on={on}>{x.slug}</C>
                    <C w={cols[1][0]} on={on} dim>{ago(x.mtime, t)}</C>
                    <C w={cols[2][0]} on={on} dim>{x.machine}</C>
                    <C w={cols[3][0]} on={on} dim>{x.description}</C>
                  </Box>
                );
              })}
              {!mems.length && <Text dimColor>{t("empty")}</Text>}
            </Box>
            <Scrollbar top={m.top} size={size} total={mems.length} />
          </Box>
        </Panel>
      )}
    </Box>
  );
}
