import { expect, mock, test } from 'claude-code/testing'

const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 3, bodyColumns: 120,
           scroll: { offset: 0, bodyRows: 1 }, view: {} },
} as const

const STATUS = {
  project: 'p', up: 2, down: 1, pathSaved: false, ahead: 0, behind: 0,
  fetchError: null, accent: '36',
  labels: { mod_chats: 'chats', mod_no_path: 'sin ruta', mod_ctx: 'ctx',
            mod_5h: '5h', mod_week: 'sem' },
}

test('the band shows the chats to move, the missing path and the windows', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const calls: string[][] = []
  on('session.cwd', async () => ({ value: '/work/p' }))
  on('session.usage', async () => ({ value: {
    startedAt: 0, context: { window: 200_000, percent: 22 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 34 }, { kind: 'seven_day', percentUsed: 61.4 }],
  } }))
  on('process.run', async (_$, e) => {
    calls.push([...e.argv])
    const out = e.argv[2] === 'sync' ? { ok: true, message: '3 synced' } : STATUS
    return { value: { exitCode: 0, stdout: JSON.stringify(out), stderr: '',
                       isStdoutTruncated: false, isStderrTruncated: false } }
  })

  const res = await $.command.run({ command: 'sto' } as never)
  expect(calls[0]).toEqual(['sto', 'mod', 'status', '--cwd', '/work/p'])
  expect(res.text).toBe('STO: ok')

  const ui = await $.ui.mount({ plugin: 'sto-band', surface: 'terminal', ...BAND })
  const text = (await ui.find({ type: 'Box' }))?.text ?? ''
  expect(text).toContain('↑2 ↓1')
  expect(text).toContain('sin ruta')
  expect(text).toContain('5h 34%')
  expect(text).toContain('sem 61%')
  expect(text).toContain('ctx 22%')
  await ui.unmount()

  const synced = await $.command.run({ command: 'sto', args: 'sync' } as never)
  expect(synced.text).toBe('3 synced')
  expect(calls.some(c => c[2] === 'sync')).toBe(true)
})
