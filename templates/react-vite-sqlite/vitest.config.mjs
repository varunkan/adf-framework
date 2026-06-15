import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    env: { ADF_DB_PATH: ':memory:' },
    server: { deps: { external: ['better-sqlite3'] } },
  },
})
