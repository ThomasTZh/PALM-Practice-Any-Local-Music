/** Read-only metronome schedule API (M3.14). */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'

const client = createApiClient()

export type MetronomeScheduleData = components['schemas']['MetronomeSchedule']

export async function fetchMetronomeSchedule(
  projectId: string,
  startFrame: number,
  endFrame: number,
  signal?: AbortSignal,
): Promise<MetronomeScheduleData> {
  const res = await client.POST('/api/v1/projects/{project_id}/metronome-schedule', {
    params: { path: { project_id: projectId } },
    body: { start_frame: startFrame, end_frame: endFrame },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Metronome schedule failed (${res.response.status})`))
  }
  return res.data
}
