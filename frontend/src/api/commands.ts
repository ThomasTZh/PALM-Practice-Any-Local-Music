/**
 * Project command API module (M1.15).
 *
 * Typed wrappers for the project-command endpoint
 * (`POST /projects/{id}/commands`), undo/redo, and the project
 * snapshot fetch used for initial load and stale resync.
 *
 * Every command carries a fresh `command_id` and `idempotency_key`
 * (both `crypto.randomUUID()`); the base revision is supplied by the
 * caller (the `useProjectCommands` hook owns it).
 */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'

const client = createApiClient()

export type CommandOp = components['schemas']['CommandRequest']['op']
export type Marker = components['schemas']['MarkerRecord']
export type WorkingState = components['schemas']['WorkingState']
export type PracticeState = components['schemas']['PracticeState']
export type PracticeLoop = components['schemas']['PracticeLoop']
export type ProjectRhythmState = components['schemas']['ProjectRhythmState']

/** The resulting project state after a command (§17.4.5). */
export interface CommandResult {
  revision: number
  markers: Marker[]
  workingState: WorkingState
  practiceState: PracticeState | null
  canUndo: boolean
  canRedo: boolean
}

/** A project snapshot for initial load / stale resync. */
export interface ProjectSnapshot {
  status: 'empty' | 'ready'
  revision: number
  markers: Marker[]
  workingState: WorkingState
  practiceState: PracticeState | null
  canUndo: boolean
  canRedo: boolean
  sampleRate: number | null
  durationFrames: number | null
  rhythmState: ProjectRhythmState | null
}

/** Default working state (mirrors the server defaults, §17.5). */
export const DEFAULT_WORKING_STATE: WorkingState = {
  selection: null,
  viewport: null,
  channel_display: { linked: true, scales: [] },
  monitoring_volume: 1.0,
  last_position_frames: 0,
  follow_playhead: true,
}

/** Thrown when the base revision is stale (409 STALE_REVISION). */
export class StaleRevisionError extends Error {
  readonly currentRevision: number

  constructor(currentRevision: number) {
    super(`The project was modified elsewhere (current revision ${currentRevision})`)
    this.name = 'StaleRevisionError'
    this.currentRevision = currentRevision
  }
}

/** Extract the standard error code from an openapi-fetch error payload. */
function errorCodeOf(error: unknown): string | null {
  if (error && typeof error === 'object' && 'error' in error) {
    const inner = (error as { error?: { code?: string } }).error
    if (inner?.code) return inner.code
  }
  return null
}

function currentRevisionOf(error: unknown, fallback: number): number {
  if (error && typeof error === 'object' && 'error' in error) {
    const details = (error as { error?: { details?: { current_revision?: number } } }).error
      ?.details
    if (typeof details?.current_revision === 'number') return details.current_revision
  }
  return fallback
}

function toCommandResult(data: components['schemas']['CommandResult']): CommandResult {
  // The server always sends these fields; fall back at the boundary so a
  // partial payload (tests, older servers) never poisons hook state.
  return {
    revision: data.revision,
    markers: data.markers ?? [],
    workingState: data.working_state ?? DEFAULT_WORKING_STATE,
    practiceState: data.practice_state ?? null,
    canUndo: data.can_undo ?? false,
    canRedo: data.can_redo ?? false,
  }
}

/**
 * Apply one project command. Throws `StaleRevisionError` on a 409
 * stale-revision conflict and a plain `Error` (envelope message) on
 * any other failure.
 */
export async function sendCommand(
  projectId: string,
  baseRevision: number,
  op: CommandOp,
  signal?: AbortSignal,
): Promise<CommandResult> {
  const body: components['schemas']['CommandRequest'] = {
    command_id: crypto.randomUUID(),
    idempotency_key: crypto.randomUUID(),
    base_revision: baseRevision,
    op,
  }
  const res = await client.POST('/api/v1/projects/{project_id}/commands', {
    params: { path: { project_id: projectId } },
    body,
    signal,
  })
  if (res.response.status === 409 && errorCodeOf(res.error) === 'STALE_REVISION') {
    throw new StaleRevisionError(currentRevisionOf(res.error, baseRevision))
  }
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Command failed (${res.response.status})`))
  }
  return toCommandResult(res.data)
}

/** Undo the newest history entry (base-revision validated, §17.4.6). */
export async function undoCommand(
  projectId: string,
  baseRevision: number,
  signal?: AbortSignal,
): Promise<CommandResult> {
  const res = await client.POST('/api/v1/projects/{project_id}/undo', {
    params: { path: { project_id: projectId } },
    body: { base_revision: baseRevision },
    signal,
  })
  if (res.response.status === 409 && errorCodeOf(res.error) === 'STALE_REVISION') {
    throw new StaleRevisionError(currentRevisionOf(res.error, baseRevision))
  }
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Undo failed (${res.response.status})`))
  }
  return toCommandResult(res.data)
}

/** Redo the newest undone history entry (base-revision validated). */
export async function redoCommand(
  projectId: string,
  baseRevision: number,
  signal?: AbortSignal,
): Promise<CommandResult> {
  const res = await client.POST('/api/v1/projects/{project_id}/redo', {
    params: { path: { project_id: projectId } },
    body: { base_revision: baseRevision },
    signal,
  })
  if (res.response.status === 409 && errorCodeOf(res.error) === 'STALE_REVISION') {
    throw new StaleRevisionError(currentRevisionOf(res.error, baseRevision))
  }
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Redo failed (${res.response.status})`))
  }
  return toCommandResult(res.data)
}

/** Fetch the project snapshot (state, markers, undo/redo flags). */
export async function getProjectSnapshot(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectSnapshot> {
  const res = await client.GET('/api/v1/projects/{project_id}', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Project load failed (${res.response.status})`))
  }
  const data = res.data
  // The server always sends these fields, but the generated types mark
  // defaulted fields as optional; fall back at the boundary.
  return {
    status: data.status === 'ready' ? 'ready' : 'empty',
    revision: data.revision ?? 0,
    markers: data.markers ?? [],
    workingState: data.working_state ?? DEFAULT_WORKING_STATE,
    practiceState: data.practice_state ?? null,
    canUndo: data.can_undo ?? false,
    canRedo: data.can_redo ?? false,
    sampleRate: data.sample_rate ?? null,
    durationFrames: data.duration_frames ?? null,
    rhythmState: data.rhythm_state ?? null,
  }
}
