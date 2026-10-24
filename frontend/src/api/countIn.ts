/** Read-only count-in plan API (M3.15). */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'

const client = createApiClient()

export type CountInPlanData = components['schemas']['CountInPlan']

export async function fetchCountInPlan(
  projectId: string,
  startFrame: number,
  playbackRate: number,
): Promise<CountInPlanData> {
  const res = await client.POST('/api/v1/projects/{project_id}/count-in-plan', {
    params: { path: { project_id: projectId } },
    body: { start_frame: startFrame, playback_rate: playbackRate },
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Count-in plan failed (${res.response.status})`))
  }
  return res.data
}
