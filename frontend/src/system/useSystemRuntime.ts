/**
 * Local runtime-diagnostics poll (M2.12 §14.4).
 *
 * While a project is open, polls `GET /api/v1/system` every 2 s and
 * exposes the optional `runtime` block (API/worker RSS + CPU, GPU
 * memory, the current media job, the last separation run) for the
 * playback panel's diagnostics line.
 *
 * Local only: the endpoint reads procfs/`nvidia-smi` on this machine
 * and is never telemetry. Polling is best-effort — a failed request
 * keeps the previous values, and the interval is cleared whenever the
 * hook is disabled or unmounted.
 */

import { useEffect, useState } from 'react'
import { createApiClient } from '../api/client'
import type { components } from '../api/schema'

export type RuntimeStatus = components['schemas']['RuntimeStatusResponse']

/** Poll cadence (M2.12 §14.4: every 2 s while a project is open). */
export const RUNTIME_POLL_MS = 2000

const client = createApiClient()

export function useSystemRuntime(enabled: boolean): RuntimeStatus | null {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null)

  useEffect(() => {
    if (!enabled) return
    let disposed = false
    const poll = async () => {
      try {
        const res = await client.GET('/api/v1/system')
        if (!disposed && res.response.ok && res.data?.runtime) {
          setRuntime(res.data.runtime)
        }
      } catch {
        // Best-effort diagnostics: keep the last good values.
      }
    }
    void poll()
    const handle = window.setInterval(() => void poll(), RUNTIME_POLL_MS)
    return () => {
      disposed = true
      window.clearInterval(handle)
    }
  }, [enabled])

  return enabled ? runtime : null
}
