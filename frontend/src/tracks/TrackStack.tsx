/**
 * The aligned track stack (M2.8, spec §10.1).
 *
 * Renders the active stem group as lanes below the original reference
 * track (the waveform editor). One shared view (the editor's zoom/pan,
 * read through `viewSource`) drives every lane (§10.1.4); each lane
 * keeps its own height and amplitude (§10.1.5). The mode bar holds the
 * playback-mode selector (with the result-set choice) and the
 * monitoring panel. The original track is a reference: it has no
 * per-track mixer (the groups are mutually exclusive, §10.4.5).
 */
import { useEffect, useMemo, useState } from 'react'
import type { PracticeState } from '../api/commands'
import type { components } from '../api/schema'
import { fetchResultSets, type ResultSetDetail, type ResultSetSummary } from '../api/result-sets'
import { effectiveTracks } from '../projects/trackSettings'
import type { MixPeaks } from '../playback/transport'
import type { PlayheadSource, ViewSource } from '../waveform/WaveformEditor'
import { MixerStrip, type TrackSettingsPatch } from './MixerStrip'
import { MonitoringPanel } from './MonitoringPanel'
import { ModeSelector, type PlaybackMode } from './ModeSelector'
import { TrackLane } from './TrackLane'

export type { PlaybackMode }

/** Canonical stem order per mode (spec §10.4). */
export const BASS_PAIR_ROLES = ['bass', 'others']
export const FOUR_STEM_ROLES = ['vocals', 'drums', 'bass', 'other']

/** Base lane height in CSS px (× `display_height`). */
export const LANE_BASE_HEIGHT = 48

export interface TrackStackProps {
  projectId: string
  /** The editor's shared view; null before the editor is ready. */
  viewSource: ViewSource | null
  /** Audible playhead for the lane playhead lines. */
  playheadSource?: PlayheadSource
  /** The project's mixer/practice state (null before first load). */
  practiceState: PracticeState | null
  /** The active set's detail (stems + provenance, spec §10.1.6). */
  detail: ResultSetDetail | null
  /** Per-quantum peaks (index = mix source order), from the transport. */
  peaks: MixPeaks | null
  /** Patch one stem's settings (sends `set_track_settings`). */
  onTrackSettings: (role: string, patch: TrackSettingsPatch) => void
  /** Set the master monitoring gain (linear; sends `set_master_gain`). */
  onMasterGain: (linear: number) => void
  /** Toggle the monitoring limiter (sends `set_monitoring_limiter`). */
  onLimiter: (enabled: boolean) => void
  /** Change the playback mode (sends `set_playback_mode`). */
  onMode: (mode: PlaybackMode) => void
  /** Select a result set (sends `set_active_result_set`). */
  onSelectSet: (resultSetId: string) => void
}

export function TrackStack({
  projectId,
  viewSource,
  playheadSource,
  practiceState,
  detail,
  peaks,
  onTrackSettings,
  onMasterGain,
  onLimiter,
  onMode,
  onSelectSet,
}: TrackStackProps) {
  const mode: PlaybackMode = practiceState?.playback_mode ?? 'original'
  const activeSetId = practiceState?.active_result_set_id ?? null

  // The project's result sets (for the mode bar's set choice).
  const [sets, setSets] = useState<ResultSetSummary[] | null>(null)
  const [modeNotice, setModeNotice] = useState<string | null>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    fetchResultSets(projectId, ctrl.signal)
      .then(setSets)
      .catch(() => {})
    return () => ctrl.abort()
  }, [projectId])

  // The active group's stems, in canonical order (spec §10.4).
  const stems = useMemo(() => {
    if (mode === 'original' || !detail) return []
    const order = mode === 'bass_pair' ? BASS_PAIR_ROLES : FOUR_STEM_ROLES
    const byRole = new Map(detail.stems.map((s) => [s.role, s]))
    return order.filter((role) => byRole.has(role)).map((role) => byRole.get(role)!)
  }, [mode, detail])

  // The no-set prompt clears when a set is active or the mode leaves stems.
  useEffect(() => {
    if (activeSetId || mode === 'original') setModeNotice(null)
  }, [activeSetId, mode])

  const handleMode = (next: PlaybackMode) => {
    if (next === 'original') {
      onMode('original')
      return
    }
    if (!activeSetId) {
      setModeNotice('Select a separation result set first.')
      return
    }
    onMode(next)
  }

  const provenance = detail
    ? `${detail.engineVersion} · model ${detail.modelManifestId.slice(0, 8)}`
    : null

  return (
    <section className="track-stack" aria-label="Tracks">
      <div className="track-mode-bar">
        <ModeSelector
          mode={mode}
          sets={sets}
          activeSetId={activeSetId}
          onMode={handleMode}
          onSelectSet={onSelectSet}
          notice={modeNotice}
        />
        <MonitoringPanel
          masterPeak={peaks?.master ?? null}
          masterGain={practiceState?.master_gain ?? 1}
          limiterEnabled={practiceState?.monitoring_limiter ?? true}
          onMasterGain={onMasterGain}
          onLimiter={onLimiter}
        />
      </div>
      {stems.map((stem, i) => {
        const { settings } = effectiveTracks(practiceState, [stem.role])[0]
        return (
          <div className="track-row" key={stem.role}>
            <div className="track-label">
              <span className="track-name" style={{ color: settings.color }}>
                {stem.displayName}
              </span>
            </div>
            <TrackLane
              projectId={projectId}
              assetId={stem.assetId}
              viewSource={viewSource}
              playheadSource={playheadSource}
              height={LANE_BASE_HEIGHT * settings.display_height}
              amplitudeScale={1}
              color={settings.color}
              label={stem.displayName}
              provenance={provenance}
              hidden={!settings.visible}
            />
            <MixerStrip
              label={stem.displayName}
              settings={settings}
              peak={peaks?.tracks[i] ?? null}
              onPatch={(patch) => onTrackSettings(stem.role, patch)}
            />
          </div>
        )
      })}
    </section>
  )
}
