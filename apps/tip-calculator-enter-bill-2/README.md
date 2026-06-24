# tip-calculator-enter-bill-2

A tip calculator: enter a bill amount and tip percent, see the tip and total,
and split it fairly across any number of people. Pure Python 3 standard library
only — no dependencies, no build step.

    python3 server.py          # serves http://127.0.0.1:8000
    python3 -m unittest -v     # run the test suite

## Features

- **Tip & total** — enter a bill and tip %, get the tip and grand total.
- **Fair split** — divide the total across N people; integer-cent splitting
  guarantees the shares sum back exactly to the total and differ by at most one
  cent.
- **Sales tax** — add a tax %, with the tip figured on either the pre-tax
  subtotal (default etiquette) or the post-tax amount.
- **Round up** — round the grand total up to the next whole dollar, absorbing
  the extra cents into the tip.
- **Quick tips** — one-tap suggestions at common preset percentages.
- **Service-quality recommendations** — pick how the service was (poor → fair →
  good → great → exceptional) and get the conventional tip percentage applied.
- **Uneven / weighted split** — apportion the bill by weights (e.g. `[2, 1, 1]`
  so one person covers half) using the largest-remainder method.
- **Itemized split** — split by what each person actually ordered; tax and tip
  are apportioned to each person in proportion to their own subtotal.
- **Target total** — work backwards from the grand total you want to pay to the
  tip (and effective tip %) needed to hit it.
- **Discounts / coupons** — take a percentage or flat-dollar discount off the
  bill before tax and tip are figured.
- **Stacked coupons** — apply several coupons in order, each one coming off
  what's left: percentages compound and a flat amount is capped so the check
  never drops below zero, with a per-coupon breakdown of what each knocked off.
- **Service charge / auto-gratuity** — separate a mandatory service charge
  (common for large parties) from any additional voluntary tip, with both
  figured on the pre- or post-tax base.
- **Whole-dollar split** — round every person's share up to the next whole
  dollar for easy cash splitting; the surplus is folded into the tip.
- **Credit-card surcharge** — add a card-processing fee on top of the final
  post-tax, post-tip total, reported separately and split fairly.
- **Gift card / store credit** — redeem a pre-paid amount against the final
  total (tax and tip still figured on the full bill, unlike a discount); only
  the leftover balance is owed and split fairly, with any surplus reported as
  unused rather than silently lost.
- **Comp a diner** — cover one or more diners' meals; the comped seats pay
  nothing and the remaining diners split the whole bill fairly.
- **Tiered tip** — pick the tip percentage from a bill-size bracket table (e.g.
  ≤$50 → 18%, ≤$100 → 20%, above → 22%), then the usual tax + tip + fair split.
- **Who pays whom** — turn what each diner has already paid into the *fewest*
  diner-to-diner transfers that square everyone up (the "one friend covered the
  whole bill, now pay them back" case).
- **Server tip-out** — at close, distribute a server's collected tips to support
  staff (busser, bartender, runner, …) as a percent of either net sales (the
  common practice) or of the tips themselves; the server keeps the remainder,
  and tip-outs that exceed the tips collected are rejected.

## HTTP API

All endpoints accept and return JSON. Validation failures return `400` with an
`{"error": ...}` body.

| Method | Path             | Purpose                                            |
| ------ | ---------------- | -------------------------------------------------- |
| GET    | `/`              | the single-page UI                                 |
| GET    | `/api/health`    | `{"status": "ok"}`                                 |
| POST   | `/api/tip`       | tip + total + fair split                           |
| POST   | `/api/presets`   | tip suggestions at preset percentages              |
| POST   | `/api/bill`      | subtotal + tax + tip breakdown, fairly split       |
| POST   | `/api/split`     | full bill split by uneven `weights`                |
| POST   | `/api/recommend` | tip breakdown for a service-quality `rating`       |
| POST   | `/api/items`     | split a bill by each person's itemized order       |
| POST   | `/api/itemtips`  | each diner's own items AND own tip rate, split      |
| POST   | `/api/target`    | tip needed to reach a desired grand `target_total` |
| POST   | `/api/discount`  | apply a `%`/`$` discount, then tax + tip, split    |
| POST   | `/api/service`   | mandatory service charge + optional tip, split     |
| POST   | `/api/roundsplit`| round each person's share up to a whole dollar     |
| POST   | `/api/cardfee`   | add a credit-card surcharge on top of the total    |
| POST   | `/api/giftcard`  | redeem a gift card against the total, split the rest |
| POST   | `/api/comp`      | split a bill with some diners comped (covered)     |
| POST   | `/api/shareditems`| own items + evenly-split shared dishes, then tip   |
| POST   | `/api/assign`    | assign each item to the diners who shared it, then tip |
| POST   | `/api/category`  | tip each category (e.g. food vs bar) at its own rate |
| POST   | `/api/tiered`    | pick the tip % from a bill-size `brackets` table    |
| POST   | `/api/reconcile` | fewest transfers to settle who `paid` what          |
| POST   | `/api/coupons`   | stack a list of `coupons` (in order), then tax + tip, split |
| POST   | `/api/summary`   | aggregate several `bills` into a spend & tip report |
| POST   | `/api/tipout`    | distribute a server's tips to support staff, keep the rest |

Everything lives in `server.py` (domain logic + HTTP handler) and `index.html`
(UI); `test_app.py` covers the domain and the API surface.
