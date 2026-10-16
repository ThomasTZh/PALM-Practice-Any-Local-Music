/**
 * Result set API module (M2.8, spec §10.1.6, §10.4.5–6).
 *
 * Fetches the list of a project's separation result sets (for the
 * playback-mode selector) and the detail of one — the set, its stems, and
 * the completing run's provenance — for the track stack. The routes are
 * read-only; the mixer never writes through them.
 */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'

const client = createApiClient()

export interface ResultSetStem {
  id: string
  role: string
  displayName: string
  audioAssetId: string
  sampleRate: number
  channelCount: number
  frameCount: number
}

export interface ResultSetDetail {
  id: string
  createdAt: string
  validationStatus: string
  cacheKey: string | null
  stems: ResultSetStem[]
  engineVersion: string
  adapterVersion: string
  modelManifestId: string
  modelManifestHash: string
}

/** One result set in the project's list (spec §10.4.5–6 selector). */
export interface ResultSetSummary {
  id: string
  createdAt: string
  validationStatus: string
  availableStemRoles: string[]
}

/**
 * Fetch the project's result sets, oldest first (spec §10.4.5–6). The
 * playback-mode selector lists the `valid` ones for choice.
 */
export async function fetchResultSets(
  projectId: string,
  signal?: AbortSignal,
): Promise<ResultSetSummary[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/result-sets', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Result set list failed (${res.response.status})`))
  }
  return (res.data ?? []).map((s) => ({
    id: s.id,
    createdAt: s.created_at,
    validationStatus: s.validation_status,
    availableStemRoles: (s.available_stem_roles ?? []).map((r) => r as string),
  }))
}

/** The result set is missing, or it belongs to another project (404). */
export class ResultSetNotFoundError extends Error {
  constructor(resultSetId: string) {
    super(`Separation result set not found: ${resultSetId}`)
    this.name = 'ResultSetNotFoundError'
  }
}

/**
 * Fetch the result set detail for the track stack (spec §10.1.6).
 * Throws `ResultSetNotFoundError` on 404 `RESULT_SET_NOT_FOUND`.
 */
export async function fetchResultSetDetail(
  projectId: string,
  resultSetId: string,
  signal?: AbortSignal,
): Promise<ResultSetDetail> {
  const res = await client.GET('/api/v1/projects/{project_id}/result-sets/{result_set_id}', {
    params: { path: { project_id: projectId, result_set_id: resultSetId } },
    signal,
  })
  if (res.response.status === 404) {
    throw new ResultSetNotFoundError(resultSetId)
  }
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Result set load failed (${res.response.status})`))
  }
  const data = res.data
  return {
    id: data.id,
    createdAt: data.created_at,
    validationStatus: data.validation_status,
    cacheKey: data.cache_key ?? null,
    stems: (data.stems ?? []).map((stem) => ({
      id: stem.id,
      role: stem.role,
      displayName: stem.display_name,
      audioAssetId: stem.audio_asset_id,
      sampleRate: stem.sample_rate,
      channelCount: stem.channel_count,
      frameCount: stem.frame_count,
    })),
    engineVersion: data.engine_version,
    adapterVersion: data.adapter_version,
    modelManifestId: data.model_manifest_id,
    modelManifestHash: data.model_manifest_hash,
  }
}
