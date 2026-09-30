/**
 * Token bootstrap (M0.8).
 *
 * Reads the session token from the URL fragment on first load,
 * stores it in sessionStorage, and immediately removes the fragment
 * with history.replaceState. Subsequent reloads reuse sessionStorage.
 */

const TOKEN_KEY = 'basseparate.sessionToken'

export function bootstrapToken(): string | null {
  const hash = window.location.hash
  if (hash.startsWith('#token=')) {
    const token = decodeURIComponent(hash.slice('#token='.length))
    if (token) {
      sessionStorage.setItem(TOKEN_KEY, token)
    }
    // Remove the fragment immediately.
    history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return sessionStorage.getItem(TOKEN_KEY)
}

export function getSessionToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function clearSessionToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}
