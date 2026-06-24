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
- `/api/stats` — `{items:[{value,unit},...], to?}` → count, sum, mean, min, max
  (each with its item index) and range of same-category quantities.
- `/api/describe` — `{items:[{value,unit},...], to?}` → the richer companion to
  `/api/stats`: adds **median**, **variance** and population & sample **standard
  deviation** (the sample figures are `null` for a single item).
- `/api/shape` — `{items:[{value,unit},...], to?}` → the third-/fourth-moment
  companion to `/api/describe`: the **skewness** (lopsidedness) and **excess
  kurtosis** (tail weight), in both population (`g1`/`g2`) and bias-corrected
  sample (`G1`/`G2`, à la Excel `SKEW`/`KURT`) flavours. The standardised
  moments are dimensionless (unit-independent); a flat series reports `null`,
  and the sample figures are `null` below 3 (skewness) / 4 (kurtosis) points.
- `/api/sort` — `{items:[{value,unit},...], to?, descending?}` → the items
  ordered by magnitude on a common unit, each tagged with its original index.
- `/api/cumsum` — `{items:[{value,unit},...], to?}` → the running (cumulative)
  total after each item, in input order (the "how does the total build up?"
  companion to `/api/sum`).
- `/api/percentile` — `{items:[{value,unit},...], percentile, to?}` → the p-th
  percentile (R-7 / Excel `PERCENTILE.INC`); P0 is the min, P100 the max, P50
  the median reported by `/api/describe`.
- `/api/proportions` — `{items:[{value,unit},...], to?}` → each quantity's share
  of the group total as a `fraction` and a `percent` (fractions sum to 1,
  percentages to 100); rejects a zero total.
- `/api/parse-compound` — `{expression:"6 ft 2 in", to?}` → parsed parts plus
  their total (the inverse of `/api/compound`).
- `/api/convert-delta` — `{value, from, to}` → an **interval** conversion (a
  10&deg;C *change* is an 18&deg;F change, not 50&deg;F).
- `/api/quartiles` — `{items:[{value,unit},...], to?}` → the five-number summary
  (min, Q1, median, Q3, max) plus the **IQR** (Q3 − Q1) of same-category
  quantities; Q1/median/Q3 use the same R-7 method as `/api/percentile`.
- `/api/outliers` — `{items:[{value,unit},...], to?, k?}` → each quantity flagged
  by **Tukey's IQR fences** (`lower = Q1 − k·IQR`, `upper = Q3 + k·IQR`; `k`
  defaults to 1.5), with the fences and outlier count.
- `/api/histogram` — `{items:[{value,unit},...], bins, to?}` → equal-width bin
  counts over the observed `[min, max]` range (counts sum to `count`; the final
  bin is closed on `max`).
- `/api/means` — `{items:[{value,unit},...], to?}` → the four classical means
  (arithmetic, geometric, harmonic, quadratic/RMS); rejects non-positive values.
- `/api/rank` — `{items:[{value,unit},...], to?, descending?}` → each quantity's
  fractional **rank** (ties share the average rank) and **percent rank**.
- `/api/mode` — `{items:[{value,unit},...], to?}` → the **mode(s)**, the most
  frequent magnitude(s) on a common unit, with the highest `frequency` and an
  `is_multimodal` flag (the third measure of central tendency alongside the
  mean/median of `/api/describe`).
- `/api/weighted-mean` — `{items:[{value,unit,weight?},...], to?}` → the
  **weighted average** `sum(w·v)/sum(w)`; a missing `weight` defaults to 1, so an
  unweighted list reduces to the plain mean. Rejects negative weights and a zero
  total weight.
- `/api/moving-average` — `{items:[{value,unit},...], window, to?}` → the simple
  **moving (rolling) average** over each contiguous window of `window` items (an
  `n`-item list yields `n − window + 1` averages); the smoothing companion to
  `/api/cumsum` and `/api/diff`.
- `/api/gini` — `{items:[{value,unit},...], to?}` → the **Gini inequality
  coefficient** (in `[0, 1]`; 0 = perfect equality, → 1 = one quantity holds
  almost everything) of same-category quantities, plus `rmad` (the relative mean
  absolute difference, `2·gini`) and `mean_abs_difference` (its absolute form).
  The inequality/concentration companion to `/api/proportions`; rejects negative
  values (an all-equal or all-zero list is `gini = 0`).
