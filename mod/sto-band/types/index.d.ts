/** What `sto data status` prints (the fields the band reads). */
export type StoStatus = {
  state: 'uptodate' | 'pending'
  down: number
  up: number
  phrase: string
  fetchError: string | null
  /** a background `git fetch` still running, and how far it got */
  fetching: { phase: 'objects' | 'deltas'; pct: number; done: number; total: number; size: string | null } | null
  accent: string
  labels: Record<string, string>
}

export type Usage = { fiveHour?: number; week?: number; ctx?: number }

declare module 'claude-code' {
  interface PluginState {
    'sto-band': {
      status: StoStatus | null
      error: string | null
      usage: Usage
      isBusy: boolean
      isAuto: boolean
    }
  }
}
