/**
 * Application state types (M0.8).
 */

export type ConnectionState = 'connecting' | 'connected' | 'unavailable' | 'session-expired'

export interface ProjectSummary {
  id: string
  name: string
  status: 'empty' | 'ready'
  created_at: string
  updated_at: string
  /** Canonical PCM asset id; waveform caches are keyed to it (M1.10). */
  canonical_asset_id?: string | null
}

export type AppView =
  | { kind: 'connecting' }
  | { kind: 'unavailable' }
  | { kind: 'session-expired' }
  | { kind: 'project-list'; projects: ProjectSummary[] }
  | { kind: 'creating-project' }
  | { kind: 'project-open'; project: ProjectSummary }
  | { kind: 'api-error'; message: string }
