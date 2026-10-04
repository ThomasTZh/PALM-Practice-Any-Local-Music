/**
 * Byte-bounded LRU cache for fetched peak tiles (spec §12.5.4).
 *
 * Keys are `<source_hash>/<level>/<tile>`; values are the raw tile
 * `ArrayBuffer`s. Whole tiles are evicted least-recently-used until the
 * byte bound holds. Eviction never drops the most recently inserted
 * entry, so a tile larger than the whole bound is kept until a newer
 * entry arrives and it becomes the least recently used.
 */

const DEFAULT_MAX_BYTES = 32 * 1024 * 1024

export function tileKey(sourceHash: string, level: number, tile: number): string {
  return `${sourceHash}/${level}/${tile}`
}

export class TileLru {
  private readonly entries = new Map<string, ArrayBuffer>()
  private bytes = 0
  readonly maxBytes: number

  constructor(maxBytes: number = DEFAULT_MAX_BYTES) {
    if (!(maxBytes > 0)) throw new RangeError('maxBytes must be > 0')
    this.maxBytes = maxBytes
  }

  get(key: string): ArrayBuffer | undefined {
    const value = this.entries.get(key)
    if (value === undefined) return undefined
    // Refresh recency: Map iteration order is insertion order.
    this.entries.delete(key)
    this.entries.set(key, value)
    return value
  }

  set(key: string, value: ArrayBuffer): void {
    if (this.entries.has(key)) {
      this.bytes -= value.byteLength
      this.entries.delete(key)
    }
    this.entries.set(key, value)
    this.bytes += value.byteLength
    this.evict()
  }

  has(key: string): boolean {
    return this.entries.has(key)
  }

  clear(): void {
    this.entries.clear()
    this.bytes = 0
  }

  get byteSize(): number {
    return this.bytes
  }

  get count(): number {
    return this.entries.size
  }

  /** Evict least-recently-used tiles until within the byte bound. */
  private evict(): void {
    // Keep at least the newest entry even if it alone exceeds the bound.
    while (this.bytes > this.maxBytes && this.entries.size > 1) {
      const oldest = this.entries.keys().next().value as string
      const value = this.entries.get(oldest) as ArrayBuffer
      this.entries.delete(oldest)
      this.bytes -= value.byteLength
    }
  }
}
