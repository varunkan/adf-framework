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

## Standalone Python converter

The live app is a dependency-free Python 3 implementation (`server.py` +
`domain.py` + `index.html`). Run it with `python3 server.py` and open
`http://127.0.0.1:8000/`; run the tests with `python3 -m unittest -v`.

It converts across ~30 categories (length, mass, temperature, volume, time,
area, speed, digital storage, data rate, pressure, energy, power, angle,
frequency, force, electrical, and more) plus fuel economy.

### API

GET routes: `/api/health`, `/api/units`, `/api/categories`,
`/api/unit-info?unit=`, `/api/factor?from=&to=`, `/api/search?q=`.

POST routes:

- `/api/convert` — `{value, from, to}` (or legacy `{value, direction}`).
- `/api/convert-all` — `{value, from}` → value in every unit of the category.
- `/api/convert-batch` — `{conversions: [...]}`.
- `/api/convert-table` — `{from, to, start, stop, step}`.
- `/api/compound` — `{value, from, units:[...]}` → mixed-unit breakdown.
- `/api/parse` — `{expression: "10 km to mi"}`.
- `/api/humanize` — `{value, from}` → auto-scaled to the readable unit.
- `/api/compare` — `{a:{value,unit}, b:{value,unit}}`.
- `/api/sum` — `{items:[{value,unit},...], to?}` → total of same-category
  quantities (`2 ft + 30 cm + 1 m`).
- `/api/parse-compound` — `{expression:"6 ft 2 in", to?}` → parsed parts plus
  their total (the inverse of `/api/compound`).
- `/api/convert-delta` — `{value, from, to}` → an **interval** conversion (a
  10&deg;C *change* is an 18&deg;F change, not 50&deg;F).
