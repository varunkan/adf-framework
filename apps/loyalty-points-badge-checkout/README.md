# loyalty-points-badge-checkout

A self-contained web app that adds a **loyalty points badge** to a checkout
screen. Built with Python standard library only (backend) and a single static
HTML file (frontend). No pip installs, no frameworks, no build step.

## Features (REQ-001)

- Loyalty points badge rendered on the checkout screen, color-coded by tier
  (Bronze / Silver / Gold / Platinum).
- Read-only loyalty lookup endpoint returns a customer's current balance,
  tier, redeemable value, and a ready-to-render badge label.
- Checkout endpoint that earns points (1 point per dollar) and returns the
  updated badge.

## Run

```
python3 server.py
```

Then open http://127.0.0.1:8000 in your browser.

The server prints a ready line and listens on port 8000 by default.

## Test

```
python3 test_app.py
```

All tests must pass with zero failures.

## API

### `GET /api/customers`
Returns the list of known customer ids.
```json
{ "customers": ["alice", "bob", "carol", "guest"] }
```

### `GET /api/loyalty/<customer_id>`
Returns the loyalty badge data for a customer.
- `200` with `{customer_id, points, tier, color, redeem_value_cents, badge_label}`
- `404` if the customer is unknown
- `400` if no customer id given

### `POST /api/checkout`
Body: `{"customer_id": "alice", "amount_cents": 4999}`
- `200` with `{points_earned, points_total, tier, color, badge_label, ...}`
- `400` invalid JSON, missing customer, or invalid amount
- `404` unknown customer

## Notes

- Loyalty data is stored in memory and resets when the server restarts.
- `make_server(port=0)` and `RequestHandler` are importable for tests.
