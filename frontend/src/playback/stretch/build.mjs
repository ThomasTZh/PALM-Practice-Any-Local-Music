#!/usr/bin/env node
// build.mjs — build the stretch WASM artifacts (M2.9, spec §11.3).
//
// Explicit developer setup/build command. Requires the pinned toolchain
// in `third_party/emsdk` (see the repo-root .gitignore note):
//
//   git clone https://github.com/emscripten-core/emsdk third_party/emsdk
//   ./third_party/emsdk/emsdk install 4.0.23
//   ./third_party/emsdk/emsdk activate 4.0.23
//   git clone https://github.com/Signalsmith-Audio/signalsmith-stretch \
//     third_party/signalsmith-stretch
//   git clone --depth 1 --branch 0.6.4 \
//     https://github.com/Signalsmith-Audio/linear third_party/signalsmith-linear
//
// then:
//
//   node frontend/src/playback/stretch/build.mjs
//
// Emits `dist/stretch-scalar.{js,wasm}` and `dist/stretch-simd.{js,wasm}`
// plus a `BUILD.md` manifest (pinned versions + SHA-256 hashes). The
// artifacts are committed so the app launches with no compiler present
// (spec §11.3.10–11).

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..', '..', '..', '..')

const EMSDK = path.join(root, 'third_party', 'emsdk')
const EMSDK_VERSION = '4.0.23'
const STRETCH_INC = path.join(root, 'third_party', 'signalsmith-stretch', 'include')
const LINEAR_INC = path.join(root, 'third_party', 'signalsmith-linear', 'include')
const DIST = path.join(here, 'dist')
const SRC = path.join(here, 'stretch_wrapper.cpp')

const EXPORTS = [
    '_stretch_configure',
    '_stretch_input_latency',
    '_stretch_output_latency',
    '_stretch_window_length',
    '_stretch_seek',
    '_stretch_process',
    '_stretch_set_rate',
    '_stretch_set_rate_now',
    '_stretch_effective_rate',
    '_stretch_reset',
    '_stretch_pool_offset',
    '_stretch_pool_input_frames',
].join(',')

mkdirSync(DIST, { recursive: true })

function sha256(file) {
    return createHash('sha256').update(readFileSync(file)).digest('hex')
}

function gitHead(dir) {
    try {
        return execFileSync('git', ['-C', dir, 'rev-parse', 'HEAD'], {
            encoding: 'utf8',
        }).trim()
    } catch {
        return 'unknown'
    }
}

function emccArgs(outFile, exportName, extra) {
    return [
        `-o`,
        `"${outFile}"`,
        `"${SRC}"`,
        `-I`,
        `"${STRETCH_INC}"`,
        `-I`,
        `"${LINEAR_INC}"`,
        '-std=c++17',
        '-O3',
        '-ffast-math',
        '-fno-exceptions',
        '-fno-rtti',
        `-sMODULARIZE=1`,
        `-sEXPORT_NAME=${exportName}`,
        '-sENVIRONMENT=web,worker,shell',
        '-sNO_EXIT_RUNTIME=1',
        '-sFILESYSTEM=0',
        // Fixed memory: the audio callback must never grow the heap (§14.7).
        '-sINITIAL_MEMORY=2mb',
        '-sALLOW_MEMORY_GROWTH=0',
        '-sSTRICT=1',
        '-sDYNAMIC_EXECUTION=0',
        `--closure=0`,
        `-sEXPORTED_FUNCTIONS=${EXPORTS}`,
        ...extra,
    ].join(' ')
}

function build(variant, extra) {
    const outFile = path.join(DIST, `stretch-${variant}.js`)
    const script =
        `cd "${EMSDK}" && EMSDK_QUIET=1 . ./emsdk_env.sh && ` +
        `em++ ${emccArgs(outFile, `StretchWasm${variant[0].toUpperCase()}${variant.slice(1)}`, extra)}`
    process.stdout.write(`\n=== building ${variant} ===\n`)
    execFileSync('bash', ['-c', script], { stdio: 'inherit' })
}

build('scalar', [])
build('simd', ['-msimd128'])

const artifacts = {}
for (const variant of ['scalar', 'simd']) {
    for (const ext of ['js', 'wasm']) {
        const f = path.join(DIST, `stretch-${variant}.${ext}`)
        artifacts[`${variant}.${ext}`] = sha256(f)
    }
}

const manifest = `# Stretch WASM build manifest (M2.9)

Built ${new Date().toISOString()} by \`build.mjs\`.

## Pinned inputs

| input | pin |
| --- | --- |
| Emscripten SDK | ${EMSDK_VERSION} (\`third_party/emsdk\`, gitignored) |
| signalsmith-stretch | \`${gitHead(path.join(root, 'third_party', 'signalsmith-stretch'))}\` |
| signalsmith-linear | \`${gitHead(path.join(root, 'third_party', 'signalsmith-linear'))}\` (tag 0.6.4) |
| wrapper source | \`${sha256(SRC)}\` (stretch_wrapper.cpp) |

## Artifacts (SHA-256)

| artifact | SHA-256 |
| --- | --- |
| dist/stretch-scalar.js | \`${artifacts['scalar.js']}\` |
| dist/stretch-scalar.wasm | \`${artifacts['scalar.wasm']}\` |
| dist/stretch-simd.js | \`${artifacts['simd.js']}\` |
| dist/stretch-simd.wasm | \`${artifacts['simd.wasm']}\` |

## Build flags

\`\`\`
em++ stretch_wrapper.cpp
  -std=c++17 -O3 -ffast-math -fno-exceptions -fno-rtti
  -sMODULARIZE=1 -sEXPORT_NAME=StretchWasm<Variant>
  -sENVIRONMENT=web,worker,shell
  -sNO_EXIT_RUNTIME=1 -sFILESYSTEM=0
  -sINITIAL_MEMORY=2mb -sALLOW_MEMORY_GROWTH=0
  -sSTRICT=1 -sDYNAMIC_EXECUTION=0 --closure=0
  -sEXPORTED_FUNCTIONS=_stretch_*
  (SIMD variant adds -msimd128)
\`\`\`

Memory is fixed at 2 MiB (no growth): the pre-allocated I/O pool
(2 × windowFrames + 2 × maxFrames floats; windowFrames = 7200 @48k,
maxFrames = 4096 → ≈88 KiB) plus the engine state must fit, so the
audio callback can never trigger a heap grow.
`

writeFileSync(path.join(here, 'BUILD.md'), manifest)
process.stdout.write('\nBUILD.md written.\n')
