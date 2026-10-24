/**
 * Pure tempo-map/grid mapping shared with the Python backend (M3.9 §11.3).
 *
 * All intermediate arithmetic uses exact BigInt rationals. Source frames
 * round half-up once for an edit/snap target; fractional positions remain
 * available for rendering.
 */

export interface Fraction {
  numerator: number
  denominator: number
}

export interface TempoAnchor {
  sourceFrame: number
  musical: Fraction
}

export interface MeterRegion {
  start: Fraction
  numerator: number
  denominator: number
  grouping: number[]
  displayTempoUnit?: string
}

export interface BarOrigin {
  firstNumberedBarPosition: Fraction
  firstBarNumber: number
}

interface BigFraction {
  n: bigint
  d: bigint
}

function gcd(a: bigint, b: bigint): bigint {
  let x = a < 0n ? -a : a
  let y = b < 0n ? -b : b
  while (y !== 0n) {
    const next = x % y
    x = y
    y = next
  }
  return x
}

function normalize(n: bigint, d: bigint): BigFraction {
  if (d === 0n) throw new Error('zero denominator')
  const sign = d < 0n ? -1n : 1n
  const divisor = gcd(n, d) || 1n
  return { n: (n * sign) / divisor, d: (d * sign) / divisor }
}

function big(value: Fraction): BigFraction {
  return normalize(BigInt(value.numerator), BigInt(value.denominator))
}

function add(a: BigFraction, b: BigFraction): BigFraction {
  return normalize(a.n * b.d + b.n * a.d, a.d * b.d)
}

function sub(a: BigFraction, b: BigFraction): BigFraction {
  return normalize(a.n * b.d - b.n * a.d, a.d * b.d)
}

function mul(a: BigFraction, b: BigFraction): BigFraction {
  return normalize(a.n * b.n, a.d * b.d)
}

function div(a: BigFraction, b: BigFraction): BigFraction {
  if (b.n === 0n) throw new Error('division by zero')
  return normalize(a.n * b.d, a.d * b.n)
}

function compare(a: BigFraction, b: BigFraction): number {
  const left = a.n * b.d
  const right = b.n * a.d
  return left < right ? -1 : left > right ? 1 : 0
}

function floorDiv(n: bigint, d: bigint): bigint {
  const quotient = n / d
  return n % d !== 0n && n < 0n !== d < 0n ? quotient - 1n : quotient
}

function isInteger(value: BigFraction): boolean {
  return value.d === 1n
}

function toFraction(value: BigFraction): Fraction {
  return { numerator: Number(value.n), denominator: Number(value.d) }
}

export function roundHalfUp(value: Fraction): number {
  const source = big(value)
  // floor(source + 1/2) = floor((2n + d) / (2d))
  return Number(floorDiv(2n * source.n + source.d, 2n * source.d))
}

export function sourceAtMusical(
  anchors: TempoAnchor[],
  musical: Fraction,
): { fraction: Fraction; sourceFrame: number } {
  if (anchors.length < 2) throw new Error('at least two anchors are required')
  const position = big(musical)
  for (let index = 0; index + 1 < anchors.length; index += 1) {
    const left = anchors[index]
    const right = anchors[index + 1]
    const m0 = big(left.musical)
    const m1 = big(right.musical)
    if (compare(position, m0) >= 0 && compare(position, m1) <= 0) {
      if (compare(m1, m0) <= 0) throw new Error('musical anchors must increase')
      const source = add(
        { n: BigInt(left.sourceFrame), d: 1n },
        div(
          mul(sub(position, m0), {
            n: BigInt(right.sourceFrame - left.sourceFrame),
            d: 1n,
          }),
          sub(m1, m0),
        ),
      )
      return { fraction: toFraction(source), sourceFrame: roundHalfUp(toFraction(source)) }
    }
  }
  throw new Error('musical position is outside the mapped interval')
}

export function musicalAtSource(anchors: TempoAnchor[], sourceFrame: number): Fraction {
  if (anchors.length < 2) throw new Error('at least two anchors are required')
  const source = { n: BigInt(sourceFrame), d: 1n }
  for (let index = 0; index + 1 < anchors.length; index += 1) {
    const left = anchors[index]
    const right = anchors[index + 1]
    if (sourceFrame >= left.sourceFrame && sourceFrame <= right.sourceFrame) {
      if (right.sourceFrame <= left.sourceFrame) {
        throw new Error('source anchors must increase')
      }
      const musical = add(
        big(left.musical),
        div(
          mul(
            sub(source, { n: BigInt(left.sourceFrame), d: 1n }),
            sub(big(right.musical), big(left.musical)),
          ),
          { n: BigInt(right.sourceFrame - left.sourceFrame), d: 1n },
        ),
      )
      return toFraction(musical)
    }
  }
  throw new Error('source frame is outside the mapped interval')
}

function barLength(region: MeterRegion): BigFraction {
  return normalize(4n * BigInt(region.numerator), BigInt(region.denominator))
}

function barsBefore(regions: MeterRegion[], index: number): bigint {
  let total = 0n
  for (let regionIndex = 0; regionIndex < index; regionIndex += 1) {
    const region = regions[regionIndex]
    const next = regions[regionIndex + 1]
    const span = sub(big(next.start), big(region.start))
    const bars = div(span, barLength(region))
    if (!isInteger(bars)) {
      throw new Error('meter region does not begin on a whole bar boundary')
    }
    total += bars.n
  }
  return total
}

export function barBeatLabel(
  regions: MeterRegion[],
  origin: BarOrigin,
  musical: Fraction,
): { barNumber: number | null; beat: number | null; pickup: boolean; label: string } {
  if (regions.length === 0) throw new Error('at least one meter region is required')
  const value = big(musical)
  const originPosition = big(origin.firstNumberedBarPosition)
  if (compare(value, originPosition) < 0) {
    return { barNumber: null, beat: null, pickup: true, label: 'pickup' }
  }
  let containing = 0
  for (let index = 0; index < regions.length; index += 1) {
    if (compare(value, big(regions[index].start)) >= 0) containing = index
  }
  const region = regions[containing]
  const length = barLength(region)
  const within = div(sub(value, big(region.start)), length)
  const barsInto = floorDiv(within.n, within.d)
  const barStart = add(big(region.start), mul({ n: barsInto, d: 1n }, length))

  let originRegion = 0
  for (let index = 0; index < regions.length; index += 1) {
    if (compare(originPosition, big(regions[index].start)) >= 0) originRegion = index
  }
  const originWithin = div(
    sub(originPosition, big(regions[originRegion].start)),
    barLength(regions[originRegion]),
  )
  if (!isInteger(originWithin)) {
    throw new Error('first numbered bar must start on a bar boundary')
  }
  const originIndex = barsBefore(regions, originRegion) + originWithin.n
  const currentIndex = barsBefore(regions, containing) + barsInto
  if (currentIndex < originIndex) {
    return { barNumber: null, beat: null, pickup: true, label: 'pickup' }
  }
  const barNumber = origin.firstBarNumber + Number(currentIndex - originIndex)
  let beat = 1
  let cumulative = { n: 0n, d: 1n }
  for (let index = 0; index < region.grouping.length; index += 1) {
    const part = region.grouping[index]
    const boundary = add(barStart, cumulative)
    if (compare(value, boundary) >= 0) beat = index + 1
    cumulative = add(cumulative, normalize(4n * BigInt(part), BigInt(region.denominator)))
  }
  return { barNumber, beat, pickup: false, label: `${barNumber}.${beat}` }
}
