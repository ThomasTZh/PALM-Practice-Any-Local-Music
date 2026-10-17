/**
 * M2.12 §14.4: the runtime-diagnostics poll lifecycle — immediate first
 * poll, 2 s cadence while enabled, no polling (and no values) while
 * disabled, cleanup on unmount, and last-good retention on failure.
 */

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }))

vi.mock('../src/api/client', () => ({
  createApiClient: () => ({ GET: mockGet }),
}))

import { RUNTIME_POLL_MS, useSystemRuntime } from '../src/system/useSystemRuntime'

function systemOk(runtime: unknown) {
  return {
    response: { ok: true, status: 200 },
    data: { app_version: '0.1.0-dev', api_version: 1, ready: true, runtime },
  }
}

describe('useSystemRuntime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockGet.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls immediately, then every 2 s while enabled', async () => {
    mockGet.mockResolvedValue(systemOk({ api: { rss_bytes: 1, cpu_seconds: 0 } }))
    const { result } = renderHook(() => useSystemRuntime(true))
    await act(async () => {})
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(result.current).toEqual({ api: { rss_bytes: 1, cpu_seconds: 0 } })

    mockGet.mockResolvedValue(systemOk({ api: { rss_bytes: 2, cpu_seconds: 0 } }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUNTIME_POLL_MS)
    })
    expect(mockGet).toHaveBeenCalledTimes(2)
    expect(result.current).toEqual({ api: { rss_bytes: 2, cpu_seconds: 0 } })
  })

  it('clears the interval on unmount', async () => {
    mockGet.mockResolvedValue(systemOk({ api: { rss_bytes: 1, cpu_seconds: 0 } }))
    const { unmount } = renderHook(() => useSystemRuntime(true))
    await act(async () => {})
    expect(mockGet).toHaveBeenCalledTimes(1)
    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUNTIME_POLL_MS * 5)
    })
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('does not poll while disabled and hides retained values', async () => {
    mockGet.mockResolvedValue(systemOk({ api: { rss_bytes: 1, cpu_seconds: 0 } }))
    const { result, rerender } = renderHook(({ enabled }) => useSystemRuntime(enabled), {
      initialProps: { enabled: false },
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUNTIME_POLL_MS * 3)
    })
    expect(mockGet).not.toHaveBeenCalled()
    expect(result.current).toBeNull()

    rerender({ enabled: true })
    await act(async () => {})
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(result.current).not.toBeNull()

    rerender({ enabled: false })
    expect(result.current).toBeNull()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUNTIME_POLL_MS * 3)
    })
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('keeps the last good values when a poll fails or omits runtime', async () => {
    mockGet.mockResolvedValueOnce(systemOk({ api: { rss_bytes: 1, cpu_seconds: 0 } }))
    mockGet.mockRejectedValueOnce(new Error('network'))
    mockGet.mockResolvedValueOnce(systemOk(null))
    const { result } = renderHook(() => useSystemRuntime(true))
    await act(async () => {})
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUNTIME_POLL_MS * 2)
    })
    expect(mockGet).toHaveBeenCalledTimes(3)
    expect(result.current).toEqual({ api: { rss_bytes: 1, cpu_seconds: 0 } })
  })
})
