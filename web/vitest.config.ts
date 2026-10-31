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
  },
})
