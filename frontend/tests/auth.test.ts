import { beforeEach, describe, expect, it } from 'vitest'
import { bootstrapToken, clearSessionToken, getSessionToken } from '../src/auth'

describe('auth token bootstrap', () => {
  beforeEach(() => {
    clearSessionToken()
    window.history.replaceState(null, '', '/')
  })

  it('reads token from URL fragment and stores it in sessionStorage', () => {
    window.history.replaceState(null, '', '/#token=secret123')
    const token = bootstrapToken()
    expect(token).toBe('secret123')
    expect(getSessionToken()).toBe('secret123')
  })

  it('removes the token from the URL after bootstrap', () => {
    window.history.replaceState(null, '', '/#token=secret123')
    bootstrapToken()
    expect(window.location.hash).toBe('')
  })

  it('decodes URI-encoded tokens', () => {
    window.history.replaceState(null, '', `/#token=${encodeURIComponent('a b/c+d=e')}`)
    expect(bootstrapToken()).toBe('a b/c+d=e')
  })

  it('returns null when no fragment and no stored token', () => {
    expect(bootstrapToken()).toBeNull()
  })

  it('reuses stored token on reload without fragment', () => {
    window.history.replaceState(null, '', '/#token=first')
    bootstrapToken()
    expect(bootstrapToken()).toBe('first')
  })

  it('does not overwrite an existing stored token with an empty fragment', () => {
    sessionStorage.setItem('basseparate.sessionToken', 'existing')
    window.history.replaceState(null, '', '/#token=')
    expect(bootstrapToken()).toBe('existing')
  })
})
