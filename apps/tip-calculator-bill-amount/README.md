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
- `/api/tiered-tax` — **split-rate tax**: many jurisdictions tax prepared food and
  alcohol at DIFFERENT rates (e.g. food 6%, liquor 10%). Given a pre-tax `food`
  subtotal and a pre-tax `alcohol` subtotal — each taxed at its own
  `food_tax_percent`/`alcohol_tax_percent` — it returns the per-category tax, the
  combined `tax` and `blended_tax_percent`, the gratuity (on the pre-tax subtotal
  by default, or the tax-inclusive total when `tip_on="total"`), the grand total
  and a per-person split reconciled exactly to the cent via largest-remainder.
  Distinct from `/api/build-bill` and `/api/calculate`, which apply ONE tax figure
  to the whole cheque (REQ-001/002 extension).
- `/api/guest-of-honor` — **treat the guest of honor**: the classic birthday /
  anniversary "your money's no good here". Given `bill`, `tip_percent`, `people`
  and a `guests` list of 0-based diner indices to treat, the honorees pay nothing
  and the remaining payers split the ENTIRE grand total evenly, reconciled exactly
  to the cent via largest-remainder. Treating everyone fails safe (someone must
  cover the cheque); an empty `guests` list reduces to a plain even split. Distinct
  from `/api/split-comped` (removes comped items from the total) and
  `/api/split-caps` (caps a contribution) — here the full total is still paid, just
  by fewer people (REQ-002 extension).
- `/api/clean-split` — **clean even split**: the everyday "I'll put it on my card,
  just send me a round number". The grand total is split evenly across `people`,
  but every diner EXCEPT the designated `organizer` (0-based index of whoever paid
  the cheque) rounds their fair share to the nearest `nearest` increment (default
  `$1`) so they can hand over tidy cash; the organizer pays whatever is left so the
  payments still sum EXACTLY to the total. Honours `tax` and pre/post-tax tipping,
  and reports each diner's `amount`, the `organizer_amount` and the
  `organizer_delta` (how much more/less the organizer pays than an exact share). An
  increment so large the others would cover more than the whole cheque fails safe.
  Distinct from `/api/round-split` (rounds EVERY share UP into a surplus kitty,
  growing the total) and `/api/guest-of-honor` (some diners pay nothing) — here the
  true total is preserved and only the rounding remainder shifts onto the organizer
  (REQ-002 extension).
- `/api/loyalty-redeem` — **redeem rewards points**: burn a loyalty/rewards balance
  for a statement credit at the till. `points` redeem only in whole `increment`
  blocks (e.g. 100-point chunks) at `point_value` dollars each (default `0.01` →
  100 pts = $1); the credit is capped at what's actually owed for goods
  (`bill + tax`) and, optionally, at `max_redeem`, so a diner can never redeem the
  tip away or drive the bill negative — leftover points come back as
  `remaining_points`. Crucially the gratuity is charged on the FULL pre-redemption
  service value (`tip_on` `subtotal`/`total`), because the redemption is a *payment*
  credit, not a price cut. Reports `redeemed_points`, `redemption`, `tip`,
  `amount_due` and the exact even per-person split. Distinct from `/api/discount`
  (lowers the tip base — you tip on the cheaper price) and `/api/tip-excluding`
  (holds part of the cheque out of the tip but you still pay it) — here you pay LESS
  but tip on the whole (REQ-001/002 extension).
- `GET /health` — liveness probe.
