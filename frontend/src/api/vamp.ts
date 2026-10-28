/**
 * Local Vamp analysis API (personal build).
 *
 * Runs the configured QM bar/beat plugin through the local native host (or
 * the Piper fallback), caches the features, and activates a new grid branch.
 */

import { createApiClient, errorMessage } from './client'

const client = createApiClient()

export interface VampAnalysisResult {
  branchId: string
  beats: number
  bars: number
  cached: boolean
  pluginKey: string
  pluginVersion: string
  bpb: number
}

export async function analyzeWithVamp(
  projectId: string,
  bpb: number,
  signal?: AbortSignal,
): Promise<VampAnalysisResult> {
  const res = await client.POST('/api/v1/projects/{project_id}/vamp-analysis', {
    params: { path: { project_id: projectId } },
    body: { bpb },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Vamp analysis failed (${res.response.status})`))
  }
  return {
    branchId: res.data.branch_id,
    beats: res.data.beats,
    bars: res.data.bars,
    cached: res.data.cached,
    pluginKey: res.data.plugin_key,
    pluginVersion: res.data.plugin_version,
    bpb: res.data.bpb,
  }
}
