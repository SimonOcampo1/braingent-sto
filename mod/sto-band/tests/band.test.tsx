import { expect, mock, test } from 'claude-code/testing'

const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 3, bodyColumns: 120,
           scroll: { offset: 0, bodyRows: 1 }, view: {} },
} as const

const LABELS = { act_sync: 'Sincronizar', act_retry: 'reintentar', mod_syncing: 'sincronizando…',
                 mod_auto_off: 'auto: no', mod_5h: '5h', mod_week: 'sem', mod_ctx: 'ctx' }
const PENDING = { state: 'pending', down: 51, up: 2, phrase: '51 nuevas en la nube · 2 para subir',
                  fetchError: null, fetching: null, accent: '36', labels: LABELS }
const UPTODATE = { ...PENDING, state: 'uptodate', down: 0, up: 0, phrase: 'al día' }

function fake(on: any, status: object, calls: string[][] = []) {
  on('session.cwd', async () => ({ value: '/work/p' }))
  on('session.usage', async () => ({ value: {
    startedAt: 0, context: { window: 200_000, percent: 22 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 34 }, { kind: 'seven_day', percentUsed: 61.4 }],
  } }))
  on('process.run', async (_$: unknown, e: any) => {
    calls.push([...e.argv])
    const out = e.argv[1] === 'data' ? status
      : JSON.stringify({ step: 'x' }) + '\n' + JSON.stringify({ done: true, message: 'sincronizado' })
    return { value: { exitCode: 0, stdout: typeof out === 'string' ? out : JSON.stringify(out),
                      stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
}

test('pending: arrows, one Sync button, the plan windows', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const calls: string[][] = []
  fake(on, PENDING, calls)
  const res = await $.command.run({ command: 'sto' } as never)
  expect(calls[0]).toEqual(['sto', 'data', 'status', '--cwd', '/work/p', '--fetch'])
  expect(res.text).toBe(PENDING.phrase)

  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  const text = (await ui.find({ type: 'Box' }))?.text ?? ''
  expect(text).toContain('braingent')
  expect(text).toContain('↓51 ↑2')
  expect(text).not.toContain('repo')
  expect(text).toContain('5h 34%')
  expect(text).toContain('ctx 22%')
  expect(!!(await ui.find({ key: 'auto' }))).toBe(false)
  await ui.press({ key: 'sync' })
  expect(calls.some(c => c.join(' ') === 'sto act sync --cwd /work/p')).toBe(true)
  await ui.unmount()
})

test('up to date: the phrase and no button; auto off shows and is remembered', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const saved: unknown[] = []
  on('store.set', async (_$, e) => (saved.push(e), { value: undefined }))
  fake(on, UPTODATE)
  await $.command.run({ command: 'sto' } as never)
  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  expect((await ui.find({ type: 'Box' }))?.text).toContain('al día')
  expect(!!(await ui.find({ key: 'sync' }))).toBe(false)
  await ui.unmount()

  const off = await $.command.run({ command: 'sto', args: 'auto' } as never)
  expect(off.text).toContain('off')
  expect(JSON.stringify(saved)).toContain('false')
  const ui2 = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  expect((await ui2.find({ key: 'auto' }))?.text).toContain('auto: no')
  await ui2.unmount()
})

test('a failed sync says why and offers retry', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  on('session.cwd', async () => ({ value: '/work/p' }))
  on('session.usage', async () => ({ value: { startedAt: 0, context: { window: 1 }, rateLimits: [] } }))
  on('process.run', async (_$, e) => {
    const out = e.argv[1] === 'data' ? PENDING : { error: 'sin conexión' }
    return { value: { exitCode: 0, stdout: JSON.stringify(out), stderr: '',
                      isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const res = await $.command.run({ command: 'sto', args: 'sync' } as never)
  expect(res.text).toBe('sin conexión')
  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  expect((await ui.find({ type: 'Box' }))?.text).toContain('! sin conexión')
  expect(!!(await ui.find({ key: 'retry' }))).toBe(true)
  await ui.unmount()
})

test('a long fetch shows its progress, not a red error', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  fake(on, { ...PENDING, labels: { ...LABELS, fetching: 'fetcheando…' },
             fetching: { phase: 'objects', pct: 53, done: 3449, total: 6453, size: '145.71 MiB' } })
  await $.command.run({ command: 'sto' } as never)
  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  const text = (await ui.find({ type: 'Box' }))?.text ?? ''
  expect(text).toContain('fetcheando… 53% (3449/6453) 145.71 MiB')
  expect(text).not.toContain('!')
  expect(!!(await ui.find({ key: 'sync' }))).toBe(false)
  await ui.unmount()
})
