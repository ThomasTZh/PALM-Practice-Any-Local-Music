import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// jsdom is the default because most suites render components. Audio and WASM
// suites that need Node primitives opt out per file with
// `// @vitest-environment node` at the top of the test.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    passWithNoTests: true,
    // Real-WASM player suites (1x/0.5x loops, 60 s sessions) and the App
    // integration suites legitimately exceed Vitest's 5 s default when the host
    // is busy; 30 s matches the Playwright/browser budget instead of killing a
    // working test. This does not extend the tests' own waits or weaken checks.
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // Run test files one at a time. The spectrogram performance test measures a
    // single 1280 px STFT view against a 100 ms best-walled target; parallel
    // heavy player/WASM files steal CPU and inflate that measurement (observed
    // 100-571 ms). Serializing files makes the benchmark see one view change
    // instead of host contention. Individual tests within a file stay ordered.
    fileParallelism: false,
  },
})
