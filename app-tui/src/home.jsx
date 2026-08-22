/**
 * The home: what this machine holds, what the repo holds, and what a sync
 * would move between them.
 *
 * Every panel is given an exact width. Letting flexbox settle them looked fine
 * until a rule had to run to the edge of one — a rule cannot be measured after
 * the fact, so the widths are decided here and handed down.
 */
import React from "react";
import { Box, Text } from "ink";
import { Bar, BigNum, Cell, Field, Legend, Panel, Rule, clip, inner } from "./theme.jsx";

export const RAIL = 38;   // the left column
export const WIDE = 98;   // below this the two columns become one

/** The Δ columns of the prototype: how many items only one side has.
 *
 * `skills` is the only module where the engine knows this by name, so it is
 * the only one with an exact answer; for the rest the difference between the
 * two file counts is the honest approximation, and it is what the terminal TUI
 * already shows as `148 local · 149 in repo`.
 */
export function deltas(m, d) {
  if (m.id === "skills") return [d.localOnly.length, d.repoOnly.length];
  return [Math.max(0, m.localFiles - m.repoFiles), Math.max(0, m.repoFiles - m.localFiles)];
}

const DOT = {
  both: ["●", "green"], local: ["◐", "yellow"],
  repo: ["◑", "blue"], none: ["○", "gray"],
};

/** One headline number in the tall face, with its direction and its breakdown. */
function Traffic({ arrow, n, parts, label, accent, t, width }) {
  return (
    <Box>
      <Box width={3} flexDirection="column" justifyContent="center">
        <Text color={n ? accent : undefined} dimColor={!n} bold>{arrow}</Text>
      </Box>
      <BigNum value={n} accent={accent} muted={!n} />
      <Box flexDirection="column" marginLeft={2} width={width - 3 - 12}>
        <Text bold>{label}</Text>
        {(parts.length ? parts : [t("nothing")]).map((p) => (
          <Text key={p} dimColor wrap="truncate">{p}</Text>
        ))}
      </Box>
    </Box>
  );
}

/** A big number over its name — the tile the counters row is made of. */
function Stat({ n, label, accent }) {
  return (
    <Box flexDirection="column" marginRight={3} alignItems="center">
      <BigNum value={n} accent={accent} muted={!n} />
      <Text dimColor>{label}</Text>
    </Box>
  );
}

export default function Home({ d, t, accent, width }) {
  const sync = d.sync;
  const wide = width >= WIDE;
  const rail = wide ? RAIL : width - 1;
  const main = wide ? width - RAIL - 2 : width - 1;

  // one number for "how much of this machine is in the repo": the share of
  // items both sides hold, over everything either side holds
  const totals = d.modules.reduce((a, m) => {
    const [dl, dr] = deltas(m, d);
    return { same: a.same + Math.min(m.localFiles, m.repoFiles), drift: a.drift + dl + dr };
  }, { same: 0, drift: 0 });
  const parity = totals.same + totals.drift === 0
    ? 100 : Math.round((100 * totals.same) / (totals.same + totals.drift));
  const drifting = d.modules.some((m) => deltas(m, d).some(Boolean));
  const good = parity === 100 ? "green" : accent;

  // `Δ L` / `Δ R` and not the words: they wrap at this width, and the product
  // already spells these two sides `[L]` and `[R]` inside a module
  // the table is packed left and stops: stretched to the panel edge the name
  // and its numbers end up a screen apart and stop reading as one row
  const nameW = Math.min(24, Math.max(14, inner(main) - 30));
  const cols = [[nameW, "flex-start", ""], [8, "flex-end", t("local")],
                [9, "flex-end", t("in_repo")], [6, "flex-end", "Δ L"],
                [7, "flex-end", "Δ R"]];
  const tableW = cols.reduce((a, c) => a + c[0], 0);

  return (
    <Box flexDirection={wide ? "row" : "column"} gap={1} alignItems="flex-start">
      <Box flexDirection="column" gap={1}>
        <Panel title={t("sec_sync")} accent={accent} width={rail}>
          <Traffic arrow="▲" n={sync.toPush} parts={sync.pushParts} width={inner(rail)}
                   label={t("to_push")} accent={accent} t={t} />
          <Box marginY={1}><Rule n={inner(rail)} /></Box>
          <Traffic arrow="▼" n={sync.toPull} parts={sync.pullParts} width={inner(rail)}
                   label={t("to_pull")} accent={accent} t={t} />
          <Box marginTop={1} flexDirection="column">
            <Field label={t("last_sync")} width={12}>
              <Text wrap="truncate">{sync.lastSync}</Text>
            </Field>
            <Field label="git" width={12}>
              <Text>
                <Text color={accent}>↑{sync.ahead} ↓{sync.behind}</Text>
                <Text dimColor> · </Text>
                <Text color={sync.dirty ? "yellow" : "green"}>
                  {sync.dirty ? t("dirty") : t("clean")}
                </Text>
              </Text>
            </Field>
            <Text dimColor>{t("checked", { ago: sync.checkedAgo })}</Text>
            {!!d.update.available && (
              <Text color="green">▲ {t("update_available")}: {d.update.available}</Text>
            )}
          </Box>
        </Panel>

        <Panel title={t("sec_usage")} accent={accent} width={rail}>
          {(d.usage.limits || []).map((l, i) => (
            <Box key={i} flexDirection="column" marginTop={i ? 1 : 0}>
              <Box>
                <BigNum value={l.percent ?? 0} unit="%" accent={accent} />
                <Box flexDirection="column" marginLeft={2} justifyContent="center">
                  <Text bold>{clip((l.label || l.kind || "?").replace(/_/g, " "), 16)}</Text>
                  <Text dimColor>{l.resets}</Text>
                </Box>
              </Box>
              {/* 80 is where a limit stops being information and starts being a
                  warning, and the bar turns red on its own there */}
              <Bar pct={l.percent} accent={accent} width={inner(rail)} warn={80} />
            </Box>
          ))}
          {!(d.usage.limits || []).length && <Text dimColor>{t("no_usage")}</Text>}
        </Panel>
      </Box>

      <Box flexDirection="column" gap={1}>
        <Panel title={t("sec_parity")} accent={accent} width={main}>
          <Box>
            {cols.map(([w, align, label], i) => (
              <Cell key={i} w={w} align={align}><Text dimColor>{label}</Text></Cell>
            ))}
          </Box>
          <Rule n={tableW} />
          {d.modules.map((m) => {
            const [dl, dr] = deltas(m, d);
            const key = dl ? "local" : dr ? "repo" : m.localFiles ? "both" : "none";
            const [glyph, colour] = DOT[key];
            return (
              <Box key={m.id}>
                <Cell w={cols[0][0]}>
                  <Text>
                    <Text color={colour}>{glyph}</Text>
                    {/* a module that is not syncing is dim and nothing else:
                        the prototype spends no column on saying it twice */}
                    <Text dimColor={!m.enabled}> {m.id}</Text>
                  </Text>
                </Cell>
                <Cell w={cols[1][0]} align="flex-end"><Text>{m.localFiles}</Text></Cell>
                <Cell w={cols[2][0]} align="flex-end"><Text>{m.repoFiles}</Text></Cell>
                <Cell w={cols[3][0]} align="flex-end">
                  <Text color={dl ? "yellow" : undefined} dimColor={!dl}>{dl || "·"}</Text>
                </Cell>
                <Cell w={cols[4][0]} align="flex-end">
                  <Text color={dr ? "blue" : undefined} dimColor={!dr}>{dr || "·"}</Text>
                </Cell>
              </Box>
            );
          })}
          {/* the legend only when a row on this table is out of parity: on a
              tidy repo it would be four states none of which are on screen */}
          {drifting && (
            <Box marginTop={1}>
              <Legend items={[["●", "green", t("st_both")], ["◐", "yellow", t("st_local")],
                              ["◑", "blue", t("st_repo")], ["✕", "red", t("st_gone")]]} />
            </Box>
          )}
        </Panel>

        <Panel title={t("sec_general")} accent={accent} width={main}>
          <Box>
            <BigNum value={parity} unit="%" accent={good} />
            <Box flexDirection="column" marginLeft={2} justifyContent="center">
              <Text bold>{t("st_both")}</Text>
              <Bar pct={parity} accent={good} width={Math.min(40, inner(main) - 12)} />
            </Box>
          </Box>
          <Box marginY={1}><Rule n={inner(main)} /></Box>
          <Box flexWrap="wrap">
            {d.counters.map((c) => (
              <Stat key={c.key} n={c.n} label={t(c.key)} accent={accent} />
            ))}
          </Box>
          <Box marginTop={1} flexDirection="column">
            <Field label={t("sec_machines")} width={16}>
              <Text wrap="truncate">
                {d.machines.map((m) => m.name + (m.local ? ` (${t("this_one")})` : "")).join(" · ")}
              </Text>
            </Field>
            <Field label={t("sec_always")} width={16}>
              <Text dimColor wrap="truncate">
                {Object.entries(d.knowledge).map(([k, n]) => `${n} ${t("n_" + k)}`).join(" · ")}
              </Text>
            </Field>
          </Box>
        </Panel>
      </Box>
    </Box>
  );
}
