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
- `/api/lorenz` — `{items:[{value,unit},...], to?}` → the **Lorenz curve** of
  same-category quantities: with the values sorted ascending, each of the `n+1`
  points (from `(0,0)` to `(1,1)`) pairs the cumulative **population share**
  (`population_fraction = i/n`, the smallest `i` items) with the cumulative
  **value share** (`value_fraction`, the fraction of the total those items hold,
  plus the running `cumulative_value`). The per-point dataset companion to the
  scalar `/api/gini` — exactly as `/api/winsorize` is to `/api/trimmed-mean`:
  where the Gini collapses inequality to one number, the curve returns the whole
  shape behind it. Reports the `area_under_curve` (trapezoidal, in `[0, 0.5]`;
  0.5 = the perfect-equality diagonal) and the `gini` recovered geometrically as
  `1 − 2·area_under_curve`, identical to `/api/gini`. Rejects negative values; an
  all-equal or all-zero list is the diagonal (`gini = 0`).
- `/api/spearman` — `{x:[{value,unit},...], y:[...], to_x?, to_y?}` → the
  **Spearman rank correlation** `rho` (in `[-1, 1]`) of two paired quantity
  series: Pearson's `r` computed on the fractional ranks of each series, so it
  measures *monotonic* (not merely linear) association, is robust to outliers and
  invariant under any monotonic rescaling of either series. The rank-based
  companion to `/api/correlation` (linear Pearson `r`); reports `has_ties` and is
  `null` when either series has zero spread.
- `/api/kendall` — `{x:[{value,unit},...], y:[...], to_x?, to_y?}` → **Kendall's
  tau-b** rank correlation (in `[-1, 1]`), the third member of the paired-series
  correlation family alongside Pearson `/api/correlation` and Spearman
  `/api/spearman`. Built from the **concordant**/**discordant** agreement of
  *every pair* of observations rather than ranks-then-Pearson, so it reads as a
  probability of concordance; reports `concordant`, `discordant`, the simpler
  `tau_a` `(C−D)/n0`, the per-axis tie counts (`ties_x`/`ties_y`), `has_ties`,
  and is `null` when either series has zero spread. Dimensionless and invariant
  under any monotonic rescaling of either series.
- `/api/theil-sen` — `{x:[{value,unit},...], y:[...], to_x?, to_y?}` → the
  **Theil–Sen robust linear fit** `y = slope·x + intercept`, the
  outlier-resistant companion to least-squares `/api/regression`. The slope is
  the **median of every pairwise slope** `(yj−yi)/(xj−xi)` and the intercept the
  median of `(y − slope·x)`, so up to ~29% of the data can be corrupted without
  swinging the line. The slope carries `y_unit/x_unit`, the intercept `y_unit`;
  reports the total `pairs`, the `used_pairs` (distinct-`x` finite slopes), the
  `tied_pairs` skipped for sharing an `x`, plus each series' `median`/`mean`. A
  series whose every `x` is equal (no finite slope) is a `400`.
- `/api/residuals` — `{x:[{value,unit},...], y:[...], to_x?, to_y?}` → the
  **per-point diagnostic** companion to `/api/regression`: the least-squares line
  evaluated at every paired point, reporting each point's `fitted` value
  `ŷ = slope·x + intercept` and `residual` `y − ŷ` (both in `y_unit`). Adds the
  variance decomposition `sst = ssr + sse` (total = explained + residual sum of
  squares), `r_squared` `= ssr/sst` (`null` when `y` has zero spread), and the
  **residual standard error** `√(sse/(n−2))` — the typical residual size — which
  is `null` for exactly two points (no residual degrees of freedom). A series
  whose every `x` is equal (no finite slope) is a `400`.
- `/api/trimmed-mean` — `{items:[{value,unit},...], proportion?, to?}` → the
  robust **trimmed mean** and **winsorized mean** of same-category quantities,
  restated in `to` (or the first item's unit). `proportion` is the fraction
  trimmed from *each* tail (default `0.1`, must be in `[0, 0.5)`): the trimmed
  mean drops the `floor(n·proportion)` smallest and largest values and averages
  the rest, while the winsorized mean instead *clamps* those extremes to the
  nearest kept value (`lower`/`upper`) before averaging all `n`. Reports the
  plain `mean` alongside, plus `trimmed_each_side` and `kept`. The
  outlier-resistant location companion to `/api/means` (classical means) and
  `/api/mad` (robust spread); rejects a `proportion` outside `[0, 0.5)`.
- `/api/winsorize` — `{items:[{value,unit},...], proportion?, to?}` → the full
  **winsorized series** of same-category quantities, one entry per input in the
  original order, each clamped to the trim bounds and flagged, restated in `to`
  (or the first item's unit). Where `/api/trimmed-mean` collapses the data to the
  scalar winsorized *mean*, this returns the whole transformed dataset: with the
  values sorted ascending and `g = floor(n·proportion)`, every value below
  `lower` (`= ordered[g]`) is raised to `lower` and every value above `upper`
  (`= ordered[n−1−g]`) is lowered to `upper`, while the middle block is left
  untouched. Each item reports its `winsorized` value and whether it was
  `clamped` (strictly outside `[lower, upper]`); also reports the untouched
  `mean`, the `winsorized_mean` (identical to the one `/api/trimmed-mean` gives
  for the same `proportion`) and the `winsorized_stdev` (population stdev of the
  clamped series). `proportion` is the fraction clamped from *each* tail (default
  `0.1`, must be in `[0, 0.5)`). The per-item transformation companion to
  `/api/trimmed-mean`, alongside `/api/zscore`, `/api/normalize` and
  `/api/outliers`.
- `/api/ema` — `{items:[{value,unit},...], alpha?, span?, to?}` → the
  **exponential moving average** (exponential smoothing) over each item on a
  common unit (`ema[0] = value[0]`, `ema[i] = α·value[i] + (1−α)·ema[i−1]`). The
  smoothing factor is given as `alpha` (in `(0, 1]`) **or** as a `span` `s`
  (`≥ 1`, mapped to `α = 2/(s+1)`); supply at most one, defaulting to `alpha`
  0.5. Unlike the equal-weighted, full-window `/api/moving-average`, an EMA emits
  one smoothed value per item over the whole history and weights recent items
  more heavily — the reactive smoothing companion to `/api/cumsum` and
  `/api/diff`.
- `/api/autocorrelation` — `{items:[{value,unit},...], maxlag?, to?}` → the
  **serial (auto)correlation** `r_k` of a *single* series at lags `0..maxlag`,
  on a common unit. Where the bivariate `/api/correlation` family relates two
  different series, this correlates one series with a delayed copy of itself — the
  standard trend/seasonality/momentum diagnostic, the serial-dependence companion
  to `/api/moving-average`, `/api/ema` and `/api/diff`. Uses the population mean
  (`r_k = Σ(xₜ−m)(xₜ₋ₖ−m) / Σ(xₜ−m)²`), so `r0` is always `1` and every `r_k` is
  in `[-1, 1]`. The coefficients are **dimensionless** (invariant under `to`);
  only the reported `mean`/`variance`/`stdev` carry the unit. `maxlag` is optional
  and defaults to `count − 1` (must be an integer in `[0, count − 1]`); rejects
  fewer than two items or a **zero-variance** series (every value identical).
- `/api/robust-zscore` — `{items:[{value,unit},...], threshold?, to?}` → each
  quantity's **modified (robust) z-score**, the Iglewicz–Hoaglin score
  standardised against the **median** and the **median absolute deviation (MAD)**
  rather than the outlier-sensitive mean and stdev of `/api/zscore`:
  `Mi = 0.6745·(x − median)/MAD`. An item is flagged `is_outlier` when `|Mi|`
  exceeds `threshold` (default 3.5, the Iglewicz–Hoaglin cut-off). The score is
  **dimensionless** (invariant under `to`); only `median`/`mad` carry the unit.
  When the MAD is zero it falls back to the **mean** absolute deviation about the
  median (`Mi = (x − median)/(1.253314·meanAD)`), reporting `method` as `"mad"`
  or `"meanad"`. Rejects a non-positive `threshold` and an all-identical series
  (both deviations vanish). The outlier-robust companion to `/api/zscore`,
  `/api/mad` and `/api/outliers`.
- `/api/confidence-interval` — `{items:[{value,unit},...], confidence?, to?}` →
  a two-sided **confidence interval for the population mean**, using the
  large-sample **normal (z) approximation**: with the sample mean `x̄`, the
  unbiased sample stdev `s` (`/(n−1)`) and `n` observations, the **standard error
  of the mean** is `SE = s/√n`, the critical value is the normal quantile
  `z = Φ⁻¹((1+confidence)/2)`, the **margin of error** is `z·SE` and the interval
  is `[x̄ − z·SE, x̄ + z·SE]`. Reports `mean`, `sample_stdev`, `standard_error`,
  `critical_value`, `margin_of_error` and the `lower`/`upper` bounds.
  `confidence` defaults to 0.95 and must lie strictly in `(0, 1)` (0.95 → z≈1.96,
  0.99 → z≈2.576). The probit `Φ⁻¹` is computed in-house (Acklam's
  approximation + a Halley refinement against `math.erfc`) — standard library
  only. Requires at least two values (the standard error is undefined for one
  observation). The inferential companion to `/api/describe`.
