/**
 * Waveform data hook (M1.10, spec §12.5, §12.8).
 *
 * Drives the editor's state machine — `empty` / `decoding` / `pending` /
 * `missing` / `ready` — and, once ready, fetches and decodes the data for
 * the current (fit-to-song) viewport: peak tiles for the chosen pyramid
 * level, or a bounded PCM window when the zoom is finer than the coarsest
 * bucket. The manifest is polled every 500 ms (visible) / 2 s (hidden)
 * while a waveform build is in flight. Each effect owns an AbortController
 * whose cleanup cancels in-flight fetches when inputs change (§12.5.3).
 *
 * M1.10 decodes synchronously via the pure `decode.ts` functions; the
 * `worker.ts` wrapper is the M1.11 optimization for continuous zooming.
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
import {
  aggregatePcmToPixels,
  parsePeakTile,
  pcmSamples,
  type PcmPixels,
  type PeakTile,
} from './decode'
import { fitViewport, type Viewport } from './viewport'
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
  /** The fit-to-song viewport, once the duration is known. */
  viewport: Viewport | null
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
    return { kind: 'samples', startFrame: first, channels: pcmSamples(merged, channelCount) }
  }
  return {
    kind: 'pixels',
    startFrame: first,
    data: aggregatePcmToPixels(merged, channelCount, first, framesPerCssPixel),
  }
}

export function useWaveform(
  projectId: string | null,
  assetId: string | null,
  widthCssPx: number,
): WaveformData {
  const [state, setState] = useState<WaveformState>('empty')
  const [manifest, setManifest] = useState<WaveformManifest | null>(null)
  const [levels, setLevels] = useState<WaveformLevelData[]>([])
  const [pcm, setPcm] = useState<PcmData | null>(null)
  const [viewport, setViewport] = useState<Viewport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const lruRef = useRef<TileLru>(new TileLru())

  // Main load: metadata -> manifest -> state. Runs on asset/project change.
  useEffect(() => {
    lruRef.current.clear()
    setManifest(null)
    setLevels([])
    setPcm(null)
    setViewport(null)
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

  // Data fetch: tiles or PCM for the ready, measured viewport (§12.5).
  useEffect(() => {
    if (state !== 'ready' || !manifest || !assetId) {
      if (state !== 'ready') {
        setLevels([])
        setPcm(null)
      }
      return
    }
    if (!(widthCssPx > 0)) return
    const man = manifest
    const aid = assetId
    const controller = new AbortController()
    let cancelled = false
    const stale = () => cancelled || controller.signal.aborted
    async function run() {
      try {
        const frameCount = man.frame_count
        const vp = fitViewport(frameCount, widthCssPx)
        setViewport(vp)
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
          setPcm(data)
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
            tiles.set(t, parsePeakTile(bytes, man.channel_count, bucketCount))
          }
          if (stale()) return
          setPcm(null)
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
  }, [state, manifest, assetId, widthCssPx])

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

  return { state, manifest, levels, pcm, viewport, error, rebuild }
}
