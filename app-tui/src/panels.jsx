/**
 * The two screens that are settings and reference: config and help.
 *
 * Config is the same list the terminal TUI shows — accent, language, badge,
 * what always syncs, and the modules — and `↵` changes the selected row, so it
 * is a settings screen and not a read-only copy of one.
 */
import React from "react";
import { Box, Text } from "ink";
import { Field, Panel, Rule, clip, inner } from "./theme.jsx";

/** The rows of the config screen, in the order the terminal TUI lists them.
 *
 * A flat list and not two panels: the cursor has to walk from the accent to
 * the last module without the arrow keys meaning something different halfway
 * down.
 */
export function configRows(d) {
  return [
    { kind: "head", key: "sec_prefs" },
    { kind: "accent" },
    { kind: "lang" },
    { kind: "badge" },
    { kind: "head", key: "sec_always" },
    ...Object.keys(d.knowledge).map((id) => ({ kind: "fixed", id })),
    { kind: "head", key: "sec_modules" },
    ...d.modules.map((m) => ({ kind: "module", id: m.id })),
  ];
}

/** The i18n key of the accent currently in use, or the raw code if the table
 *  ever grows one this front-end has not seen. */
const accentName = (d) =>
  (d.prefs.accents.find(([, code]) => code === d.prefs.accent) || [d.prefs.accent])[0];

/** Which rows `↵` does something to — the cursor skips the headings. */
export const isActionable = (r) => r.kind !== "head" && r.kind !== "fixed";

export function Config({ d, t, accent, width, sel, rows }) {
  const w = Math.min(76, width - 1);
  const lab = 22;
  const byId = Object.fromEntries(d.modules.map((m) => [m.id, m]));

  return (
    <Panel title={t("tab_config")} accent={accent} width={w}>
      {rows.map((r, i) => {
        const on = i === sel;
        const mark = <Text color={accent}>{on ? "›" : " "}</Text>;
        if (r.kind === "head")
          return (
            <Box key={i} marginTop={i ? 1 : 0}>
              <Text color={accent} bold>{t(r.key).toUpperCase()}</Text>
              <Text dimColor> </Text>
              <Rule n={inner(w) - t(r.key).length - 1} />
            </Box>
          );
        if (r.kind === "accent")
          return (
            <Box key={i}>
              {mark}
              <Field label={t("accent_color")} width={lab}>
                <Text color={accent} bold={on}>{t(accentName(d))}</Text>
              </Field>
              <Box marginLeft={2}>
                {d.prefs.accents.map(([, code]) => (
                  <Text key={code} backgroundColor={code === d.prefs.accent ? "white" : undefined}>
                    <Text color={ANSI[code]}>{"██"}</Text>
                  </Text>
                ))}
              </Box>
            </Box>
          );
        if (r.kind === "lang")
          return (
            <Box key={i}>
              {mark}
              <Field label={t("language")} width={lab}>
                <Text>
                  {d.prefs.langs.map((code, j) => (
                    <Text key={code}>
                      {j ? "  " : ""}
                      <Text color={code === d.prefs.lang ? accent : undefined}
                            bold={code === d.prefs.lang}
                            dimColor={code !== d.prefs.lang}>{code}</Text>
                    </Text>
                  ))}
                </Text>
              </Field>
            </Box>
          );
        if (r.kind === "badge")
          return (
            <Box key={i}>
              {mark}
              <Field label={t("badge_row")} width={lab}>
                <Text>
                  <Text color={d.prefs.badge ? accent : undefined} dimColor={!d.prefs.badge}>
                    {d.prefs.badge ? "[x]" : "[ ]"}
                  </Text>
                  <Text dimColor>{"  " + (d.prefs.badge ? t("badge_on") : t("badge_off"))}</Text>
                </Text>
              </Field>
            </Box>
          );
        if (r.kind === "fixed")
          return (
            <Box key={i}>
              <Text color="green"> ●</Text>
              <Field label={" " + t("n_" + r.id)} width={lab}>
                <Text>
                  {d.knowledge[r.id]}
                  <Text dimColor>{"   " + t("always_syncing")}</Text>
                </Text>
              </Field>
            </Box>
          );
        const m = byId[r.id];
        return (
          <Box key={i}>
            {mark}
            <Field label={r.id} width={lab}>
              <Text>
                <Text color={m.enabled ? accent : undefined} dimColor={!m.enabled}>
                  {m.enabled ? "[x]" : "[ ]"}
                </Text>
                <Text dimColor>
                  {"  " + (m.enabled ? t("syncing") : t("not_syncing"))}
                  {`   ${m.localFiles} ${t("local")} · ${m.repoFiles} ${t("in_repo")}`}
                </Text>
              </Text>
            </Field>
          </Box>
        );
      })}
    </Panel>
  );
}

// the swatch needs the real colour of each accent, not the one in use
const ANSI = { 36: "cyan", 32: "green", 35: "magenta", 34: "blue", 33: "yellow", 31: "red" };

/** The `sto` commands and what each one does, straight off the CLI registry.
 *
 * Keyboard shortcuts are not here: the action bar already shows the ones for
 * the screen you are on, and a second list of them goes stale on its own every
 * time a key moves.
 */
export function Help({ d, t, accent, width }) {
  const w = Math.min(96, width - 1);
  const col = Math.min(30, Math.max(12, Math.floor(inner(w) / 3)));
  return (
    <Panel title={t("sec_commands")} accent={accent} width={w}>
      {d.commands.map(([usage, what]) => (
        <Box key={usage}>
          <Box width={col}><Text color={accent}>{clip(usage, col - 1)}</Text></Box>
          <Box width={inner(w) - col}><Text dimColor>{what}</Text></Box>
        </Box>
      ))}
    </Panel>
  );
}
