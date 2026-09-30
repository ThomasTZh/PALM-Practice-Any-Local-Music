/**
 * Application state types (M0.8).
 */

export type ConnectionState =
  | 'connecting'
  | 'connected'
  | 'unavailable'
  | 'session-expired'

export interface ProjectSummary {
  id: string
  name: string
  status: 'empty' | 'ready'
  created_at: string
  updated_at: string
}

export type AppView =
  | { kind: 'connecting' }
  | { kind: 'unavailable' }
  | { kind: 'session-expired' }
  | { kind: 'project-list'; projects: ProjectSummary[] }
  | { kind: 'creating-project' }
  | { kind: 'project-open'; project: ProjectSummary }
  | { kind: 'api-error'; message: string }
