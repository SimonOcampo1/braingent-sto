/** What `sto mod status` prints, or the reason it could not. */
export type StoStatus = {
  project: string
  up: number
  down: number
  pathSaved: boolean
  ahead: number
  behind: number
  fetchError: string | null
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
