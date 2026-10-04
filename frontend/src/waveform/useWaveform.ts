/**
 * Waveform data hook (M1.10 §12.5, §12.8; M1.11 §13).
 *
 * Drives the editor's state machine — `empty` / `decoding` / `pending` /
 * `missing` / `ready` — and, once ready, fetches and decodes the data for
 * the viewport the component passes in: peak tiles for the chosen pyramid
 * level, or a bounded PCM window when the zoom is finer than the coarsest
 * bucket. It also fetches the coarsest level's full tile set once per
 * manifest for the overview strip, which always shows the whole source.
 * The manifest is polled every 500 ms (visible) / 2 s (hidden) while a
 * waveform build is in flight. Each effect owns an AbortController whose
 * cleanup cancels in-flight fetches when inputs change (§12.5.3).
 *
 * Decode runs through the `worker.ts` wrappers (decode worker with a
 * main-thread fallback, so jsdom tests are unaffected); results are
 * dropped when the owning effect is stale.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createWaveformJob,
  getAssetMetadata,
  getAssetPcm,
  getPeakTile,
  getPeaksManifest,
  listProjectJobs,
  TileNotReadyError,
  type WaveformManifest,
} from '../api/waveform'
import { latestCompletedImportId } from '../api/playback'
import {
  adjacentTileRange,
  chooseLevel,
  pcmFrameRange,
  TILE_BUCKETS,
  usePcm,
  useSampleLevel,
} from './levels'
import { type PcmPixels, type PeakTile } from './decode'
import { decodePcmPixels, decodePcmSamples, decodeTile } from './worker'
import type { Viewport } from './viewport'
import { TileLru, tileKey } from './tileCache'

export type WaveformState = 'empty' | 'decoding' | 'pending' | 'missing' | 'ready'

export interface WaveformLevelData {
  level: number
  bucketFrameCount: number
  tiles: Map<number, PeakTile>
}

export type PcmData =
  | { kind: 'pixels'; startFrame: number; data: PcmPixels }
  | { kind: 'samples'; startFrame: number; channels: Float32Array[] }

export interface WaveformData {
  state: WaveformState
  manifest: WaveformManifest | null
  levels: WaveformLevelData[]
  pcm: PcmData | null
  /** Coarsest-level data covering the whole source (overview strip). */
  overview: WaveformLevelData | null
  error: string | null
  /** Post a `waveform` build job (the `missing`-state rebuild button). */
  rebuild: () => void
}

const PCM_MAX_BYTES = 8 * 1024 * 1024

function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** Fetch a bounded PCM window, chunked to stay under the 8 MiB cap. */
async function fetchPcmWindow(
  assetId: string,
  channelCount: number,
  first: number,
  last: number,
  framesPerCssPixel: number,
  signal: AbortSignal,
): Promise<PcmData> {
  const maxFrames = Math.floor(PCM_MAX_BYTES / (4 * channelCount))
  const chunks: ArrayBuffer[] = []
  let pos = first
  while (pos < last) {
    const count = Math.min(maxFrames, last - pos)
    const window = await getAssetPcm(assetId, pos, count, signal)
    chunks.push(window.bytes)
    pos += window.frameCount
    if (window.eof) break
  }
  const totalBytes = chunks.reduce((sum, c) => sum + c.byteLength, 0)
  const merged = new ArrayBuffer(totalBytes)
  const out = new Uint8Array(merged)
  let offset = 0
  for (const c of chunks) {
    out.set(new Uint8Array(c), offset)
    offset += c.byteLength
  }
  if (useSampleLevel(framesPerCssPixel)) {
    const channels = await decodePcmSamples(merged, channelCount)
    return { kind: 'samples', startFrame: first, channels }
  }
  const data = await decodePcmPixels(merged, channelCount, first, framesPerCssPixel)
  return { kind: 'pixels', startFrame: first, data }
}

export function useWaveform(
  projectId: string | null,
  assetId: string | null,
  viewport: Viewport | null,
): WaveformData {
  const [state, setState] = useState<WaveformState>('empty')
  const [manifest, setManifest] = useState<WaveformManifest | null>(null)
  const [levels, setLevels] = useState<WaveformLevelData[]>([])
  const [pcmState, setPcmState] = useState<PcmData | null>(null)
  const [overview, setOverview] = useState<WaveformLevelData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const lruRef = useRef<TileLru>(new TileLru())

  // Main load: metadata -> manifest -> state. Runs on asset/project change.
  useEffect(() => {
    lruRef.current.clear()
    setManifest(null)
    setLevels([])
    setPcmState(null)
    setOverview(null)
    setError(null)
    if (!assetId) {
      setState('empty')
      return
    }
    const aid = assetId
    const controller = new AbortController()
    let cancelled = false
    const stale = () => cancelled || controller.signal.aborted
    async function run() {
      try {
        setState('decoding')
        const metadata = await getAssetMetadata(aid, controller.signal)
        if (stale()) return
        if (!metadata.waveform) {
          const jobs = projectId ? await listProjectJobs(projectId, controller.signal) : []
          if (stale()) return
          const live = jobs.some(
            (j) => j.jobType === 'waveform' && (j.state === 'queued' || j.state === 'running'),
          )
          setState(live ? 'pending' : 'missing')
          return
        }
        const m = await getPeaksManifest(aid, controller.signal)
        if (stale()) return
        if (m === null) {
          setState('missing')
          return
        }
        setManifest(m)
        setState(m.final ? 'ready' : 'pending')
      } catch (e) {
        if (stale() || isAbort(e)) return
        setError(messageOf(e))
        setState('missing')
      }
    }
    run()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [assetId, projectId])

  // Poll the manifest while a waveform build is in flight (§12.8).
  useEffect(() => {
    if (state !== 'pending' || !assetId) return
    const aid = assetId
    const controller = new AbortController()
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const interval = () => (document.visibilityState === 'visible' ? 500 : 2000)

    function schedule() {
      if (cancelled) return
      if (timer) clearTimeout(timer)
      timer = setTimeout(tick, interval())
    }
    async function tick() {
      try {
        const m = await getPeaksManifest(aid, controller.signal)
        if (cancelled) return
        if (m && m.final) {
          setManifest(m)
          setState('ready')
          return
        }
        if (m) setManifest(m)
      } catch (e) {
        if (cancelled || isAbort(e)) return
        // Transient: keep polling.
      }
      schedule()
    }
    schedule()
    document.addEventListener('visibilitychange', schedule)
    return () => {
      cancelled = true
      controller.abort()
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', schedule)
    }
  }, [state, assetId])

  // Data fetch: tiles or PCM for the ready, passed-in viewport (§12.5,
  // M1.11 §13.1). Re-runs on every zoom/pan because the viewport identity
  // changes; the AbortController cancels the superseded request.
  useEffect(() => {
    if (state !== 'ready' || !manifest || !assetId) {
      if (state !== 'ready') {
        setLevels([])
        setPcmState(null)
      }
      return
    }
    if (!viewport) return
    const man = manifest
    const aid = assetId
    const vp = viewport
    const controller = new AbortController()
    let cancelled = false
    const stale = () => cancelled || controller.signal.aborted
    async function run() {
      try {
        const frameCount = man.frame_count
        const fpp = vp.framesPerCssPixel
        if (usePcm(fpp)) {
          const [first, last] = pcmFrameRange(vp, frameCount)
          const data = await fetchPcmWindow(
            aid,
            man.channel_count,
            first,
            last,
            fpp,
            controller.signal,
          )
          if (stale()) return
          setPcmState(data)
          setLevels([])
        } else {
          const level = chooseLevel(man, fpp)
          const summary = man.levels[level]
          const [t0, t1] = adjacentTileRange(summary, vp)
          const tiles = new Map<number, PeakTile>()
          for (let t = t0; t <= t1; t++) {
            const key = tileKey(man.source_hash, level, t)
            let bytes = lruRef.current.get(key)
            if (!bytes) {
              const tile = await getPeakTile(aid, level, t, controller.signal)
              if (stale()) return
              bytes = tile.bytes
              lruRef.current.set(key, bytes)
            }
            const bucketCount =
              t === summary.tile_count - 1 ? summary.final_tile_buckets : TILE_BUCKETS
            tiles.set(t, await decodeTile(bytes, man.channel_count, bucketCount))
            if (stale()) return
          }
          if (stale()) return
          setPcmState(null)
          setLevels([{ level, bucketFrameCount: summary.bucket_frame_count, tiles }])
        }
      } catch (e) {
        if (stale() || isAbort(e)) return
        if (e instanceof TileNotReadyError) return
        setError(messageOf(e))
      }
    }
    run()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [state, manifest, assetId, viewport])

  // Overview: the coarsest level's full tile set, once per manifest
  // (M1.11 §13.2.3). Small (a few tiles) and LRU-cached.
  useEffect(() => {
    if (state !== 'ready' || !manifest || !assetId) {
      if (state !== 'ready') setOverview(null)
      return
    }
    const man = manifest
    const aid = assetId
    const controller = new AbortController()
    let cancelled = false
    const stale = () => cancelled || controller.signal.aborted
    async function run() {
      try {
        const level = man.levels.length - 1
        const summary = man.levels[level]
        const tiles = new Map<number, PeakTile>()
        for (let t = 0; t < summary.tile_count; t++) {
          const key = tileKey(man.source_hash, level, t)
          let bytes = lruRef.current.get(key)
          if (!bytes) {
            const tile = await getPeakTile(aid, level, t, controller.signal)
            if (stale()) return
            bytes = tile.bytes
            lruRef.current.set(key, bytes)
          }
          const bucketCount =
            t === summary.tile_count - 1 ? summary.final_tile_buckets : TILE_BUCKETS
          tiles.set(t, await decodeTile(bytes, man.channel_count, bucketCount))
          if (stale()) return
        }
        if (stale()) return
        setOverview({ level, bucketFrameCount: summary.bucket_frame_count, tiles })
      } catch (e) {
        if (stale() || isAbort(e)) return
        if (e instanceof TileNotReadyError) return
        // A failed overview is not fatal for the main view.
      }
    }
    run()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [state, manifest, assetId])

  const rebuild = useCallback(() => {
    if (!projectId) return
    ;(async () => {
      try {
        const importId = await latestCompletedImportId(projectId)
        if (!importId) {
          setError('No completed import to build a waveform from')
          return
        }
        setState('pending')
        await createWaveformJob(projectId, importId)
      } catch (e) {
        if (isAbort(e)) return
        setError(messageOf(e))
        setState('missing')
      }
    })()
  }, [projectId])

  return { state, manifest, levels, pcm: pcmState, overview, error, rebuild }
}
