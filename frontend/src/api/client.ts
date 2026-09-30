/**
 * API client wrapper (M0.8).
 *
 * Uses openapi-fetch with the generated schema types.
 * Adds the Authorization header from sessionStorage.
 * Parses the standard error envelope centrally.
 */

import createClient from 'openapi-fetch'
import type { paths } from './schema'
import { getSessionToken } from '../auth'

export class ApiError extends Error {
  readonly code: string
  readonly statusCode: number

  constructor(code: string, message: string, statusCode: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.statusCode = statusCode
  }
}

/** Extract a human-readable message from the standard error envelope. */
export function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object') {
    const e = error as { error?: { message?: string }; detail?: string; message?: string }
    if (e.error?.message) return e.error.message
    if (typeof e.detail === 'string') return e.detail
    if (e.message) return e.message
  }
  return fallback
}

export function createApiClient(baseUrl = '') {
  const client = createClient<paths>({ baseUrl })

  client.use({
    onRequest({ request }) {
      const token = getSessionToken()
      if (token) {
        request.headers.set('Authorization', `Bearer ${token}`)
      }
    },
  })

  return client
}

export type { paths }
