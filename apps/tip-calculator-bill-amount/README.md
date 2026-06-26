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

## Standalone Python build

The canonical implementation is a zero-dependency Python 3 build (stdlib only):

    python3 server.py            # serves http://localhost:8000
    python3 -m unittest -v       # full test suite

Domain logic and the HTTP layer both live in `server.py`; tests in `test_app.py`.
JSON endpoints (all `POST` unless noted):

- `/api/calculate` — tip + total from bill/percent, with tax-awareness, pre/post-tax
  tipping, round-up, and per-person split (REQ-001/REQ-002).
- `/api/suggestions` — tip/total across several tip tiers.
- `/api/reverse` — back out the tip needed to hit a target grand total.
- `/api/round-split` — split with each share rounded up to a clean increment.
- `/api/split` — split the total unevenly by weighted shares.
- `/api/items-split` — itemised split: each diner pays their own items plus a
  fair share of tax and tip.
- `/api/settle` — **settle up**: given what each diner already paid, report each
  one's fair share, balance, and a minimal list of transfers (who pays whom) so
  the table ends square (REQ-002 extension).
- `/api/rating` — suggest a tip from a 1–5 star service rating, then calculate it.
- `/api/change` — make cash change for a total, broken into the fewest US
  bills/coins.
- `/api/combine` — combine several cheques (each with its own tip rate/tax) into
  one grand total and split it evenly.
- `/api/discount` — apply a coupon/discount (flat amount or percent) to the bill,
  then tip and split; choose whether to tip on the pre- or post-discount amount
  (REQ-001 extension).
- `/api/tip-pool` — distribute a collected tip pool among staff weighted by hours,
  summing exactly to the pool via largest-remainder (REQ-002 extension).
- `/api/auto-gratuity` — large-party automatic gratuity: a mandatory tip kicks in
  once the party reaches a size threshold, and a chosen tip below it is bumped up
  (REQ-001 extension).
- `/api/split-percentage` — split the grand total by explicit per-diner percentages
  that must total 100, reconciled to the cent via largest-remainder (REQ-002 extension).
- `/api/target-per-person` — back out the tip needed so each diner pays a clean,
  chosen per-person amount (REQ-001/002 extension).
- `/api/round-total` — round the grand total to a clean increment (up / nearest /
  down), folding the change into the tip; honours tax and pre/post-tax tipping and
  splits the rounded total exactly across people (REQ-001/002 extension).
- `/api/split-comped` — even split where some diners are treated (a birthday comp):
  the comped diners pay nothing and their share is redistributed exactly across the
  remaining payers (REQ-002 extension).
- `/api/gross-up-tip` — gross up a card tip so the server still nets the intended
  gratuity after the payment processor's percentage fee (REQ-001 extension).
- `/api/shared-items` — itemised split that also handles SHARED items: each diner
  pays their own items plus a fair portion of every shared item (split among its
  named sharers), with tax/tip apportioned by consumption and reconciled exactly
  to the cent (REQ-002 extension).
- `/api/regional-tip` — suggest a customary gratuity for a country/region (e.g.
  18% in the US, ~10% across much of Europe, 0% in Japan), then calculate it; the
  typical low/high range is returned for context (REQ-001 extension).
- `/api/charity` — round the checkout total UP for a charity donation: the spare
  change becomes a separate donation line and the server's tip is left untouched
  (distinct from `/api/round-total`, which folds the round-up into the tip); also
  accepts an explicit fixed donation and splits the total exactly across people
  (REQ-001/002 extension).
- `/api/diner-tips` — per-diner INDIVIDUAL tip rates: each diner brings their own
  pre-tax portion of the bill AND their own chosen tip percent ("I tip 25%, you
  tip 15%"); shared tax is apportioned across diners in proportion to their portion
  via largest-remainder, and each diner pays amount + tax share + their own tip.
  Distinct from `/api/items-split` and `/api/split` (single table-wide rate) and
  `/api/split-percentage` (fixed shares of one total) (REQ-001/002 extension).
- `/api/affordable-bill` — inverse **planner**: given a per-person `budget`, a
  `tip_percent` and a sales-`tax_percent` rate, solve for the largest pre-tax food
  bill the table can afford ("we've each got $50 and tip 20% — what can we
  order?"). Honours pre/post-tax tipping, floors to the cent so the grand total
  never exceeds budget, splits it exactly across people and reports the leftover
  `headroom`. Distinct from `/api/reverse` and `/api/target-per-person`, which
  take the bill as given and solve for the TIP (REQ-001/002 extension).
- `/api/card-split` — **card surcharge split**: each diner brings their own pre-tax
  portion and a `method` (`card`/`cash`, default cash); a single table-wide
  `tip_percent` and apportioned `tax` apply to everyone, then `card_surcharge`
  percent is added ON TOP of each CARD payer's own (amount + tax + tip) subtotal
  while cash payers add nothing. Reports per-diner `surcharge`/`total`, the
  `card_count`/`cash_count`, and totals that reconcile to the cent. Distinct from
  `/api/diner-tips` (per-diner tip *rates*) and `/api/service-charge` (one flat fee
  on the whole bill) (REQ-001/002 extension).
- `GET /health` — liveness probe.
