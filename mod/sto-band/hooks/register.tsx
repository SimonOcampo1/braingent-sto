import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionContextUsage, SessionRateLimit } from 'claude-code'

import type { StoStatus, Usage } from '../types'

// The band asks `sto` for everything sync-related, so the rules stay in one
// place (scripts/cli.py) and the strings in scripts/i18n.py. What the engine
// already knows (limits, context) never leaves the engine.
const status = atom({ plugin: 'sto-band', key: 'status' } as const, null)
const error = atom({ plugin: 'sto-band', key: 'error' } as const, null)
const usage = atom({ plugin: 'sto-band', key: 'usage' } as const, {})
const isBusy = atom({ plugin: 'sto-band', key: 'isBusy' } as const, false)

const REFRESH_MS = 60_000
const ANSI: Record<string, string> = {
  '31': 'red', '32': 'green', '33': 'yellow',
  '34': 'blue', '35': 'magenta', '36': 'cyan',
}

export function toUsage(limits: readonly SessionRateLimit[], context: SessionContextUsage): Usage {
  const pct = (kind: string) => limits.find(l => l.kind === kind)?.percentUsed
  return { fiveHour: pct('five_hour'), week: pct('seven_day'), ctx: context.percent }
}

/** `sto mod <sub>` parsed, or the reason in one line. */
async function sto($: EngineInterface, sub: string): Promise<{ data?: StoStatus & { message?: string }; error?: string }> {
  try {
    const cwd = await $.session.cwd()
    const r = await $.process.run(['sto', 'mod', sub, '--cwd', cwd],
                                  { timeoutMs: sub === 'sync' ? 600_000 : 30_000 })
    const data = JSON.parse(r.stdout)
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
  const r = await sto($, 'status')
  await update($, error, () => r.error ?? null)
  if (r.data) await update($, status, () => r.data!)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'sto',
      description: '/sto sync: pull, keep and bring this project\'s chats, push. Bare: refresh the band',
    })
    void refresh($, true)
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
    if ((e.args ?? '').trim() !== 'sync') {
      await refresh($, true)
      return { text: (await read($, error)) ?? 'STO: ok' }
    }
    if (await read($, isBusy)) return { text: 'STO: ' + 'sync already running' }
    await update($, isBusy, () => true)
    try {
      const r = await sto($, 'sync')
      $.ui.toast(r.error ?? r.data?.message ?? 'STO: ok')
      return { text: r.error ?? r.data?.message ?? '' }
    } finally {
      await update($, isBusy, () => false)
      await refresh($, true)
    }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const s = await read($, status)
    const err = await read($, error)
    const u = await read($, usage)
    const busy = await read($, isBusy)
    const { Box, Text } = $.ui.resolve(e)
    const L = (k: string, en: string) => s?.labels?.[k] ?? en
    const accent = ANSI[s?.accent ?? '36'] ?? 'cyan'
    const pct = (label: string, v?: number) =>
      v === undefined ? null : <Text dimColor>{label} {Math.round(v)}%  </Text>

    return (
      <Box>
        <Text color={accent} bold>STO  </Text>
        {busy && <Text color={accent}>{L('mod_syncing', 'syncing...')}  </Text>}
        {!busy && s && (
          <Text>
            {L('mod_chats', 'chats')}{' '}
            {s.up || s.down
              ? <Text color={accent}>{'↑'}{s.up} {'↓'}{s.down}</Text>
              : <Text dimColor>{L('mod_uptodate', 'up to date')}</Text>}
            {!s.pathSaved && <Text color="warning">  {L('mod_no_path', 'no path')}</Text>}
            {(s.ahead > 0 || s.behind > 0) &&
              <Text dimColor>  {L('mod_repo', 'repo')} {'↑'}{s.ahead} {'↓'}{s.behind}</Text>}
            {'  '}
          </Text>
        )}
        {!busy && err && <Text color="warning">{err.slice(0, 60)}  </Text>}
        {pct(L('mod_5h', '5h'), u.fiveHour)}
        {pct(L('mod_week', 'wk'), u.week)}
        {pct(L('mod_ctx', 'ctx'), u.ctx)}
      </Box>
    )
  })
}
