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
