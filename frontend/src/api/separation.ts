/**
 * Separation run API client (M2.8/M3 personal UI).
 *
 * Starts a Demucs run and polls the existing durable job endpoint. The
 * backend remains the owner of stems and result sets; the browser only
 * selects the completed set and switches the mixer mode.
 */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'

const client = createApiClient()

export type MediaJob = components['schemas']['MediaJob']

export interface SeparationRun {
  runId: string | null
  jobId: string | null
  resultSetId: string | null
  cached: boolean
}

export async function startSeparation(
  projectId: string,
  signal?: AbortSignal,
): Promise<SeparationRun> {
  const res = await client.POST('/api/v1/projects/{project_id}/runs', {
    params: { path: { project_id: projectId } },
    body: { mode: 'four_stems', seed: 0, device: 'cpu' },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Separation failed to start (${res.response.status})`))
  }
  return {
    runId: res.data.run_id ?? null,
    jobId: res.data.job_id ?? null,
    resultSetId: res.data.result_set_id ?? null,
    cached: res.data.cached ?? false,
  }
}

export async function getMediaJob(jobId: string, signal?: AbortSignal): Promise<MediaJob> {
  const res = await client.GET('/api/v1/jobs/{job_id}', {
    params: { path: { job_id: jobId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Job status failed (${res.response.status})`))
  }
  return res.data
}
