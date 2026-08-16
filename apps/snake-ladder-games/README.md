# ADF app — react-vite-sqlite

React + Vite + Tailwind frontend; Fastify + better-sqlite3 backend; served as a
single process on `PORT`.

    npm ci
    npm run build      # tsc typecheck + vite build -> dist/
    npm start          # node server/index.mjs  (serves dist/ + /api/*)
    npm test           # vitest

Generated feature code lives in `src/**` (UI), `server/api/**` (routes), and
`schema.sql` (tables). The server serves the built SPA at `/` and the JSON API
under `/api/*`, owning a local SQLite file.
