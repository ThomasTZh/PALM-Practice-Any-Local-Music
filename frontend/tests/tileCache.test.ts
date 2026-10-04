import { describe, expect, it } from 'vitest'
import { tileKey, TileLru } from '../src/waveform/tileCache'

function bufferOf(size: number): ArrayBuffer {
  return new ArrayBuffer(size)
}

describe('tileKey', () => {
  it('joins hash, level, and tile index', () => {
    expect(tileKey('abc', 1, 7)).toBe('abc/1/7')
  })
})

describe('TileLru', () => {
  it('misses on an empty cache', () => {
    const cache = new TileLru()
    expect(cache.get('k')).toBeUndefined()
    expect(cache.has('k')).toBe(false)
    expect(cache.byteSize).toBe(0)
    expect(cache.count).toBe(0)
  })

  it('stores and returns tiles', () => {
    const cache = new TileLru()
    const tile = bufferOf(16)
    cache.set('k', tile)
    expect(cache.get('k')).toBe(tile)
    expect(cache.has('k')).toBe(true)
    expect(cache.byteSize).toBe(16)
    expect(cache.count).toBe(1)
  })

  it('evicts least-recently-used tiles first', () => {
    const cache = new TileLru(16) // room for two 8-byte tiles
    cache.set('a', bufferOf(8))
    cache.set('b', bufferOf(8))
    cache.set('c', bufferOf(8)) // evicts 'a'
    expect(cache.has('a')).toBe(false)
    expect(cache.has('b')).toBe(true)
    expect(cache.has('c')).toBe(true)
    expect(cache.byteSize).toBe(16)
  })

  it('a get refreshes recency', () => {
    const cache = new TileLru(16)
    const a = bufferOf(8)
    const b = bufferOf(8)
    cache.set('a', a)
    cache.set('b', b)
    expect(cache.get('a')).toBe(a) // 'a' is now most recent
    cache.set('c', bufferOf(8)) // evicts 'b', not 'a'
    expect(cache.has('a')).toBe(true)
    expect(cache.has('b')).toBe(false)
    expect(cache.has('c')).toBe(true)
  })

  it('re-setting a key does not double-count its bytes', () => {
    const cache = new TileLru(16)
    cache.set('a', bufferOf(8))
    cache.set('a', bufferOf(8))
    expect(cache.byteSize).toBe(8)
    expect(cache.count).toBe(1)
  })

  it('keeps an oversized tile until a newer entry evicts it', () => {
    // Strict LRU: an entry larger than the bound is kept (eviction never
    // drops the newest entry), but it is evicted like any other once it
    // becomes the least recently used.
    const cache = new TileLru(8)
    cache.set('big', bufferOf(64))
    expect(cache.has('big')).toBe(true)
    expect(cache.byteSize).toBe(64)
    cache.set('small', bufferOf(8)) // 'big' is now the oldest entry
    expect(cache.has('big')).toBe(false)
    expect(cache.has('small')).toBe(true)
    expect(cache.byteSize).toBe(8)
  })

  it('evicts until the bound holds across mixed sizes', () => {
    const cache = new TileLru(24)
    cache.set('a', bufferOf(8))
    cache.set('b', bufferOf(8))
    cache.set('c', bufferOf(16)) // evicts 'a' (16+8=24 fits)
    expect(cache.has('a')).toBe(false)
    expect(cache.has('b')).toBe(true)
    expect(cache.has('c')).toBe(true)
    expect(cache.byteSize).toBe(24)
  })

  it('clears all entries and accounting', () => {
    const cache = new TileLru(16)
    cache.set('a', bufferOf(8))
    cache.set('b', bufferOf(8))
    cache.clear()
    expect(cache.count).toBe(0)
    expect(cache.byteSize).toBe(0)
    expect(cache.get('a')).toBeUndefined()
  })

  it('rejects a non-positive bound', () => {
    expect(() => new TileLru(0)).toThrow(RangeError)
    expect(() => new TileLru(-1)).toThrow(RangeError)
  })
})
