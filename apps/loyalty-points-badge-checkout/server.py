import os
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data.json")

POINTS_PER_DOLLAR = 10
REDEEM_RATE = 100  # 100 points = $1
REFERRAL_BONUS = 100  # points granted to BOTH parties when a referral signs up

# Daily check-in rewards. A streak grows by one each consecutive check-in and the
# bonus climbs with it (base + step per extra day) up to a cap, so returning
# members are rewarded for showing up repeatedly.
CHECKIN_BASE_BONUS = 10
CHECKIN_STEP = 5
CHECKIN_MAX_BONUS = 50


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (ValueError, OSError):
            pass
    return {"customers": {}}


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


_lock = threading.Lock()
_store = load_data()


def get_customer(cid):
    return _store["customers"].get(cid)


def ensure_customer(cid):
    c = _store["customers"].get(cid)
    if c is None:
        c = {"id": cid, "points": 0}
        _store["customers"][cid] = c
    return c


# Tier name -> minimum points to reach it (ascending order).
TIERS = [
    ("Bronze", 0),
    ("Silver", 500),
    ("Gold", 2000),
    ("Platinum", 5000),
]


def badge_label(points):
    if points >= 5000:
        return "Platinum"
    if points >= 2000:
        return "Gold"
    if points >= 500:
        return "Silver"
    return "Bronze"


def tier_progress(points):
    """Return (nextTier, pointsToNextTier) for a points balance.

    nextTier is None once the customer is at the top tier (Platinum)."""
    for name, threshold in TIERS:
        if points < threshold:
            return name, threshold - points
    return None, 0


def customer_summary(c):
    """Public view of a customer including badge + tier progress."""
    points = c["points"]
    nxt, to_next = tier_progress(points)
    return {
        "id": c["id"],
        "points": points,
        "tier": badge_label(points),
        "nextTier": nxt,
        "pointsToNextTier": to_next,
    }


def _txns():
    """Transaction log, created lazily so a freshly-reset store works."""
    return _store.setdefault("transactions", [])


def _next_seq():
    seq = _store.get("seq", 0) + 1
    _store["seq"] = seq
    return seq


def record_txn(cid, kind, fields):
    """Append a transaction record and return it."""
    txn = {"id": _next_seq(), "customerId": cid, "type": kind}
    txn.update(fields)
    _txns().append(txn)
    return txn


def max_redeemable(points, subtotal):
    """Most points worth applying to this order.

    Capped by the balance and by the order value (no point in redeeming
    more than the subtotal is worth)."""
    by_value = int(round(subtotal * REDEEM_RATE))
    return max(0, min(points, by_value))


def compute_checkout(points, subtotal, redeem):
    """Pure checkout math shared by preview and commit. No writes."""
    discount = round(redeem / REDEEM_RATE, 2)
    total = round(max(0.0, subtotal - discount), 2)
    earned = int(round(total * POINTS_PER_DOLLAR))
    balance = points - redeem + earned
    return {
        "subtotal": subtotal,
        "discount": discount,
        "total": total,
        "pointsRedeemed": redeem,
        "pointsEarned": earned,
        "pointsBalance": balance,
        "tier": badge_label(balance),
    }


def checkout_view(cid, subtotal):
    """Compute the loyalty badge view for a checkout screen."""
    c = ensure_customer(cid)
    points = c["points"]
    earn = int(round(subtotal * POINTS_PER_DOLLAR)) if subtotal > 0 else 0
    redeemable_value = round(points / REDEEM_RATE, 2)
    nxt, to_next = tier_progress(points)
    return {
        "customerId": cid,
        "points": points,
        "tier": badge_label(points),
        "nextTier": nxt,
        "pointsToNextTier": to_next,
        "subtotal": subtotal,
        "pointsToEarn": earn,
        "redeemableValue": redeemable_value,
        "maxRedeemablePoints": max_redeemable(points, subtotal),
        "redeemRate": REDEEM_RATE,
        "pointsPerDollar": POINTS_PER_DOLLAR,
    }


def loyalty_stats():
    """Aggregate view across all customers for an admin/overview screen."""
    customers = list(_store["customers"].values())
    total_points = sum(c["points"] for c in customers)
    tier_counts = {name: 0 for name, _ in TIERS}
    for c in customers:
        tier_counts[badge_label(c["points"])] += 1
    return {
        "customerCount": len(customers),
        "totalPoints": total_points,
        "tierCounts": tier_counts,
        "transactionCount": len(_txns()),
        "redeemableValue": round(total_points / REDEEM_RATE, 2),
    }


# ---------------------------------------------------------------------------
# Rewards catalog — fixed-cost perks a customer can redeem points for. This is
# distinct from redeeming points for a checkout discount: a reward is a named
# perk (voucher, freebie) bought outright with points and confirmed by a code.
# ---------------------------------------------------------------------------
REWARDS = [
    {"id": "free-shipping", "name": "Free Shipping", "cost": 150, "category": "shipping"},
    {"id": "coffee", "name": "Free Coffee", "cost": 300, "category": "food"},
    {"id": "voucher-5", "name": "$5 Voucher", "cost": 500, "category": "voucher"},
    {"id": "voucher-10", "name": "$10 Voucher", "cost": 1000, "category": "voucher"},
]


def reward_by_id(rid):
    for r in REWARDS:
        if r["id"] == rid:
            return r
    return None


def rewards_catalog(points=None, category=None):
    """Catalog view; optionally filtered by category and/or flagged for affordability."""
    out = []
    for r in REWARDS:
        if category is not None and r.get("category") != category:
            continue
        item = {"id": r["id"], "name": r["name"], "cost": r["cost"],
                "category": r.get("category")}
        if points is not None:
            item["affordable"] = points >= r["cost"]
        out.append(item)
    return out


def categories_view():
    """Distinct reward categories with how many rewards each contains."""
    counts = {}
    order = []
    for r in REWARDS:
        cat = r.get("category")
        if cat is None:
            continue
        if cat not in counts:
            counts[cat] = 0
            order.append(cat)
        counts[cat] += 1
    return [{"category": c, "count": counts[c]} for c in order]


def redemption_code(seq):
    """Deterministic confirmation code for a redeemed reward."""
    return "RWD-%05d" % seq


# ---------------------------------------------------------------------------
# Tier catalog — the badge thresholds plus a human-readable perk for each tier.
# This is the public, descriptive companion to the internal TIERS table and the
# aggregate tierCounts in loyalty_stats().
# ---------------------------------------------------------------------------
TIER_BENEFITS = {
    "Bronze": "Earn 10 points per $1 spent.",
    "Silver": "Bronze perks + early access to new rewards.",
    "Gold": "Silver perks + free shipping on every order.",
    "Platinum": "Gold perks + a dedicated concierge and birthday bonus.",
}


def tiers_view():
    """Descriptive list of every badge tier with its perk and member count."""
    counts = loyalty_stats()["tierCounts"]
    out = []
    for name, threshold in TIERS:
        out.append({
            "name": name,
            "minPoints": threshold,
            "benefit": TIER_BENEFITS.get(name, ""),
            "customerCount": counts.get(name, 0),
        })
    return out


# ---------------------------------------------------------------------------
# Promo codes — one-shot bonus-point grants. Each customer may redeem a given
# code at most once; the set of codes already used is tracked per customer.
# ---------------------------------------------------------------------------
PROMOS = [
    {"code": "WELCOME50", "bonus": 50},
    {"code": "SUMMER100", "bonus": 100},
    {"code": "VIP500", "bonus": 500},
]


def promo_by_code(code):
    for p in PROMOS:
        if p["code"] == code:
            return p
    return None


def _redeemed_promos(c):
    """Per-customer set of already-used promo codes (created lazily)."""
    return c.setdefault("redeemedPromos", [])


def promos_catalog(customer=None):
    """List promo codes; if a customer is given, flag which they've redeemed."""
    used = set(_redeemed_promos(customer)) if customer is not None else set()
    out = []
    for p in PROMOS:
        item = {"code": p["code"], "bonus": p["bonus"]}
        if customer is not None:
            item["redeemed"] = p["code"] in used
        out.append(item)
    return out


def leaderboard(limit=None):
    """Customers ranked by points (desc); ties keep insertion order stable."""
    ranked = sorted(
        _store["customers"].values(),
        key=lambda c: c["points"],
        reverse=True,
    )
    if limit is not None:
        ranked = ranked[:limit]
    rows = []
    for i, c in enumerate(ranked):
        rows.append({
            "rank": i + 1,
            "id": c["id"],
            "points": c["points"],
            "tier": badge_label(c["points"]),
        })
    return rows


TIER_NAMES = [name for name, _ in TIERS]


# ---------------------------------------------------------------------------
# Points goals — an optional per-customer savings target. Customers set a goal
# (e.g. "save 1000 points") and the API reports how close they are to it.
# ---------------------------------------------------------------------------
def goal_view(c):
    """Progress toward a customer's points goal (None if no goal is set)."""
    goal = c.get("goal")
    points = c["points"]
    if not goal:
        return {
            "customerId": c["id"],
            "goal": None,
            "points": points,
            "remaining": 0,
            "reached": False,
        }
    remaining = max(0, goal - points)
    return {
        "customerId": c["id"],
        "goal": goal,
        "points": points,
        "remaining": remaining,
        "reached": points >= goal,
    }


# ---------------------------------------------------------------------------
# Customer rank — a single customer's standing in the points leaderboard. This
# is the per-customer companion to the full leaderboard() listing.
# ---------------------------------------------------------------------------
def customer_rank(cid):
    """Return this customer's 1-based rank by points, or None if unknown.

    Ranking matches leaderboard(): points descending, ties broken by stable
    insertion order. The result also carries the total customer count so the
    caller can render "rank N of M"."""
    c = get_customer(cid)
    if c is None:
        return None
    ranked = sorted(
        _store["customers"].values(),
        key=lambda x: x["points"],
        reverse=True,
    )
    total = len(ranked)
    for i, other in enumerate(ranked):
        if other["id"] == cid:
            return {
                "customerId": cid,
                "rank": i + 1,
                "points": c["points"],
                "tier": badge_label(c["points"]),
                "totalCustomers": total,
            }
    return None


# ---------------------------------------------------------------------------
# Referrals — an existing member refers a brand-new customer. Both parties are
# granted REFERRAL_BONUS points. This finally puts the long-declared
# REFERRAL_BONUS to work: a member is rewarded for growing the program and the
# newcomer starts with a welcome balance.
# ---------------------------------------------------------------------------
def referral_code(seq):
    """Deterministic confirmation code for a completed referral."""
    return "REF-%05d" % seq


# ---------------------------------------------------------------------------
# Reward wishlist — a per-customer shortlist of catalog rewards the customer is
# saving up for. The view reports, for each saved reward, whether it is already
# affordable and how many more points are needed otherwise. This complements the
# rewards catalog (browse) and redemption (buy) with a "save for later" step.
# ---------------------------------------------------------------------------
def _wishlist(c):
    """Per-customer list of wished reward ids (created lazily)."""
    return c.setdefault("wishlist", [])


def wishlist_view(c):
    """Customer's wishlist with affordability + points-needed for each item.

    Unknown reward ids (e.g. a reward later removed from the catalog) are
    skipped so the view always reflects redeemable rewards."""
    points = c["points"]
    items = []
    for rid in _wishlist(c):
        r = reward_by_id(rid)
        if r is None:
            continue
        items.append({
            "id": r["id"],
            "name": r["name"],
            "cost": r["cost"],
            "affordable": points >= r["cost"],
            "pointsNeeded": max(0, r["cost"] - points),
        })
    return {
        "customerId": c["id"],
        "points": points,
        "wishlist": items,
        "count": len(items),
    }


# ---------------------------------------------------------------------------
# Code lookup — every issued reward (RWD-) and referral (REF-) confirmation code
# is stored on its transaction. This lets a clerk verify a voucher code presented
# at checkout and see which customer and reward it belongs to.
# ---------------------------------------------------------------------------
def find_by_code(code):
    """Return the transaction carrying this confirmation code, or None."""
    for t in _txns():
        if t.get("code") == code:
            return t
    return None


# ---------------------------------------------------------------------------
# Single tier detail — the per-tier companion to tiers_view(); looks a tier up by
# name (case-insensitive) and returns its threshold, perk, and member count.
# ---------------------------------------------------------------------------
def tier_by_name(name):
    """Return one tier's descriptive view by name, or None if unknown."""
    for t in tiers_view():
        if t["name"].lower() == name.lower():
            return t
    return None


# ---------------------------------------------------------------------------
# Points estimator — anonymous checkout math with no customer involved. Lets the
# UI show "spend $X, earn Y points" (and the discount for a given redemption)
# before anyone signs in. Pure: it never reads or writes the store.
# ---------------------------------------------------------------------------
def estimate_checkout(subtotal, redeem):
    """Earn/discount preview for an order, independent of any customer."""
    discount = round(redeem / REDEEM_RATE, 2)
    total = round(max(0.0, subtotal - discount), 2)
    earned = int(round(total * POINTS_PER_DOLLAR))
    return {
        "subtotal": subtotal,
        "discount": discount,
        "total": total,
        "pointsRedeemed": redeem,
        "pointsToEarn": earned,
        "redeemRate": REDEEM_RATE,
        "pointsPerDollar": POINTS_PER_DOLLAR,
    }


# ---------------------------------------------------------------------------
# Daily check-in streak — an engagement loop. Each check-in extends the member's
# streak by one and grants a bonus that grows with the streak (capped). This is a
# pure-points reward distinct from spending; it rewards habitual return visits.
# ---------------------------------------------------------------------------
def checkin_bonus(streak):
    """Bonus points for the Nth consecutive check-in (streak >= 1)."""
    if streak < 1:
        return 0
    return min(CHECKIN_BASE_BONUS + (streak - 1) * CHECKIN_STEP, CHECKIN_MAX_BONUS)


def streak_view(c):
    """Customer's current streak plus the bonus their NEXT check-in would grant."""
    streak = c.get("streak", 0)
    return {
        "customerId": c["id"],
        "streak": streak,
        "lastBonus": checkin_bonus(streak),       # what the latest check-in earned
        "nextBonus": checkin_bonus(streak + 1),   # what the next one will earn
        "maxBonus": CHECKIN_MAX_BONUS,
    }


# ---------------------------------------------------------------------------
# Points statement — a per-customer ledger summary derived from the transaction
# log. Each transaction contributes a signed points delta; the statement rolls
# these up into lifetime earned vs. redeemed totals and a per-type breakdown.
# ---------------------------------------------------------------------------
def txn_points_delta(t):
    """Signed points movement a single transaction represents (+earned/-spent)."""
    kind = t.get("type")
    if kind == "checkout":
        return t.get("pointsEarned", 0) - t.get("pointsRedeemed", 0)
    if kind in ("reward", "bundle", "gift-reward"):
        return -t.get("cost", 0)
    if kind == "gift-received":
        return 0  # a gifted voucher is a perk, not a points movement
    if kind in ("promo", "referral", "referral-bonus", "checkin"):
        return t.get("bonus", 0)
    if kind == "transfer-in":
        return t.get("points", 0)
    if kind == "transfer-out":
        return -t.get("points", 0)
    if kind in ("adjust", "refund"):
        return t.get("delta", 0)  # already signed
    return 0


def txn_earned_redeemed(t):
    """Split a transaction into (earned, redeemed) point amounts, both >= 0.

    Checkout is the one transaction that moves points in *both* directions at
    once (it can redeem points for a discount while earning points on the
    order), so its two legs are reported separately rather than netted. Every
    other transaction has a single signed movement, classified by its sign."""
    if t.get("type") == "checkout":
        return t.get("pointsEarned", 0), t.get("pointsRedeemed", 0)
    delta = txn_points_delta(t)
    return (delta, 0) if delta >= 0 else (0, -delta)


def statement_view(cid):
    """Lifetime earned/redeemed rollup and per-type counts for a customer."""
    c = get_customer(cid)
    if c is None:
        return None
    earned = 0
    redeemed = 0
    counts = {}
    txns = [t for t in _txns() if t["customerId"] == cid]
    for t in txns:
        e, r = txn_earned_redeemed(t)
        earned += e
        redeemed += r
        counts[t["type"]] = counts.get(t["type"], 0) + 1
    return {
        "customerId": cid,
        "transactionCount": len(txns),
        "totalEarned": earned,
        "totalRedeemed": redeemed,
        "net": earned - redeemed,
        "countsByType": counts,
        "pointsBalance": c["points"],
        "tier": badge_label(c["points"]),
    }


# ---------------------------------------------------------------------------
# Next-tier target — how far a customer is from their next badge, expressed both
# in points and in the dollars they'd need to spend to earn them. The per-customer
# companion to tier_progress(), surfaced as its own endpoint for a "spend $X more
# to reach Gold" nudge at checkout.
# ---------------------------------------------------------------------------
def next_tier_view(c):
    points = c["points"]
    nxt, to_next = tier_progress(points)
    at_top = nxt is None
    dollars = 0.0 if at_top else round(to_next / POINTS_PER_DOLLAR, 2)
    return {
        "customerId": c["id"],
        "points": points,
        "tier": badge_label(points),
        "nextTier": nxt,
        "pointsToNextTier": to_next,
        "dollarsToSpend": dollars,
        "atTopTier": at_top,
    }


# ---------------------------------------------------------------------------
# Achievements — derived milestone badges a customer unlocks purely from their
# history (transaction log + current state). Unlike tiers, which track the live
# points balance and can go *down* when points are spent, an achievement is a
# permanent, earned-once recognition of a behaviour (first purchase, a long
# streak, gifting, referring, etc.). This reads the existing transaction log and
# never writes, so it composes with every flow already in the program.
# ---------------------------------------------------------------------------
BIG_SPENDER_THRESHOLD = 100.0   # lifetime dollars spent across checkouts
HIGH_ROLLER_THRESHOLD = 1000    # lifetime points earned
STREAK_MASTER_DAYS = 7          # consecutive check-in streak

ACHIEVEMENTS = [
    {"id": "first-purchase", "name": "First Purchase",
     "description": "Complete your first checkout."},
    {"id": "big-spender", "name": "Big Spender",
     "description": "Spend $%g or more in total." % BIG_SPENDER_THRESHOLD},
    {"id": "high-roller", "name": "High Roller",
     "description": "Earn %d or more points in your lifetime." % HIGH_ROLLER_THRESHOLD},
    {"id": "collector", "name": "Collector",
     "description": "Redeem at least one catalog reward."},
    {"id": "streak-master", "name": "Streak Master",
     "description": "Reach a %d-day check-in streak." % STREAK_MASTER_DAYS},
    {"id": "philanthropist", "name": "Philanthropist",
     "description": "Gift points to another member."},
    {"id": "recruiter", "name": "Recruiter",
     "description": "Refer a new member to the program."},
    {"id": "goal-getter", "name": "Goal Getter",
     "description": "Reach a points savings goal you set."},
    {"id": "top-tier", "name": "Top Tier",
     "description": "Reach the Platinum badge tier."},
]

ACHIEVEMENT_IDS = [a["id"] for a in ACHIEVEMENTS]


def achievement_profile(cid):
    """Derived metrics behind achievement unlocks, or None if customer unknown."""
    c = get_customer(cid)
    if c is None:
        return None
    txns = [t for t in _txns() if t["customerId"] == cid]
    checkouts = [t for t in txns if t["type"] == "checkout"]
    total_spend = round(sum(t.get("subtotal", 0) for t in checkouts), 2)
    lifetime_earned = sum(txn_earned_redeemed(t)[0] for t in txns)
    goal = c.get("goal")
    return {
        "customerId": cid,
        "checkoutCount": len(checkouts),
        "totalSpend": total_spend,
        "lifetimeEarned": lifetime_earned,
        "rewardsRedeemed": sum(1 for t in txns if t["type"] == "reward"),
        "transfersOut": sum(1 for t in txns if t["type"] == "transfer-out"),
        "referrals": sum(1 for t in txns if t["type"] == "referral"),
        "streak": c.get("streak", 0),
        "points": c["points"],
        "tier": badge_label(c["points"]),
        "goalReached": bool(goal) and c["points"] >= goal,
    }


def _achievement_unlocked(aid, p):
    """Whether achievement `aid` is unlocked for profile `p`."""
    if aid == "first-purchase":
        return p["checkoutCount"] >= 1
    if aid == "big-spender":
        return p["totalSpend"] >= BIG_SPENDER_THRESHOLD
    if aid == "high-roller":
        return p["lifetimeEarned"] >= HIGH_ROLLER_THRESHOLD
    if aid == "collector":
        return p["rewardsRedeemed"] >= 1
    if aid == "streak-master":
        return p["streak"] >= STREAK_MASTER_DAYS
    if aid == "philanthropist":
        return p["transfersOut"] >= 1
    if aid == "recruiter":
        return p["referrals"] >= 1
    if aid == "goal-getter":
        return p["goalReached"]
    if aid == "top-tier":
        return p["tier"] == "Platinum"
    return False


def achievements_catalog():
    """The full list of achievements with their definitions (no customer)."""
    return [dict(a) for a in ACHIEVEMENTS]


def achievements_view(cid):
    """Per-customer achievement board: each badge flagged unlocked/locked."""
    p = achievement_profile(cid)
    if p is None:
        return None
    items = []
    unlocked = 0
    for a in ACHIEVEMENTS:
        got = _achievement_unlocked(a["id"], p)
        if got:
            unlocked += 1
        item = dict(a)
        item["unlocked"] = got
        items.append(item)
    return {
        "customerId": cid,
        "achievements": items,
        "unlockedCount": unlocked,
        "totalCount": len(ACHIEVEMENTS),
        "profile": p,
    }


# ---------------------------------------------------------------------------
# Cart checkout — checkout from a list of line items instead of a pre-summed
# subtotal. The cart is validated and totalled here, then the resulting subtotal
# flows through the exact same checkout math (compute_checkout) and transaction
# log as the plain /api/checkout, so points, badges, statements and refunds all
# behave identically. The committed transaction additionally records the line
# items for the receipt.
# ---------------------------------------------------------------------------
def normalize_cart(items):
    """Validate cart line items and total them.

    Returns (lines, subtotal); each line is {name, price, qty, lineTotal}.
    Raises ValueError(message) on any invalid input."""
    if not isinstance(items, list) or len(items) == 0:
        raise ValueError("items must be a non-empty list")
    lines = []
    subtotal = 0.0
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError("each item must be an object")
        price = it.get("price", None)
        if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
            raise ValueError("item price must be a non-negative number")
        qty = it.get("qty", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise ValueError("item qty must be a positive integer")
        name = str(it.get("name", "")).strip() or ("item-%d" % (idx + 1))
        line_total = round(price * qty, 2)
        subtotal = round(subtotal + line_total, 2)
        lines.append({
            "name": name,
            "price": round(float(price), 2),
            "qty": qty,
            "lineTotal": line_total,
        })
    return lines, subtotal


# ---------------------------------------------------------------------------
# Reward bundles — curated sets of catalog rewards sold together for a single
# points price that is cheaper than buying each reward outright. A bundle is the
# "buy the set, save points" companion to the single-reward catalog: it reuses
# the same reward definitions (so a bundle's contents and savings stay in sync
# with the catalog) and, when redeemed, deducts points and issues a verifiable
# BND- confirmation code exactly like a single reward redemption.
# ---------------------------------------------------------------------------
BUNDLES = [
    {"id": "starter", "name": "Starter Pack",
     "rewardIds": ["free-shipping", "coffee"], "cost": 400},
    {"id": "value", "name": "Value Pack",
     "rewardIds": ["coffee", "voucher-5"], "cost": 700},
    {"id": "premium", "name": "Premium Pack",
     "rewardIds": ["voucher-5", "voucher-10", "free-shipping"], "cost": 1500},
]


def bundle_by_id(bid):
    for b in BUNDLES:
        if b["id"] == bid:
            return b
    return None


def bundle_full_cost(b):
    """Combined cost of buying the bundle's rewards individually.

    Unknown reward ids contribute nothing, so a bundle stays well-defined even
    if a reward is later pulled from the catalog."""
    total = 0
    for rid in b["rewardIds"]:
        r = reward_by_id(rid)
        if r is not None:
            total += r["cost"]
    return total


def bundle_view(b, points=None, expand=False):
    """Public view of a bundle: its price, what it would cost à la carte, and
    the points saved. With expand=True the contained rewards are listed in full;
    with points given the bundle is flagged affordable/unaffordable."""
    full = bundle_full_cost(b)
    item = {
        "id": b["id"],
        "name": b["name"],
        "cost": b["cost"],
        "rewardIds": list(b["rewardIds"]),
        "rewardCount": len(b["rewardIds"]),
        "fullCost": full,
        "savings": full - b["cost"],
    }
    if expand:
        rewards = []
        for rid in b["rewardIds"]:
            r = reward_by_id(rid)
            if r is not None:
                rewards.append({"id": r["id"], "name": r["name"],
                                "cost": r["cost"], "category": r.get("category")})
        item["rewards"] = rewards
    if points is not None:
        item["affordable"] = points >= b["cost"]
        item["pointsNeeded"] = max(0, b["cost"] - points)
    return item


def bundles_catalog(points=None):
    """Catalog of every bundle, optionally flagged for affordability."""
    return [bundle_view(b, points=points) for b in BUNDLES]


def bundle_code(seq):
    """Deterministic confirmation code for a redeemed bundle."""
    return "BND-%05d" % seq


# ---------------------------------------------------------------------------
# Reward gifting — buy a catalog reward *for another member*. This is the
# meeting point of the two existing flows: like /redeem it spends the buyer's
# points on a named reward, and like /transfer the benefit lands on a second
# customer. The buyer is charged the reward's points cost and a verifiable GFT-
# voucher is issued to the recipient (who pays nothing). It reuses the reward
# catalog, the transaction log, statement math and code verification, so a
# gifted voucher behaves exactly like a self-redeemed one at the till.
# ---------------------------------------------------------------------------
def gift_code(seq):
    """Deterministic confirmation code for a gifted reward voucher."""
    return "GFT-%05d" % seq


def gifts_view(cid):
    """Rewards this customer has gifted out and received, or None if unknown.

    Derived purely from the transaction log: a `gift-reward` txn is one the
    customer sent (they paid the points), a `gift-received` txn is one they
    were given. Newest first, matching the /transactions ordering."""
    if get_customer(cid) is None:
        return None
    sent = []
    received = []
    for t in _txns():
        if t["customerId"] != cid:
            continue
        if t["type"] == "gift-reward":
            sent.append({
                "rewardId": t.get("rewardId"),
                "rewardName": t.get("rewardName"),
                "cost": t.get("cost"),
                "toCustomerId": t.get("toCustomerId"),
                "code": t.get("code"),
                "transactionId": t["id"],
            })
        elif t["type"] == "gift-received":
            received.append({
                "rewardId": t.get("rewardId"),
                "rewardName": t.get("rewardName"),
                "fromCustomerId": t.get("fromCustomerId"),
                "code": t.get("code"),
                "transactionId": t["id"],
            })
    sent.sort(key=lambda g: g["transactionId"], reverse=True)
    received.sort(key=lambda g: g["transactionId"], reverse=True)
    return {
        "customerId": cid,
        "sent": sent,
        "received": received,
        "sentCount": len(sent),
        "receivedCount": len(received),
    }


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "LoyaltyBadge/1.0"

    def log_message(self, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # ---------- routing ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        query = {}
        if "?" in self.path:
            from urllib.parse import parse_qs
            query = parse_qs(self.path.split("?", 1)[1])

        if path == "/" or path == "":
            try:
                with open(os.path.join(HERE, "index.html"), "r") as f:
                    self._send_html(200, f.read())
            except OSError:
                self._send_html(500, "<h1>index.html missing</h1>")
            return

        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return

        # GET /api/stats -> aggregate loyalty overview
        if path == "/api/stats":
            self._send_json(200, loyalty_stats())
            return

        # GET /api/estimate?subtotal=..&redeemPoints=.. -> anonymous earn/discount preview
        if path == "/api/estimate":
            sub_raw = (query.get("subtotal") or ["0"])[0]
            try:
                subtotal = float(sub_raw)
            except ValueError:
                self._send_json(400, {"error": "subtotal must be a number"})
                return
            if subtotal < 0:
                self._send_json(400, {"error": "subtotal must be >= 0"})
                return
            redeem_raw = (query.get("redeemPoints") or ["0"])[0]
            try:
                redeem = int(redeem_raw)
            except ValueError:
                self._send_json(400, {"error": "redeemPoints must be an integer"})
                return
            if redeem < 0:
                self._send_json(400, {"error": "redeemPoints must be >= 0"})
                return
            self._send_json(200, estimate_checkout(subtotal, redeem))
            return

        # GET /api/codes/<code> -> verify an issued reward/referral confirmation code
        if path.startswith("/api/codes/"):
            code = path[len("/api/codes/"):]
            if not code:
                self._send_json(400, {"error": "code required"})
                return
            txn = find_by_code(code)
            if txn is None:
                self._send_json(404, {"error": "code not found"})
                return
            self._send_json(200, {"code": code, "valid": True, "transaction": txn})
            return

        # GET /api/tiers -> descriptive badge tiers with perks + member counts
        if path == "/api/tiers":
            tiers = tiers_view()
            self._send_json(200, {"tiers": tiers, "count": len(tiers)})
            return

        # GET /api/tiers/<name> -> a single tier's detail (404 if unknown)
        if path.startswith("/api/tiers/"):
            name = path[len("/api/tiers/"):]
            tier = tier_by_name(name)
            if tier is None:
                self._send_json(404, {"error": "tier not found",
                                      "validTiers": TIER_NAMES})
                return
            self._send_json(200, tier)
            return

        # GET /api/promos[?customerId=..] -> promo codes (redeemed flag if customer given)
        if path == "/api/promos":
            cid = (query.get("customerId") or [""])[0]
            customer = None
            if cid:
                customer = get_customer(cid)
                if customer is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
            promos = promos_catalog(customer)
            resp = {"promos": promos, "count": len(promos)}
            if cid:
                resp["customerId"] = cid
            self._send_json(200, resp)
            return

        # GET /api/achievements -> full catalog of milestone badges
        if path == "/api/achievements":
            cat = achievements_catalog()
            self._send_json(200, {"achievements": cat, "count": len(cat)})
            return

        # GET /api/categories -> distinct reward categories with counts
        if path == "/api/categories":
            cats = categories_view()
            self._send_json(200, {"categories": cats, "count": len(cats)})
            return

        # GET /api/bundles[?customerId=..] -> curated reward bundles (affordable flag if customer)
        if path == "/api/bundles":
            cid = (query.get("customerId") or [""])[0]
            points = None
            if cid:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                points = c["points"]
            bundles = bundles_catalog(points)
            resp = {"bundles": bundles, "count": len(bundles)}
            if cid:
                resp["customerId"] = cid
                resp["points"] = points
            self._send_json(200, resp)
            return

        # GET /api/bundles/<id> -> a single bundle's detail (404 if unknown)
        if path.startswith("/api/bundles/"):
            bid = path[len("/api/bundles/"):]
            bundle = bundle_by_id(bid)
            if bundle is None:
                self._send_json(404, {"error": "bundle not found"})
                return
            self._send_json(200, bundle_view(bundle, expand=True))
            return

        # GET /api/rewards[?customerId=..][&category=..] -> catalog
        if path == "/api/rewards":
            cid = (query.get("customerId") or [""])[0]
            category = (query.get("category") or [""])[0] or None
            points = None
            if cid:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                points = c["points"]
            rewards = rewards_catalog(points, category)
            resp = {"rewards": rewards, "count": len(rewards)}
            if cid:
                resp["customerId"] = cid
                resp["points"] = points
            if category:
                resp["category"] = category
            self._send_json(200, resp)
            return

        # GET /api/rewards/<id> -> a single reward's detail (404 if unknown)
        if path.startswith("/api/rewards/"):
            rid = path[len("/api/rewards/"):]
            reward = reward_by_id(rid)
            if reward is None:
                self._send_json(404, {"error": "reward not found"})
                return
            self._send_json(200, {"id": reward["id"], "name": reward["name"],
                                  "cost": reward["cost"],
                                  "category": reward.get("category")})
            return

        # GET /api/leaderboard[?limit=N] -> customers ranked by points
        if path == "/api/leaderboard":
            limit = None
            raw = (query.get("limit") or [""])[0]
            if raw:
                try:
                    limit = int(raw)
                except ValueError:
                    self._send_json(400, {"error": "limit must be an integer"})
                    return
                if limit < 0:
                    self._send_json(400, {"error": "limit must be >= 0"})
                    return
            rows = leaderboard(limit)
            self._send_json(200, {"leaderboard": rows, "count": len(rows)})
            return

        # GET /api/customers[?tier=Gold] -> list customers (optionally one tier)
        if path == "/api/customers":
            tier = (query.get("tier") or [""])[0]
            if tier and tier not in TIER_NAMES:
                self._send_json(400, {"error": "unknown tier",
                                      "validTiers": TIER_NAMES})
                return
            customers = [customer_summary(c) for c in _store["customers"].values()]
            if tier:
                customers = [c for c in customers if c["tier"] == tier]
            customers.sort(key=lambda x: x["points"], reverse=True)
            resp = {"customers": customers, "count": len(customers)}
            if tier:
                resp["tier"] = tier
            self._send_json(200, resp)
            return

        # GET /api/customers/<id>[/transactions]
        if path.startswith("/api/customers/"):
            rest = path[len("/api/customers/"):]
            if not rest:
                self._send_json(400, {"error": "customer id required"})
                return
            if rest.endswith("/goal"):
                cid = rest[:-len("/goal")]
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, goal_view(c))
                return
            if rest.endswith("/rank"):
                cid = rest[:-len("/rank")]
                rank = customer_rank(cid)
                if rank is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, rank)
                return
            if rest.endswith("/streak"):
                cid = rest[:-len("/streak")]
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, streak_view(c))
                return
            if rest.endswith("/statement"):
                cid = rest[:-len("/statement")]
                stmt = statement_view(cid)
                if stmt is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, stmt)
                return
            if rest.endswith("/achievements"):
                cid = rest[:-len("/achievements")]
                view = achievements_view(cid)
                if view is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, view)
                return
            if rest.endswith("/next-tier"):
                cid = rest[:-len("/next-tier")]
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, next_tier_view(c))
                return
            if rest.endswith("/wishlist"):
                cid = rest[:-len("/wishlist")]
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, wishlist_view(c))
                return
            if rest.endswith("/gifts"):
                cid = rest[:-len("/gifts")]
                view = gifts_view(cid)
                if view is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                self._send_json(200, view)
                return
            if rest.endswith("/transactions"):
                cid = rest[:-len("/transactions")]
                if get_customer(cid) is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                txns = [t for t in _txns() if t["customerId"] == cid]
                kind = (query.get("type") or [""])[0]
                if kind:
                    txns = [t for t in txns if t["type"] == kind]
                txns.sort(key=lambda t: t["id"], reverse=True)
                self._send_json(200, {"customerId": cid, "transactions": txns,
                                      "count": len(txns)})
                return
            cid = rest
            c = get_customer(cid)
            if c is None:
                self._send_json(404, {"error": "customer not found"})
                return
            self._send_json(200, customer_summary(c))
            return

        # GET /api/checkout/badge?customerId=..&subtotal=..
        if path == "/api/checkout/badge":
            cid = (query.get("customerId") or [""])[0]
            if not cid:
                self._send_json(400, {"error": "customerId is required"})
                return
            sub_raw = (query.get("subtotal") or ["0"])[0]
            try:
                subtotal = float(sub_raw)
            except ValueError:
                self._send_json(400, {"error": "subtotal must be a number"})
                return
            if subtotal < 0:
                self._send_json(400, {"error": "subtotal must be >= 0"})
                return
            with _lock:
                view = checkout_view(cid, subtotal)
                save_data(_store)
            self._send_json(200, view)
            return

        self._send_json(404, {"error": "route not found", "path": path})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        # POST /api/customers  -> create/upsert with optional starting points
        if path == "/api/customers":
            cid = str(data.get("id", "")).strip()
            if not cid:
                self._send_json(400, {"error": "id is required"})
                return
            pts = data.get("points", 0)
            if not isinstance(pts, (int, float)) or pts < 0:
                self._send_json(400, {"error": "points must be a non-negative number"})
                return
            with _lock:
                c = ensure_customer(cid)
                c["points"] = int(pts)
                save_data(_store)
            self._send_json(201, {"id": c["id"], "points": c["points"],
                                  "tier": badge_label(c["points"])})
            return

        # POST /api/customers/<id>/adjust -> manual points grant/correction
        if path.startswith("/api/customers/") and path.endswith("/adjust"):
            cid = path[len("/api/customers/"):-len("/adjust")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            delta = data.get("delta", None)
            if not isinstance(delta, (int, float)) or isinstance(delta, bool):
                self._send_json(400, {"error": "delta must be a number"})
                return
            delta = int(delta)
            reason = str(data.get("reason", "")).strip() or "manual adjustment"
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                before = c["points"]
                after = max(0, before + delta)
                applied = after - before  # honours the >= 0 clamp
                c["points"] = after
                txn = record_txn(cid, "adjust", {
                    "delta": applied,
                    "reason": reason,
                    "pointsBalance": after,
                })
                save_data(_store)
            self._send_json(200, {
                "customerId": cid,
                "delta": applied,
                "reason": reason,
                "pointsBalance": after,
                "tier": badge_label(after),
                "transactionId": txn["id"],
            })
            return

        # POST /api/customers/<id>/checkin -> daily check-in; grows streak + grants bonus
        if path.startswith("/api/customers/") and path.endswith("/checkin"):
            cid = path[len("/api/customers/"):-len("/checkin")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                streak = c.get("streak", 0) + 1
                c["streak"] = streak
                bonus = checkin_bonus(streak)
                c["points"] += bonus
                txn = record_txn(cid, "checkin", {
                    "streak": streak,
                    "bonus": bonus,
                    "pointsBalance": c["points"],
                })
                save_data(_store)
            self._send_json(200, {
                "customerId": cid,
                "streak": streak,
                "bonus": bonus,
                "nextBonus": checkin_bonus(streak + 1),
                "pointsBalance": c["points"],
                "tier": badge_label(c["points"]),
                "transactionId": txn["id"],
            })
            return

        # POST /api/customers/<id>/redeem -> spend points on a catalog reward
        if path.startswith("/api/customers/") and path.endswith("/redeem"):
            cid = path[len("/api/customers/"):-len("/redeem")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            rid = str(data.get("rewardId", "")).strip()
            if not rid:
                self._send_json(400, {"error": "rewardId is required"})
                return
            reward = reward_by_id(rid)
            if reward is None:
                self._send_json(404, {"error": "reward not found"})
                return
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                if c["points"] < reward["cost"]:
                    self._send_json(400, {"error": "not enough points for this reward"})
                    return
                c["points"] -= reward["cost"]
                txn = record_txn(cid, "reward", {
                    "rewardId": reward["id"],
                    "rewardName": reward["name"],
                    "cost": reward["cost"],
                    "pointsBalance": c["points"],
                })
                txn["code"] = redemption_code(txn["id"])
                save_data(_store)
            self._send_json(200, {
                "customerId": cid,
                "rewardId": reward["id"],
                "rewardName": reward["name"],
                "cost": reward["cost"],
                "code": txn["code"],
                "pointsBalance": c["points"],
                "tier": badge_label(c["points"]),
                "transactionId": txn["id"],
            })
            return

        # POST /api/customers/<id>/redeem-bundle -> buy a curated reward bundle with points
        if path.startswith("/api/customers/") and path.endswith("/redeem-bundle"):
            cid = path[len("/api/customers/"):-len("/redeem-bundle")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            bid = str(data.get("bundleId", "")).strip()
            if not bid:
                self._send_json(400, {"error": "bundleId is required"})
                return
            bundle = bundle_by_id(bid)
            if bundle is None:
                self._send_json(404, {"error": "bundle not found"})
                return
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                if c["points"] < bundle["cost"]:
                    self._send_json(400, {"error": "not enough points for this bundle"})
                    return
                c["points"] -= bundle["cost"]
                txn = record_txn(cid, "bundle", {
                    "bundleId": bundle["id"],
                    "bundleName": bundle["name"],
                    "rewardIds": list(bundle["rewardIds"]),
                    "cost": bundle["cost"],
                    "pointsBalance": c["points"],
                })
                txn["code"] = bundle_code(txn["id"])
                save_data(_store)
            self._send_json(200, {
                "customerId": cid,
                "bundleId": bundle["id"],
                "bundleName": bundle["name"],
                "rewardIds": list(bundle["rewardIds"]),
                "cost": bundle["cost"],
                "code": txn["code"],
                "pointsBalance": c["points"],
                "tier": badge_label(c["points"]),
                "transactionId": txn["id"],
            })
            return

        # POST /api/customers/<id>/transfer -> gift points to another customer
        if path.startswith("/api/customers/") and path.endswith("/transfer"):
            cid = path[len("/api/customers/"):-len("/transfer")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            to_cid = str(data.get("toCustomerId", "")).strip()
            if not to_cid:
                self._send_json(400, {"error": "toCustomerId is required"})
                return
            if to_cid == cid:
                self._send_json(400, {"error": "cannot transfer points to self"})
                return
            pts = data.get("points", None)
            if not isinstance(pts, (int, float)) or isinstance(pts, bool) or pts <= 0:
                self._send_json(400, {"error": "points must be a positive number"})
                return
            pts = int(pts)
            with _lock:
                sender = get_customer(cid)
                if sender is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                recipient = get_customer(to_cid)
                if recipient is None:
                    self._send_json(404, {"error": "recipient not found"})
                    return
                if sender["points"] < pts:
                    self._send_json(400, {"error": "not enough points to transfer"})
                    return
                sender["points"] -= pts
                recipient["points"] += pts
                out_txn = record_txn(cid, "transfer-out", {
                    "toCustomerId": to_cid,
                    "points": pts,
                    "pointsBalance": sender["points"],
                })
                in_txn = record_txn(to_cid, "transfer-in", {
                    "fromCustomerId": cid,
                    "points": pts,
                    "pointsBalance": recipient["points"],
                })
                save_data(_store)
            self._send_json(200, {
                "customerId": cid,
                "toCustomerId": to_cid,
                "points": pts,
                "pointsBalance": sender["points"],
                "tier": badge_label(sender["points"]),
                "recipientBalance": recipient["points"],
                "transactionId": out_txn["id"],
                "recipientTransactionId": in_txn["id"],
            })
            return

        # POST /api/customers/<id>/gift-reward -> buy a catalog reward FOR another member
        if path.startswith("/api/customers/") and path.endswith("/gift-reward"):
            cid = path[len("/api/customers/"):-len("/gift-reward")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            to_cid = str(data.get("toCustomerId", "")).strip()
            if not to_cid:
                self._send_json(400, {"error": "toCustomerId is required"})
                return
            if to_cid == cid:
                self._send_json(400, {"error": "cannot gift a reward to self"})
                return
            rid = str(data.get("rewardId", "")).strip()
            if not rid:
                self._send_json(400, {"error": "rewardId is required"})
                return
            reward = reward_by_id(rid)
            if reward is None:
                self._send_json(404, {"error": "reward not found"})
                return
            with _lock:
                sender = get_customer(cid)
                if sender is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                recipient = get_customer(to_cid)
                if recipient is None:
                    self._send_json(404, {"error": "recipient not found"})
                    return
                if sender["points"] < reward["cost"]:
                    self._send_json(400, {"error": "not enough points for this reward"})
                    return
                sender["points"] -= reward["cost"]
                out_txn = record_txn(cid, "gift-reward", {
                    "rewardId": reward["id"],
                    "rewardName": reward["name"],
                    "cost": reward["cost"],
                    "toCustomerId": to_cid,
                    "pointsBalance": sender["points"],
                })
                out_txn["code"] = gift_code(out_txn["id"])
                # The recipient's voucher carries the SAME code so either party
                # can present it; the buyer's txn is the one that holds the code
                # for /api/codes verification (it is recorded first).
                in_txn = record_txn(to_cid, "gift-received", {
                    "rewardId": reward["id"],
                    "rewardName": reward["name"],
                    "fromCustomerId": cid,
                    "code": out_txn["code"],
                    "pointsBalance": recipient["points"],
                })
                save_data(_store)
            self._send_json(201, {
                "customerId": cid,
                "toCustomerId": to_cid,
                "rewardId": reward["id"],
                "rewardName": reward["name"],
                "cost": reward["cost"],
                "code": out_txn["code"],
                "pointsBalance": sender["points"],
                "tier": badge_label(sender["points"]),
                "recipientBalance": recipient["points"],
                "transactionId": out_txn["id"],
                "recipientTransactionId": in_txn["id"],
            })
            return

        # POST /api/customers/<id>/promo -> redeem a one-shot promo code for points
        if path.startswith("/api/customers/") and path.endswith("/promo"):
            cid = path[len("/api/customers/"):-len("/promo")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            code = str(data.get("code", "")).strip()
            if not code:
                self._send_json(400, {"error": "code is required"})
                return
            promo = promo_by_code(code)
            if promo is None:
                self._send_json(404, {"error": "promo code not found"})
                return
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                used = _redeemed_promos(c)
                if promo["code"] in used:
                    self._send_json(400, {"error": "promo code already redeemed"})
                    return
                c["points"] += promo["bonus"]
                used.append(promo["code"])
                txn = record_txn(cid, "promo", {
                    "code": promo["code"],
                    "bonus": promo["bonus"],
                    "pointsBalance": c["points"],
                })
                save_data(_store)
            self._send_json(200, {
                "customerId": cid,
                "code": promo["code"],
                "bonus": promo["bonus"],
                "pointsBalance": c["points"],
                "tier": badge_label(c["points"]),
                "transactionId": txn["id"],
            })
            return

        # POST /api/customers/<id>/goal -> set or clear a points savings goal
        if path.startswith("/api/customers/") and path.endswith("/goal"):
            cid = path[len("/api/customers/"):-len("/goal")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            goal = data.get("goal", None)
            # null/0 clears the goal; otherwise it must be a positive integer.
            if goal is not None:
                if not isinstance(goal, (int, float)) or isinstance(goal, bool) or goal < 0:
                    self._send_json(400, {"error": "goal must be a non-negative number"})
                    return
                goal = int(goal)
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                if not goal:  # None or 0 -> clear any existing goal
                    c.pop("goal", None)
                else:
                    c["goal"] = goal
                view = goal_view(c)
                save_data(_store)
            self._send_json(200, view)
            return

        # POST /api/customers/<id>/refer -> refer a brand-new customer; both get a bonus
        if path.startswith("/api/customers/") and path.endswith("/refer"):
            cid = path[len("/api/customers/"):-len("/refer")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            new_cid = str(data.get("newCustomerId", "")).strip()
            if not new_cid:
                self._send_json(400, {"error": "newCustomerId is required"})
                return
            if new_cid == cid:
                self._send_json(400, {"error": "cannot refer yourself"})
                return
            with _lock:
                referrer = get_customer(cid)
                if referrer is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                if get_customer(new_cid) is not None:
                    self._send_json(400, {"error": "referred customer already exists"})
                    return
                # Create the newcomer and reward BOTH parties.
                newcomer = ensure_customer(new_cid)
                newcomer["referredBy"] = cid
                referrer["points"] += REFERRAL_BONUS
                newcomer["points"] += REFERRAL_BONUS
                ref_txn = record_txn(cid, "referral", {
                    "referredCustomerId": new_cid,
                    "bonus": REFERRAL_BONUS,
                    "pointsBalance": referrer["points"],
                })
                ref_txn["code"] = referral_code(ref_txn["id"])
                new_txn = record_txn(new_cid, "referral-bonus", {
                    "referredBy": cid,
                    "bonus": REFERRAL_BONUS,
                    "pointsBalance": newcomer["points"],
                })
                save_data(_store)
            self._send_json(201, {
                "customerId": cid,
                "newCustomerId": new_cid,
                "bonus": REFERRAL_BONUS,
                "code": ref_txn["code"],
                "pointsBalance": referrer["points"],
                "tier": badge_label(referrer["points"]),
                "newCustomerBalance": newcomer["points"],
                "transactionId": ref_txn["id"],
                "newCustomerTransactionId": new_txn["id"],
            })
            return

        # POST /api/customers/<id>/wishlist/remove -> drop a reward from the wishlist
        if path.startswith("/api/customers/") and path.endswith("/wishlist/remove"):
            cid = path[len("/api/customers/"):-len("/wishlist/remove")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            rid = str(data.get("rewardId", "")).strip()
            if not rid:
                self._send_json(400, {"error": "rewardId is required"})
                return
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                wl = _wishlist(c)
                if rid in wl:
                    wl.remove(rid)
                view = wishlist_view(c)
                save_data(_store)
            self._send_json(200, view)
            return

        # POST /api/customers/<id>/wishlist -> save a catalog reward for later
        if path.startswith("/api/customers/") and path.endswith("/wishlist"):
            cid = path[len("/api/customers/"):-len("/wishlist")]
            if not cid:
                self._send_json(400, {"error": "customer id required"})
                return
            rid = str(data.get("rewardId", "")).strip()
            if not rid:
                self._send_json(400, {"error": "rewardId is required"})
                return
            if reward_by_id(rid) is None:
                self._send_json(404, {"error": "reward not found"})
                return
            with _lock:
                c = get_customer(cid)
                if c is None:
                    self._send_json(404, {"error": "customer not found"})
                    return
                wl = _wishlist(c)
                if rid not in wl:  # idempotent: saving twice is a no-op
                    wl.append(rid)
                view = wishlist_view(c)
                save_data(_store)
            self._send_json(201, view)
            return

        # POST /api/checkout/refund -> reverse a prior checkout transaction
        if path == "/api/checkout/refund":
            txid = data.get("transactionId", None)
            if not isinstance(txid, int) or isinstance(txid, bool):
                self._send_json(400, {"error": "transactionId must be an integer"})
                return
            with _lock:
                orig = next((t for t in _txns() if t["id"] == txid), None)
                if orig is None:
                    self._send_json(404, {"error": "transaction not found"})
                    return
                if orig["type"] != "checkout":
                    self._send_json(400, {"error": "only checkout transactions can be refunded"})
                    return
                if orig.get("refunded"):
                    self._send_json(400, {"error": "transaction already refunded"})
                    return
                cid = orig["customerId"]
                c = ensure_customer(cid)
                # Undo the order: give back redeemed points, take back earned
                # points. Clamp at zero so we never drive a balance negative.
                restored = orig.get("pointsRedeemed", 0)
                reclaimed = orig.get("pointsEarned", 0)
                before = c["points"]
                after = max(0, before + restored - reclaimed)
                delta = after - before
                c["points"] = after
                orig["refunded"] = True
                txn = record_txn(cid, "refund", {
                    "originalTransactionId": txid,
                    "pointsRestored": restored,
                    "pointsReclaimed": reclaimed,
                    "delta": delta,
                    "amountRefunded": orig.get("total", 0),
                    "pointsBalance": after,
                })
                save_data(_store)
            self._send_json(200, {
                "customerId": cid,
                "originalTransactionId": txid,
                "amountRefunded": orig.get("total", 0),
                "pointsRestored": restored,
                "pointsReclaimed": reclaimed,
                "delta": delta,
                "pointsBalance": after,
                "tier": badge_label(after),
                "transactionId": txn["id"],
            })
            return

        # POST /api/checkout/cart/preview -> total a cart + preview, NO write
        if path == "/api/checkout/cart/preview":
            cid = str(data.get("customerId", "")).strip()
            if not cid:
                self._send_json(400, {"error": "customerId is required"})
                return
            try:
                lines, subtotal = normalize_cart(data.get("items", None))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            redeem = data.get("redeemPoints", 0)
            if not isinstance(redeem, (int, float)) or isinstance(redeem, bool) or redeem < 0:
                self._send_json(400, {"error": "redeemPoints must be a non-negative number"})
                return
            redeem = int(redeem)
            c = get_customer(cid)
            points = c["points"] if c is not None else 0
            if redeem > points:
                self._send_json(400, {"error": "not enough points to redeem"})
                return
            result = compute_checkout(points, subtotal, redeem)
            resp = {"customerId": cid, "preview": True,
                    "items": lines, "itemCount": len(lines)}
            resp.update(result)
            self._send_json(200, resp)
            return

        # POST /api/checkout/cart -> commit a cart purchase, award points
        if path == "/api/checkout/cart":
            cid = str(data.get("customerId", "")).strip()
            if not cid:
                self._send_json(400, {"error": "customerId is required"})
                return
            try:
                lines, subtotal = normalize_cart(data.get("items", None))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            redeem = data.get("redeemPoints", 0)
            if not isinstance(redeem, (int, float)) or isinstance(redeem, bool) or redeem < 0:
                self._send_json(400, {"error": "redeemPoints must be a non-negative number"})
                return
            redeem = int(redeem)
            with _lock:
                c = ensure_customer(cid)
                if redeem > c["points"]:
                    self._send_json(400, {"error": "not enough points to redeem"})
                    return
                result = compute_checkout(c["points"], subtotal, redeem)
                c["points"] = result["pointsBalance"]
                # Record a normal checkout txn (so refund/statement work) plus
                # the cart line items for the receipt.
                fields = dict(result)
                fields["items"] = lines
                fields["itemCount"] = len(lines)
                txn = record_txn(cid, "checkout", fields)
                save_data(_store)
                resp = {"customerId": cid, "items": lines, "itemCount": len(lines),
                        "transactionId": txn["id"]}
                resp.update(result)
            self._send_json(201, resp)
            return

        # POST /api/checkout/preview -> compute totals WITHOUT writing
        if path == "/api/checkout/preview":
            cid = str(data.get("customerId", "")).strip()
            if not cid:
                self._send_json(400, {"error": "customerId is required"})
                return
            subtotal = data.get("subtotal", None)
            if not isinstance(subtotal, (int, float)) or subtotal < 0:
                self._send_json(400, {"error": "subtotal must be a non-negative number"})
                return
            redeem = data.get("redeemPoints", 0)
            if not isinstance(redeem, (int, float)) or redeem < 0:
                self._send_json(400, {"error": "redeemPoints must be a non-negative number"})
                return
            redeem = int(redeem)
            # Preview reflects the customer's current balance, but creates
            # them only in-memory and never persists or mutates the store.
            c = get_customer(cid)
            points = c["points"] if c is not None else 0
            if redeem > points:
                self._send_json(400, {"error": "not enough points to redeem"})
                return
            result = compute_checkout(points, subtotal, redeem)
            resp = {"customerId": cid, "preview": True}
            resp.update(result)
            self._send_json(200, resp)
            return

        # POST /api/checkout  -> complete a purchase, award points
        if path == "/api/checkout":
            cid = str(data.get("customerId", "")).strip()
            if not cid:
                self._send_json(400, {"error": "customerId is required"})
                return
            subtotal = data.get("subtotal", None)
            if not isinstance(subtotal, (int, float)) or subtotal < 0:
                self._send_json(400, {"error": "subtotal must be a non-negative number"})
                return
            redeem = data.get("redeemPoints", 0)
            if not isinstance(redeem, (int, float)) or redeem < 0:
                self._send_json(400, {"error": "redeemPoints must be a non-negative number"})
                return
            redeem = int(redeem)
            with _lock:
                c = ensure_customer(cid)
                if redeem > c["points"]:
                    self._send_json(400, {"error": "not enough points to redeem"})
                    return
                # Reuse the single source of truth for checkout math.
                result = compute_checkout(c["points"], subtotal, redeem)
                c["points"] = result["pointsBalance"]
                record_txn(cid, "checkout", result)
                save_data(_store)
                resp = {"customerId": cid}
                resp.update(result)
            self._send_json(200, resp)
            return

        self._send_json(404, {"error": "route not found", "path": path})


def make_server(port=0):
    return ThreadingHTTPServer(("0.0.0.0", port), RequestHandler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = make_server(port)
    print("Loyalty checkout server ready on http://0.0.0.0:%d" % server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
