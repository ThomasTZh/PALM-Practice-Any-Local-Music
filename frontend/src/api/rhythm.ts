/**
 * Read-only rhythm grid API (M3.11/M3.17).
 *
 * Fetches the active branch's tempo/meter/bar-origin/pulse state and the
 * derived visible grid for a source-frame range. A project without a
 * complete active grid returns `null` rather than throwing, so the editor
 * can render a "no grid" state.
 */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'

const client = createApiClient()

export type RhythmGridData = components['schemas']['RhythmGridResponse']
export type RhythmGridDetail = components['schemas']['GridDetail']
export type RhythmGridEvent = components['schemas']['GridEvent']

export interface RhythmGridQuery {
  startFrame: number
  endFrame: number
  detail: RhythmGridDetail
}

export async function fetchRhythmGrid(
  projectId: string,
  query: RhythmGridQuery,
  signal?: AbortSignal,
): Promise<RhythmGridData | null> {
  const res = await client.GET('/api/v1/projects/{project_id}/rhythm-grid', {
    params: {
      path: { project_id: projectId },
      query: {
        start_frame: query.startFrame,
        end_frame: query.endFrame,
        detail: query.detail,
      },
    },
    signal,
  })
  if (res.response.status === 404) {
    const code =
      res.error && typeof res.error === 'object' && 'error' in res.error
        ? (res.error as { error?: { code?: string } }).error?.code
        : undefined
    if (code === 'RHYTHM_GRID_UNAVAILABLE') return null
  }
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Rhythm grid request failed (${res.response.status})`))
  }
  return res.data
}

export interface RhythmResultSummary {
  id: string
  run_id: string
  activation_artifact_id: string
  stage: string
  status: string
  decoder_profile_id: string
  accepted_count: number
  candidate_count: number
  created_at: string
}

export interface RhythmBranchSummary {
  id: string
  revision: number
  parent_automatic_result_id: string | null
  grid_validity: string
  pulse_count: number
  tempo_anchor_count: number
  meter_region_count: number
  updated_at: string
}

export async function listRhythmResults(
  projectId: string,
  signal?: AbortSignal,
): Promise<RhythmResultSummary[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/rhythm-results', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Rhythm results failed (${res.response.status})`))
  }
  return res.data as RhythmResultSummary[]
}

export async function listRhythmBranches(
  projectId: string,
  signal?: AbortSignal,
): Promise<RhythmBranchSummary[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/rhythm-branches', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Rhythm branches failed (${res.response.status})`))
  }
  return res.data as RhythmBranchSummary[]
}

export type RhythmRunSummary = components['schemas']['RhythmRunSummary']

export interface RhythmRunRequest {
  model_id?: string
  device?: string
  force_rerun?: boolean
  threads?: number
}

export async function startRhythmRun(
  projectId: string,
  request: RhythmRunRequest = {},
  signal?: AbortSignal,
): Promise<RhythmRunSummary> {
  const res = await client.POST('/api/v1/projects/{project_id}/rhythm-runs', {
    params: { path: { project_id: projectId } },
    body: { ...request, force_rerun: request.force_rerun ?? false },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Rhythm run failed (${res.response.status})`))
  }
  return res.data
}

export async function listRhythmRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<RhythmRunSummary[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/rhythm-runs', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Rhythm runs failed (${res.response.status})`))
  }
  return res.data
}

export async function getRhythmRun(
  projectId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<RhythmRunSummary> {
  const res = await client.GET('/api/v1/projects/{project_id}/rhythm-runs/{run_id}', {
    params: { path: { project_id: projectId, run_id: runId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Rhythm run failed (${res.response.status})`))
  }
  return res.data
}
