import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionContextUsage, SessionRateLimit } from 'claude-code'

import type { StoStatus, Usage } from '../types'

// The band asks `sto` for everything sync-related, so the rules stay in one
// place (scripts/cli.py, scripts/ui_data.py) and the strings in scripts/i18n.py.
// It reads the same `sto data status` the TUI header reads: one number, two UIs.
const status = atom({ plugin: 'sto-band', key: 'status' } as const, null)
const error = atom({ plugin: 'sto-band', key: 'error' } as const, null)
const usage = atom({ plugin: 'sto-band', key: 'usage' } as const, {})
const isBusy = atom({ plugin: 'sto-band', key: 'isBusy' } as const, false)
const isAuto = atom({ plugin: 'sto-band', key: 'isAuto' } as const, true)

const REFRESH_MS = 60_000
// while a long fetch runs in the background, so its progress moves on screen
const FETCH_POLL_MS = 10_000
const AUTO_MS = 30 * 60_000
const ANSI: Record<string, string> = {
  '31': 'red', '32': 'green', '33': 'yellow',
  '34': 'blue', '35': 'magenta', '36': 'cyan',
}

export function toUsage(limits: readonly SessionRateLimit[], context: SessionContextUsage): Usage {
  const pct = (kind: string) => limits.find(l => l.kind === kind)?.percentUsed
  return { fiveHour: pct('five_hour'), week: pct('seven_day'), ctx: context.percent }
}

/** `sto <argv>`'s last stdout line as JSON: `sto act` prints steps before its
 *  final line, `sto data` prints one line. Or the reason, in one line. */
async function sto($: EngineInterface, argv: string[], long = false): Promise<{ data?: any; error?: string }> {
  try {
    const r = await $.process.run(['sto', ...argv], { timeoutMs: long ? 600_000 : 30_000 })
    const last = r.stdout.trim().split('\n').pop() ?? ''
    const data = JSON.parse(last)
    return data.error ? { error: data.error } : { data }
  } catch (err) {
    return { error: 'sto: ' + String((err as Error)?.message ?? err).slice(0, 80) }
  }
}

let lastAt = 0

/** Ask `sto` again, at most once a minute unless somebody pressed for it. */
async function refresh($: EngineInterface, force = false) {
  const now = await $.clock.now()
  if (!force && now - lastAt < REFRESH_MS) return
  lastAt = now
  const u = await $.session.usage()
  await update($, usage, () => toUsage(u.rateLimits, u.context))
  const cwd = await $.session.cwd()
  const r = await sto($, ['data', 'status', '--cwd', cwd, '--fetch'])
  await update($, error, () => r.error ?? r.data?.fetchError ?? null)
  if (r.data) await update($, status, () => r.data as StoStatus)
}

/** One sync at a time, whoever asked: the button, a command or the timer.
 *  `act sync --cwd` moves this project's chats too (the button and /sto sync);
 *  the timer's bare `act sync` carries memories and config. `quiet` toasts
 *  only a failure. */
async function runSync($: EngineInterface, argv: string[], quiet = false): Promise<string> {
  if (await read($, isBusy)) return (await read($, status))?.labels?.mod_syncing ?? 'syncing…'
  await update($, isBusy, () => true)
  let r: { data?: any; error?: string } = {}
  try {
    r = await sto($, argv, true)
  } finally {
    await update($, isBusy, () => false)
    await refresh($, true)
  }
  // after the refresh, or its fresh status would wipe the reason this sync failed
  if (r.error) await update($, error, () => r.error!)
  const text = r.error ?? r.data?.message ?? ''
  if (r.error || !quiet) $.ui.toast(text)
  return text
}

async function syncHere($: EngineInterface, quiet = false) {
  return runSync($, ['act', 'sync', '--cwd', await $.session.cwd()], quiet)
}

/** Auto on or off, remembered across sessions in the store. */
async function setAuto($: EngineInterface, isOn: boolean) {
  await $.store.set('auto', isOn)
  await update($, isAuto, () => isOn)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'sto',
      description: '/sto sync: sync now. /sto auto: auto sync on/off. Bare: the state in one line',
    })
    const auto = (await $.store.get('auto')) !== false
    await update($, isAuto, () => auto)
    // bring down before anything else: the memories another machine wrote land
    // before the first prompt reads them
    void (auto ? runSync($, ['act', 'pull'], true) : refresh($, true))
    $.clock.every(FETCH_POLL_MS, () => {
      void (async () => {
        if ((await read($, status))?.fetching) await refresh($, true)
      })()
    })
    $.clock.every(AUTO_MS, () => {
      void (async () => {
        if (await read($, isAuto)) await runSync($, ['act', 'sync'], true)
      })()
    })
    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    await update($, usage, () => toUsage(e.rateLimits, e.context))
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    void refresh($)
    return next(e)
  })

  on('command.run', { command: 'sto' }, async ($, e) => {
    const arg = (e.args ?? '').trim()
    if (arg === 'sync') return { text: await syncHere($) }
    if (arg === 'auto') {
      const turnOn = !(await read($, isAuto))
      await setAuto($, turnOn)
      return { text: 'braingent auto: ' + (turnOn ? 'on' : 'off') }
    }
    await refresh($, true)
    return { text: (await read($, error)) ?? (await read($, status))?.phrase ?? '' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const s = await read($, status)
    const err = await read($, error)
    const u = await read($, usage)
    const busy = await read($, isBusy)
    const auto = await read($, isAuto)
    const { Box, Button, Text } = $.ui.resolve(e)
    const L = (k: string, en: string) => s?.labels?.[k] ?? en
    const accent = ANSI[s?.accent ?? '36'] ?? 'cyan'
    const pct = (label: string, v?: number) =>
      v === undefined ? null : <Text dimColor>{label} {Math.round(v)}%  </Text>
    const f = s?.fetching
    const fetching = f && [L('fetching', 'fetching…'), f.phase === 'deltas' ? 'deltas' : '',
                            f.pct + '%', f.total ? `(${f.done}/${f.total})` : '', f.size ?? '']
                           .filter(Boolean).join(' ')
    const arrows = s ? [s.down ? '↓' + s.down : '', s.up ? '↑' + s.up : ''].filter(Boolean).join(' ') : ''

    return (
      <Box>
        <Text color={accent} bold>braingent  </Text>
        {busy && <Text color={accent}>{L('mod_syncing', 'syncing…')}  </Text>}
        {!busy && err && <Text color="warning">! {err.slice(0, 60)}  </Text>}
        {!busy && err && <Button key="retry" label={L('act_retry', 'retry')}
                                 onPress={() => void syncHere($)} />}
        {!busy && !err && fetching && <Text color={accent}>{fetching}  </Text>}
        {!busy && !err && !fetching && s?.state === 'pending' && <Text color={accent}>{arrows}  </Text>}
        {!busy && !err && !fetching && s?.state === 'pending' &&
          <Button key="sync" label={L('act_sync', 'Sync')} onPress={() => void syncHere($)} />}
        {!busy && !err && !fetching && s?.state === 'uptodate' && <Text dimColor>{s.phrase}  </Text>}
        {pct(L('mod_5h', '5h'), u.fiveHour)}
        {pct(L('mod_week', 'wk'), u.week)}
        {pct(L('mod_ctx', 'ctx'), u.ctx)}
        {!auto && <Button key="auto" dimColor label={L('mod_auto_off', 'auto: off')}
                          onPress={() => void setAuto($, true)} />}
      </Box>
    )
  })
}
