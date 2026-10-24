/**
 * Project command hook (M1.15, spec §17.5).
 *
 * Owns the authoritative project state (`revision`, `markers`,
 * `workingState`, `canUndo`, `canRedo`) — updated only from server
 * responses, never mutated optimistically.
 *
 * Write semantics:
 * - `send(op)` appends to a serialized per-tab queue (one command in
 *   flight at a time, §17.5.4); the base revision is read at send
 *   time, so queued commands always chain on the latest revision.
 * - `scheduleView(op)` coalesces view-state ops (viewport / selection /
 *   display / volume / follow) to one send per op type after ~1 s of
 *   quiet (§17.5.2).
 * - `notePosition(frame, playing)` sends `set_position` immediately on
 *   pause and at most every 5 s while playing; it bypasses the view
 *   debounce and is never recorded in history (§17.5.3/§17.4.10).
 * - `flush()` sends all armed debounced ops and awaits the queue
 *   (§17.5.5); call it on unmount / project switch.
 * - A 409 `stale_revision` triggers a project refetch to resync state,
 *   clears the queue, and surfaces a one-line notice.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  DEFAULT_WORKING_STATE,
  getProjectSnapshot,
  redoCommand,
  sendCommand,
  StaleRevisionError,
  undoCommand,
  type CommandOp,
  type CommandResult,
  type Marker,
  type PracticeState,
  type ProjectRhythmState,
  type WorkingState,
} from '../api/commands'

const VIEW_DEBOUNCE_MS = 1000
const POSITION_CADENCE_MS = 5000

export interface ProjectCommands {
  loaded: boolean
  revision: number
  markers: Marker[]
  workingState: WorkingState
  /** The project's mixer/practice state (M2.8); null before first load. */
  practiceState: PracticeState | null
  /** Sid length in frames from the snapshot (M2.11 loop bounds); null unknown. */
  durationFrames: number | null
  /** Musical-grid state from the snapshot (M3.11 ruler visibility). */
  rhythmState: ProjectRhythmState | null
  canUndo: boolean
  canRedo: boolean
  /** Commands currently in flight. */
  pendingCount: number
  /** Op types with an armed (debounced) view send. */
  armedTypes: string[]
  /** True while anything is in flight or a debounce is armed. */
  pending: boolean
  /** One-line notice after a stale-revision resync (null when idle). */
  staleNotice: string | null
  /** Apply one command immediately (marker ops, undo/redo targets). */
  send: (op: CommandOp) => Promise<CommandResult | null>
  /** Coalesce a view-state op; one send per op type after quiet time. */
  scheduleView: (op: CommandOp) => void
  /** Record the playhead position (immediate on pause, 5 s cadence). */
  notePosition: (frame: number, playing: boolean) => void
  /** Undo the newest history entry. */
  undo: () => Promise<CommandResult | null>
  /** Redo the newest undone history entry. */
  redo: () => Promise<CommandResult | null>
  /** Send all armed debounced ops and await the queue. */
  flush: () => Promise<void>
  /** Clear the stale notice. */
  clearStaleNotice: () => void
}

export function useProjectCommands(projectId: string | null): ProjectCommands {
  const [loaded, setLoaded] = useState(false)
  const [revision, setRevision] = useState(0)
  const [markers, setMarkers] = useState<Marker[]>([])
  const [workingState, setWorkingState] = useState<WorkingState>(DEFAULT_WORKING_STATE)
  const [practiceState, setPracticeState] = useState<PracticeState | null>(null)
  const [durationFrames, setDurationFrames] = useState<number | null>(null)
  const [rhythmState, setRhythmState] = useState<ProjectRhythmState | null>(null)
  const [canUndo, setCanUndo] = useState(false)
  const [canRedo, setCanRedo] = useState(false)
  const [pendingCount, setPendingCount] = useState(0)
  const [armedTypes, setArmedTypes] = useState<string[]>([])
  const [staleNotice, setStaleNotice] = useState<string | null>(null)

  const revisionRef = useRef(0)
  const chainRef = useRef<Promise<void>>(Promise.resolve())
  const inflightRef = useRef(0)
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const latestViewOpsRef = useRef(new Map<string, CommandOp>())
  const positionRef = useRef({ lastSentAt: 0 })
  const projectRef = useRef(projectId)
  projectRef.current = projectId

  const applyResult = useCallback((result: CommandResult) => {
    revisionRef.current = result.revision
    setRevision(result.revision)
    setMarkers(result.markers)
    setWorkingState(result.workingState)
    setPracticeState(result.practiceState)
    setCanUndo(result.canUndo)
    setCanRedo(result.canRedo)
  }, [])

  const setArmed = useCallback((types: Set<string>) => {
    setArmedTypes(Array.from(types))
  }, [])

  /** Refetch the project to resync after a stale-revision conflict. */
  const resync = useCallback(async () => {
    const id = projectRef.current
    if (!id) return
    // Drop armed view ops: they were computed against stale state.
    for (const timer of timersRef.current.values()) clearTimeout(timer)
    timersRef.current.clear()
    latestViewOpsRef.current.clear()
    setArmed(new Set())
    try {
      const snap = await getProjectSnapshot(id)
      revisionRef.current = snap.revision
      setRevision(snap.revision)
      setMarkers(snap.markers)
      setWorkingState(snap.workingState)
      setPracticeState(snap.practiceState)
      setDurationFrames(snap.durationFrames)
      setRhythmState(snap.rhythmState ?? null)
      setCanUndo(snap.canUndo)
      setCanRedo(snap.canRedo)
      setStaleNotice('Project changed elsewhere — reloaded.')
    } catch {
      // Best effort: keep the last known state.
    }
  }, [setArmed])

  /** Run one server operation on the serialized queue. */
  const enqueue = useCallback(
    (fn: (baseRevision: number) => Promise<CommandResult>): Promise<CommandResult | null> => {
      return new Promise((resolve) => {
        const task = chainRef.current.then(async () => {
          const id = projectRef.current
          if (!id) {
            resolve(null)
            return
          }
          inflightRef.current += 1
          setPendingCount(inflightRef.current)
          try {
            const base = revisionRef.current
            const result = await fn(base)
            // The project may have switched while in flight; only apply
            // the result to the state of the project it belongs to.
            if (projectRef.current === id) applyResult(result)
            resolve(result)
          } catch (err) {
            if (err instanceof StaleRevisionError && projectRef.current === id) {
              await resync()
            }
            resolve(null)
          } finally {
            inflightRef.current -= 1
            setPendingCount(inflightRef.current)
          }
        })
        chainRef.current = task.then(
          () => undefined,
          () => undefined,
        )
      })
    },
    [applyResult, resync],
  )

  const send = useCallback(
    (op: CommandOp) => enqueue((base) => sendCommand(projectRef.current!, base, op)),
    [enqueue],
  )

  const undo = useCallback(
    () => enqueue((base) => undoCommand(projectRef.current!, base)),
    [enqueue],
  )

  const redo = useCallback(
    () => enqueue((base) => redoCommand(projectRef.current!, base)),
    [enqueue],
  )

  const scheduleView = useCallback(
    (op: CommandOp) => {
      latestViewOpsRef.current.set(op.type, op)
      setArmed(new Set(latestViewOpsRef.current.keys()))
      const timers = timersRef.current
      const existing = timers.get(op.type)
      if (existing) clearTimeout(existing)
      timers.set(
        op.type,
        setTimeout(() => {
          timers.delete(op.type)
          const latest = latestViewOpsRef.current.get(op.type)
          latestViewOpsRef.current.delete(op.type)
          setArmed(new Set(latestViewOpsRef.current.keys()))
          if (latest) send(latest)
        }, VIEW_DEBOUNCE_MS),
      )
    },
    [send, setArmed],
  )

  const notePosition = useCallback(
    (frame: number, playing: boolean) => {
      const now = Date.now()
      if (!playing || now - positionRef.current.lastSentAt >= POSITION_CADENCE_MS) {
        positionRef.current.lastSentAt = now
        send({ type: 'set_position', position_frames: frame })
      }
    },
    [send],
  )

  const flush = useCallback(async () => {
    for (const [type, timer] of timersRef.current) {
      clearTimeout(timer)
      const op = latestViewOpsRef.current.get(type)
      latestViewOpsRef.current.delete(type)
      if (op) send(op)
    }
    timersRef.current.clear()
    setArmed(new Set())
    await chainRef.current
  }, [send, setArmed])

  const clearStaleNotice = useCallback(() => setStaleNotice(null), [])

  // Initial load + per-project reset.
  const prevIdRef = useRef<string | null>(null)
  useEffect(() => {
    const prevId = prevIdRef.current
    prevIdRef.current = projectId
    // Flush armed view ops for the previous project (best effort, fire
    // and forget): the serialized queue is now owned by the new project.
    if (prevId && prevId !== projectId) {
      for (const [type, timer] of timersRef.current) {
        clearTimeout(timer)
        const op = latestViewOpsRef.current.get(type)
        latestViewOpsRef.current.delete(type)
        if (op) void sendCommand(prevId, revisionRef.current, op).catch(() => undefined)
      }
      chainRef.current = Promise.resolve()
    }
    setLoaded(false)
    setStaleNotice(null)
    for (const timer of timersRef.current.values()) clearTimeout(timer)
    timersRef.current.clear()
    latestViewOpsRef.current.clear()
    setArmed(new Set())
    if (!projectId) {
      revisionRef.current = 0
      setRevision(0)
      setMarkers([])
      setWorkingState(DEFAULT_WORKING_STATE)
      setPracticeState(null)
      setDurationFrames(null)
      setCanUndo(false)
      setCanRedo(false)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const snap = await getProjectSnapshot(projectId)
        if (cancelled) return
        revisionRef.current = snap.revision
        setRevision(snap.revision)
        setMarkers(snap.markers)
        setWorkingState(snap.workingState)
        setPracticeState(snap.practiceState)
        setDurationFrames(snap.durationFrames)
        setRhythmState(snap.rhythmState ?? null)
        setCanUndo(snap.canUndo)
        setCanRedo(snap.canRedo)
        setLoaded(true)
      } catch {
        if (!cancelled) setLoaded(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [projectId, setArmed])

  // Clear any armed timers on unmount (flush() is the caller's choice).
  useEffect(() => {
    const timers = timersRef.current
    return () => {
      for (const timer of timers.values()) clearTimeout(timer)
      timers.clear()
    }
  }, [])

  // Best-effort send of armed view ops when the page is closed (§17.5.6).
  useEffect(() => {
    const onPageHide = () => {
      const id = projectRef.current
      if (!id) return
      for (const op of latestViewOpsRef.current.values()) {
        const body = {
          command_id: crypto.randomUUID(),
          idempotency_key: crypto.randomUUID(),
          base_revision: revisionRef.current,
          op,
        }
        try {
          navigator.sendBeacon(
            `/api/v1/projects/${id}/commands`,
            new Blob([JSON.stringify(body)], { type: 'application/json' }),
          )
        } catch {
          // best effort
        }
      }
    }
    window.addEventListener('pagehide', onPageHide)
    return () => window.removeEventListener('pagehide', onPageHide)
  }, [])

  return {
    loaded,
    revision,
    markers,
    workingState,
    practiceState,
    durationFrames,
    rhythmState,
    canUndo,
    canRedo,
    pendingCount,
    armedTypes,
    pending: pendingCount > 0 || armedTypes.length > 0,
    staleNotice,
    send,
    scheduleView,
    notePosition,
    undo,
    redo,
    flush,
    clearStaleNotice,
  }
}
