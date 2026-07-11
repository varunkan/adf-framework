# Loyalty Points Badge — Checkout

A self-contained web app that adds a **loyalty points badge** to a checkout screen.
Customers see their current points, badge tier (Bronze / Silver / Gold), can redeem
points for a discount, and see points they'll earn — all on the checkout page.

## Requirements

- Python 3 (standard library only). No pip installs.

## Run

```bash
python3 server.py
```

Then open http://localhost:8000

Override the port:

```bash
PORT=9000 python3 server.py
```

Data persists to `data.json` next to `server.py` (auto-created with sample customers
`alice`, `bob`, `guest`).

## Loyalty rules

- Earn **10 points per $1** of order total (after discount).
- Redeem **100 points for $1** off.
- Badge tiers: **Gold** ≥ 1000 pts, **Silver** ≥ 250 pts, **Bronze** ≥ 1 pt, else No tier.

## API

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET  | `/api/customers` | — | List customers with points + badge |
| GET  | `/api/loyalty/{id}` | — | Single customer loyalty (404 if missing) |
| POST | `/api/checkout/preview` | `{customer_id, subtotal, redeem_points?}` | Compute discount/total/badge (no write) → 200 |
| POST | `/api/checkout` | `{customer_id, subtotal, redeem_points?}` | Commit order, update points → 201 |
| GET  | `/api/tiers` | — | Badge tiers with perks + member counts |
| GET  | `/api/promos` | `?customerId=` | Promo codes (per-customer redeemed flag) |
| POST | `/api/customers/{id}/promo` | `{code}` | Redeem a one-shot promo code for bonus points |
| POST | `/api/customers/{id}/transfer` | `{toCustomerId, points}` | Gift points to another customer |
| GET  | `/api/tiers/{id}` | — | Single badge tier detail (case-insensitive, 404 if unknown) |
| GET  | `/api/estimate` | `?subtotal=&redeemPoints=` | Anonymous earn/discount preview (no customer) |
| GET  | `/api/codes/{code}` | — | Verify an issued reward/referral code → owning transaction |
| GET  | `/api/customers/{id}/wishlist` | — | Saved rewards with affordability + points-needed gap |
| POST | `/api/customers/{id}/wishlist` | `{rewardId}` | Save a catalog reward for later (idempotent) → 201 |
| POST | `/api/customers/{id}/wishlist/remove` | `{rewardId}` | Remove a reward from the wishlist |
| POST | `/api/customers/{id}/gift-reward` | `{toCustomerId, rewardId}` | Buy a catalog reward for another member; issues a `GFT-` voucher → 201 |
| GET  | `/api/customers/{id}/gifts` | — | Rewards this customer has gifted out and received |

Errors: `400` invalid input, `404` unknown customer.

## Promo codes & gifting

- **Promo codes** grant a one-time bonus to a customer (`WELCOME50`, `SUMMER100`,
  `VIP500`). Each code can be redeemed at most once per customer.
- **Gifting** transfers points from one customer to another, recording a
  `transfer-out` transaction for the sender and a `transfer-in` for the recipient.
- **Reward gifting** (`/api/customers/{id}/gift-reward`) spends the buyer's points
  on a catalog reward for *another* member: the buyer is charged the reward's cost,
  a verifiable `GFT-` voucher is issued to the recipient (who pays nothing), and the
  buyer's spend shows up in their statement just like a self-redemption. `/gifts`
  lists every reward a customer has sent and received.

## Wishlist, estimator & code verification

- **Wishlist** lets a customer save catalog rewards for later; the view flags
  which saved rewards are already affordable and how many more points the rest
  need. Saving the same reward twice is a no-op.
- **Estimator** (`/api/estimate`) does the earn/discount math for any order with
  no customer involved — handy for a "spend $X, earn Y points" hint.
- **Code verification** (`/api/codes/{code}`) looks up an issued reward (`RWD-`)
  or referral (`REF-`) confirmation code and returns the transaction it belongs
  to, so a voucher can be validated at checkout.

## Test

```bash
python3 test_app.py
```

All tests should pass with zero failures.
