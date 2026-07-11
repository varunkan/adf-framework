import os
import json
import threading
import unittest
import http.client

import server


class LoyaltyAppTest(unittest.TestCase):
    def setUp(self):
        # Isolate persistence: never write the real data.json, even when the
        # suite is run via `python3 -m unittest` (which skips the __main__ guard).
        self._orig_data_file = server.DATA_FILE
        server.DATA_FILE = os.path.join(server.HERE, "test_data.json")
        # fresh in-memory store per test run
        server._store = {"customers": {}}
        self.server = server.make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if os.path.exists(server.DATA_FILE):
            os.remove(server.DATA_FILE)
        server.DATA_FILE = self._orig_data_file

    def conn(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def request(self, method, path, body=None):
        c = self.conn()
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        c.request(method, path, payload, headers)
        r = c.getresponse()
        raw = r.read().decode("utf-8")
        c.close()
        data = json.loads(raw) if raw else {}
        return r.status, data

    def test_root_serves_html(self):
        status, _ = self._raw_get("/")
        self.assertEqual(status, 200)

    def _raw_get(self, path):
        c = self.conn()
        c.request("GET", path)
        r = c.getresponse()
        r.read()
        status = r.status
        c.close()
        return status, None

    def test_create_customer_and_read_back(self):
        status, data = self.request("POST", "/api/customers",
                                    {"id": "alice", "points": 600})
        self.assertEqual(status, 201)
        self.assertEqual(data["points"], 600)
        self.assertEqual(data["tier"], "Silver")

        status, data = self.request("GET", "/api/customers/alice")
        self.assertEqual(status, 200)
        self.assertEqual(data["points"], 600)
        self.assertEqual(data["tier"], "Silver")

    def test_badge_view(self):
        self.request("POST", "/api/customers", {"id": "bob", "points": 250})
        status, data = self.request("GET", "/api/checkout/badge?customerId=bob&subtotal=10")
        self.assertEqual(status, 200)
        self.assertEqual(data["points"], 250)
        self.assertEqual(data["pointsToEarn"], 100)  # 10 * 10
        self.assertEqual(data["tier"], "Bronze")
        self.assertAlmostEqual(data["redeemableValue"], 2.5)

    def test_checkout_awards_points(self):
        self.request("POST", "/api/customers", {"id": "carol", "points": 0})
        status, data = self.request("POST", "/api/checkout",
                                    {"customerId": "carol", "subtotal": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["pointsEarned"], 200)  # 20 * 10
        self.assertEqual(data["pointsBalance"], 200)
        self.assertEqual(data["total"], 20)

    def test_checkout_redeem(self):
        self.request("POST", "/api/customers", {"id": "dan", "points": 500})
        status, data = self.request("POST", "/api/checkout",
                                    {"customerId": "dan", "subtotal": 10, "redeemPoints": 200})
        self.assertEqual(status, 200)
        # 200 points => $2 discount, total = 8, earns 80
        self.assertEqual(data["discount"], 2.0)
        self.assertEqual(data["total"], 8.0)
        self.assertEqual(data["pointsEarned"], 80)
        self.assertEqual(data["pointsBalance"], 500 - 200 + 80)

    def test_checkout_records_transaction(self):
        # Checkout must persist a transaction the /transactions route can read.
        self.request("POST", "/api/customers", {"id": "frank", "points": 0})
        self.request("POST", "/api/checkout", {"customerId": "frank", "subtotal": 15})
        status, data = self.request("GET", "/api/customers/frank/transactions")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        txn = data["transactions"][0]
        self.assertEqual(txn["type"], "checkout")
        self.assertEqual(txn["total"], 15)
        self.assertEqual(txn["pointsEarned"], 150)
        self.assertEqual(txn["pointsBalance"], 150)

    def test_transactions_empty_for_new_customer(self):
        self.request("POST", "/api/customers", {"id": "grace", "points": 10})
        status, data = self.request("GET", "/api/customers/grace/transactions")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["transactions"], [])

    def test_redeem_too_many_points_400(self):
        self.request("POST", "/api/customers", {"id": "eve", "points": 50})
        status, data = self.request("POST", "/api/checkout",
                                    {"customerId": "eve", "subtotal": 10, "redeemPoints": 999})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_customer_404(self):
        status, data = self.request("GET", "/api/customers/nobody")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_badge_requires_customer_id_400(self):
        status, data = self.request("GET", "/api/checkout/badge?subtotal=10")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_unknown_route_404(self):
        status, data = self.request("GET", "/api/does-not-exist")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: max redeemable on badge view ----------
    def test_badge_reports_max_redeemable(self):
        # balance 250 pts, subtotal $1 -> only 100 pts are worth applying
        self.request("POST", "/api/customers", {"id": "max1", "points": 250})
        status, data = self.request("GET", "/api/checkout/badge?customerId=max1&subtotal=1")
        self.assertEqual(status, 200)
        self.assertEqual(data["maxRedeemablePoints"], 100)  # capped by $1 value

    def test_badge_max_redeemable_capped_by_balance(self):
        # balance 50 pts, big subtotal -> capped by the 50 pt balance
        self.request("POST", "/api/customers", {"id": "max2", "points": 50})
        status, data = self.request("GET", "/api/checkout/badge?customerId=max2&subtotal=100")
        self.assertEqual(status, 200)
        self.assertEqual(data["maxRedeemablePoints"], 50)

    # ---------- new: checkout preview (no writes) ----------
    def test_preview_matches_checkout_math(self):
        self.request("POST", "/api/customers", {"id": "prev", "points": 500})
        status, data = self.request("POST", "/api/checkout/preview",
                                    {"customerId": "prev", "subtotal": 10, "redeemPoints": 200})
        self.assertEqual(status, 200)
        self.assertTrue(data["preview"])
        self.assertEqual(data["discount"], 2.0)
        self.assertEqual(data["total"], 8.0)
        self.assertEqual(data["pointsEarned"], 80)
        self.assertEqual(data["pointsBalance"], 500 - 200 + 80)

    def test_preview_does_not_persist(self):
        self.request("POST", "/api/customers", {"id": "prev2", "points": 300})
        self.request("POST", "/api/checkout/preview",
                     {"customerId": "prev2", "subtotal": 50, "redeemPoints": 100})
        # balance must be untouched and no transaction recorded
        status, data = self.request("GET", "/api/customers/prev2")
        self.assertEqual(data["points"], 300)
        status, txns = self.request("GET", "/api/customers/prev2/transactions")
        self.assertEqual(txns["count"], 0)

    def test_preview_rejects_overredeem(self):
        self.request("POST", "/api/customers", {"id": "prev3", "points": 10})
        status, data = self.request("POST", "/api/checkout/preview",
                                    {"customerId": "prev3", "subtotal": 5, "redeemPoints": 999})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_preview_requires_customer_id(self):
        status, data = self.request("POST", "/api/checkout/preview", {"subtotal": 5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: manual points adjustment ----------
    def test_adjust_grants_points(self):
        self.request("POST", "/api/customers", {"id": "adj1", "points": 100})
        status, data = self.request("POST", "/api/customers/adj1/adjust",
                                    {"delta": 450, "reason": "promo bonus"})
        self.assertEqual(status, 200)
        self.assertEqual(data["delta"], 450)
        self.assertEqual(data["pointsBalance"], 550)
        self.assertEqual(data["tier"], "Silver")
        self.assertEqual(data["reason"], "promo bonus")
        # persisted
        _, c = self.request("GET", "/api/customers/adj1")
        self.assertEqual(c["points"], 550)

    def test_adjust_deduct_clamps_at_zero(self):
        self.request("POST", "/api/customers", {"id": "adj2", "points": 30})
        status, data = self.request("POST", "/api/customers/adj2/adjust",
                                    {"delta": -100})
        self.assertEqual(status, 200)
        self.assertEqual(data["pointsBalance"], 0)
        self.assertEqual(data["delta"], -30)  # only what could be removed

    def test_adjust_records_transaction(self):
        self.request("POST", "/api/customers", {"id": "adj3", "points": 0})
        self.request("POST", "/api/customers/adj3/adjust", {"delta": 25, "reason": "goodwill"})
        status, data = self.request("GET", "/api/customers/adj3/transactions")
        self.assertEqual(data["count"], 1)
        txn = data["transactions"][0]
        self.assertEqual(txn["type"], "adjust")
        self.assertEqual(txn["delta"], 25)
        self.assertEqual(txn["reason"], "goodwill")
        self.assertEqual(txn["pointsBalance"], 25)

    def test_adjust_missing_customer_404(self):
        status, data = self.request("POST", "/api/customers/ghost/adjust", {"delta": 10})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_adjust_invalid_delta_400(self):
        self.request("POST", "/api/customers", {"id": "adj4", "points": 10})
        status, data = self.request("POST", "/api/customers/adj4/adjust", {"delta": "lots"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: aggregate stats ----------
    def test_stats_empty(self):
        status, data = self.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        self.assertEqual(data["customerCount"], 0)
        self.assertEqual(data["totalPoints"], 0)
        self.assertEqual(data["transactionCount"], 0)

    def test_stats_aggregates_customers_and_tiers(self):
        self.request("POST", "/api/customers", {"id": "s1", "points": 100})    # Bronze
        self.request("POST", "/api/customers", {"id": "s2", "points": 600})    # Silver
        self.request("POST", "/api/customers", {"id": "s3", "points": 2500})   # Gold
        self.request("POST", "/api/checkout", {"customerId": "s1", "subtotal": 5})
        status, data = self.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        self.assertEqual(data["customerCount"], 3)
        self.assertEqual(data["totalPoints"], 100 + 600 + 2500 + 50)  # s1 earned 50
        self.assertEqual(data["tierCounts"]["Silver"], 1)
        self.assertEqual(data["tierCounts"]["Gold"], 1)
        self.assertEqual(data["transactionCount"], 1)


    # ---------- new: rewards catalog ----------
    def test_rewards_catalog_lists_rewards(self):
        status, data = self.request("GET", "/api/rewards")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], len(data["rewards"]))
        self.assertTrue(data["count"] >= 1)
        ids = {r["id"] for r in data["rewards"]}
        self.assertIn("voucher-5", ids)
        # without a customer there is no affordability flag
        self.assertNotIn("affordable", data["rewards"][0])

    def test_rewards_catalog_marks_affordability(self):
        self.request("POST", "/api/customers", {"id": "rw1", "points": 400})
        status, data = self.request("GET", "/api/rewards?customerId=rw1")
        self.assertEqual(status, 200)
        self.assertEqual(data["points"], 400)
        by_id = {r["id"]: r for r in data["rewards"]}
        self.assertTrue(by_id["free-shipping"]["affordable"])   # 150 <= 400
        self.assertTrue(by_id["coffee"]["affordable"])          # 300 <= 400
        self.assertFalse(by_id["voucher-5"]["affordable"])      # 500 > 400

    def test_rewards_catalog_unknown_customer_404(self):
        status, data = self.request("GET", "/api/rewards?customerId=ghost")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: reward redemption ----------
    def test_redeem_reward_deducts_points(self):
        self.request("POST", "/api/customers", {"id": "rd1", "points": 600})
        status, data = self.request("POST", "/api/customers/rd1/redeem",
                                    {"rewardId": "voucher-5"})
        self.assertEqual(status, 200)
        self.assertEqual(data["cost"], 500)
        self.assertEqual(data["pointsBalance"], 100)
        self.assertEqual(data["rewardName"], "$5 Voucher")
        self.assertTrue(data["code"].startswith("RWD-"))
        # persisted
        _, c = self.request("GET", "/api/customers/rd1")
        self.assertEqual(c["points"], 100)

    def test_redeem_reward_records_transaction(self):
        self.request("POST", "/api/customers", {"id": "rd2", "points": 300})
        _, r = self.request("POST", "/api/customers/rd2/redeem", {"rewardId": "coffee"})
        status, data = self.request("GET", "/api/customers/rd2/transactions")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        txn = data["transactions"][0]
        self.assertEqual(txn["type"], "reward")
        self.assertEqual(txn["rewardId"], "coffee")
        self.assertEqual(txn["cost"], 300)
        self.assertEqual(txn["pointsBalance"], 0)
        self.assertEqual(txn["code"], r["code"])

    def test_redeem_reward_not_enough_points_400(self):
        self.request("POST", "/api/customers", {"id": "rd3", "points": 100})
        status, data = self.request("POST", "/api/customers/rd3/redeem",
                                    {"rewardId": "voucher-5"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)
        # balance untouched
        _, c = self.request("GET", "/api/customers/rd3")
        self.assertEqual(c["points"], 100)

    def test_redeem_unknown_reward_404(self):
        self.request("POST", "/api/customers", {"id": "rd4", "points": 9999})
        status, data = self.request("POST", "/api/customers/rd4/redeem",
                                    {"rewardId": "spaceship"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_unknown_customer_404(self):
        status, data = self.request("POST", "/api/customers/nobody/redeem",
                                    {"rewardId": "coffee"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_missing_reward_id_400(self):
        self.request("POST", "/api/customers", {"id": "rd5", "points": 500})
        status, data = self.request("POST", "/api/customers/rd5/redeem", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: checkout refund / reversal ----------
    def test_refund_reverses_checkout(self):
        self.request("POST", "/api/customers", {"id": "rf1", "points": 500})
        # redeem 200 on a $10 order -> discount 2, total 8, earns 80, bal 380
        _, co = self.request("POST", "/api/checkout",
                             {"customerId": "rf1", "subtotal": 10, "redeemPoints": 200})
        self.assertEqual(co["pointsBalance"], 380)
        txid = self._last_txn_id("rf1")
        status, data = self.request("POST", "/api/checkout/refund",
                                    {"transactionId": txid})
        self.assertEqual(status, 200)
        self.assertEqual(data["pointsRestored"], 200)
        self.assertEqual(data["pointsReclaimed"], 80)
        # 380 + 200 - 80 = 500 (back to the starting balance)
        self.assertEqual(data["pointsBalance"], 500)
        self.assertEqual(data["amountRefunded"], 8.0)
        _, c = self.request("GET", "/api/customers/rf1")
        self.assertEqual(c["points"], 500)

    def test_refund_records_transaction_and_marks_original(self):
        self.request("POST", "/api/customers", {"id": "rf2", "points": 0})
        self.request("POST", "/api/checkout", {"customerId": "rf2", "subtotal": 20})
        txid = self._last_txn_id("rf2")
        self.request("POST", "/api/checkout/refund", {"transactionId": txid})
        status, data = self.request("GET", "/api/customers/rf2/transactions")
        self.assertEqual(status, 200)
        types = [t["type"] for t in data["transactions"]]
        self.assertIn("refund", types)
        refund = next(t for t in data["transactions"] if t["type"] == "refund")
        self.assertEqual(refund["originalTransactionId"], txid)
        original = next(t for t in data["transactions"] if t["id"] == txid)
        self.assertTrue(original["refunded"])

    def test_refund_twice_rejected(self):
        self.request("POST", "/api/customers", {"id": "rf3", "points": 0})
        self.request("POST", "/api/checkout", {"customerId": "rf3", "subtotal": 5})
        txid = self._last_txn_id("rf3")
        self.request("POST", "/api/checkout/refund", {"transactionId": txid})
        status, data = self.request("POST", "/api/checkout/refund",
                                    {"transactionId": txid})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_refund_clamps_at_zero(self):
        # spend earned points before refunding so reclaim would go negative
        self.request("POST", "/api/customers", {"id": "rf4", "points": 0})
        self.request("POST", "/api/checkout", {"customerId": "rf4", "subtotal": 20})  # +200
        txid = self._last_txn_id("rf4")
        # drain the balance to 0
        self.request("POST", "/api/customers/rf4/adjust", {"delta": -200})
        status, data = self.request("POST", "/api/checkout/refund",
                                    {"transactionId": txid})
        self.assertEqual(status, 200)
        self.assertEqual(data["pointsBalance"], 0)  # clamped, never negative

    def test_refund_unknown_transaction_404(self):
        status, data = self.request("POST", "/api/checkout/refund",
                                    {"transactionId": 99999})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_refund_non_checkout_rejected(self):
        self.request("POST", "/api/customers", {"id": "rf5", "points": 0})
        self.request("POST", "/api/customers/rf5/adjust", {"delta": 50})
        txid = self._last_txn_id("rf5")  # an "adjust" txn
        status, data = self.request("POST", "/api/checkout/refund",
                                    {"transactionId": txid})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_refund_invalid_transaction_id_400(self):
        status, data = self.request("POST", "/api/checkout/refund",
                                    {"transactionId": "abc"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: leaderboard ----------
    def test_leaderboard_ranks_by_points(self):
        self.request("POST", "/api/customers", {"id": "lo", "points": 100})
        self.request("POST", "/api/customers", {"id": "hi", "points": 3000})
        self.request("POST", "/api/customers", {"id": "mid", "points": 800})
        status, data = self.request("GET", "/api/leaderboard")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 3)
        board = data["leaderboard"]
        self.assertEqual(board[0]["id"], "hi")
        self.assertEqual(board[0]["rank"], 1)
        self.assertEqual(board[0]["tier"], "Gold")
        self.assertEqual(board[1]["id"], "mid")
        self.assertEqual(board[2]["id"], "lo")
        self.assertEqual(board[2]["rank"], 3)

    def test_leaderboard_respects_limit(self):
        for i in range(5):
            self.request("POST", "/api/customers", {"id": "p%d" % i, "points": i * 100})
        status, data = self.request("GET", "/api/leaderboard?limit=2")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["leaderboard"][0]["id"], "p4")

    def test_leaderboard_empty(self):
        status, data = self.request("GET", "/api/leaderboard")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["leaderboard"], [])

    def test_leaderboard_bad_limit_400(self):
        status, data = self.request("GET", "/api/leaderboard?limit=abc")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: transaction type filter ----------
    def test_transactions_filter_by_type(self):
        self.request("POST", "/api/customers", {"id": "tf1", "points": 500})
        self.request("POST", "/api/checkout", {"customerId": "tf1", "subtotal": 10})
        self.request("POST", "/api/customers/tf1/adjust", {"delta": 20})
        status, data = self.request("GET", "/api/customers/tf1/transactions?type=adjust")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["transactions"][0]["type"], "adjust")

    # ---------- new: tier catalog ----------
    def test_tiers_lists_all_tiers_with_perks(self):
        status, data = self.request("GET", "/api/tiers")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], len(data["tiers"]))
        names = [t["name"] for t in data["tiers"]]
        self.assertEqual(names, ["Bronze", "Silver", "Gold", "Platinum"])
        for t in data["tiers"]:
            self.assertIn("minPoints", t)
            self.assertTrue(t["benefit"])  # non-empty perk description
        gold = next(t for t in data["tiers"] if t["name"] == "Gold")
        self.assertEqual(gold["minPoints"], 2000)

    def test_tiers_report_member_counts(self):
        self.request("POST", "/api/customers", {"id": "t1", "points": 100})   # Bronze
        self.request("POST", "/api/customers", {"id": "t2", "points": 600})   # Silver
        self.request("POST", "/api/customers", {"id": "t3", "points": 6000})  # Platinum
        status, data = self.request("GET", "/api/tiers")
        self.assertEqual(status, 200)
        by_name = {t["name"]: t for t in data["tiers"]}
        self.assertEqual(by_name["Bronze"]["customerCount"], 1)
        self.assertEqual(by_name["Silver"]["customerCount"], 1)
        self.assertEqual(by_name["Gold"]["customerCount"], 0)
        self.assertEqual(by_name["Platinum"]["customerCount"], 1)

    # ---------- new: promo codes ----------
    def test_promos_catalog_lists_codes(self):
        status, data = self.request("GET", "/api/promos")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], len(data["promos"]))
        codes = {p["code"] for p in data["promos"]}
        self.assertIn("WELCOME50", codes)
        self.assertNotIn("redeemed", data["promos"][0])  # no customer -> no flag

    def test_promos_catalog_flags_redeemed_for_customer(self):
        self.request("POST", "/api/customers", {"id": "pc1", "points": 0})
        self.request("POST", "/api/customers/pc1/promo", {"code": "WELCOME50"})
        status, data = self.request("GET", "/api/promos?customerId=pc1")
        self.assertEqual(status, 200)
        self.assertEqual(data["customerId"], "pc1")
        by_code = {p["code"]: p for p in data["promos"]}
        self.assertTrue(by_code["WELCOME50"]["redeemed"])
        self.assertFalse(by_code["SUMMER100"]["redeemed"])

    def test_promos_catalog_unknown_customer_404(self):
        status, data = self.request("GET", "/api/promos?customerId=ghost")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_promo_grants_points(self):
        self.request("POST", "/api/customers", {"id": "pr1", "points": 100})
        status, data = self.request("POST", "/api/customers/pr1/promo",
                                    {"code": "SUMMER100"})
        self.assertEqual(status, 200)
        self.assertEqual(data["bonus"], 100)
        self.assertEqual(data["pointsBalance"], 200)
        _, c = self.request("GET", "/api/customers/pr1")
        self.assertEqual(c["points"], 200)

    def test_redeem_promo_records_transaction(self):
        self.request("POST", "/api/customers", {"id": "pr2", "points": 0})
        self.request("POST", "/api/customers/pr2/promo", {"code": "VIP500"})
        status, data = self.request("GET", "/api/customers/pr2/transactions")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        txn = data["transactions"][0]
        self.assertEqual(txn["type"], "promo")
        self.assertEqual(txn["code"], "VIP500")
        self.assertEqual(txn["bonus"], 500)
        self.assertEqual(txn["pointsBalance"], 500)

    def test_redeem_promo_twice_rejected(self):
        self.request("POST", "/api/customers", {"id": "pr3", "points": 0})
        self.request("POST", "/api/customers/pr3/promo", {"code": "WELCOME50"})
        status, data = self.request("POST", "/api/customers/pr3/promo",
                                    {"code": "WELCOME50"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)
        # balance unchanged after the rejected second redemption
        _, c = self.request("GET", "/api/customers/pr3")
        self.assertEqual(c["points"], 50)

    def test_redeem_promo_unknown_code_404(self):
        self.request("POST", "/api/customers", {"id": "pr4", "points": 0})
        status, data = self.request("POST", "/api/customers/pr4/promo",
                                    {"code": "NOPE"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_promo_unknown_customer_404(self):
        status, data = self.request("POST", "/api/customers/ghost/promo",
                                    {"code": "WELCOME50"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_promo_missing_code_400(self):
        self.request("POST", "/api/customers", {"id": "pr5", "points": 0})
        status, data = self.request("POST", "/api/customers/pr5/promo", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: points transfer (gifting) ----------
    def test_transfer_moves_points_between_customers(self):
        self.request("POST", "/api/customers", {"id": "tx_a", "points": 500})
        self.request("POST", "/api/customers", {"id": "tx_b", "points": 100})
        status, data = self.request("POST", "/api/customers/tx_a/transfer",
                                    {"toCustomerId": "tx_b", "points": 200})
        self.assertEqual(status, 200)
        self.assertEqual(data["points"], 200)
        self.assertEqual(data["pointsBalance"], 300)
        self.assertEqual(data["recipientBalance"], 300)
        _, a = self.request("GET", "/api/customers/tx_a")
        _, b = self.request("GET", "/api/customers/tx_b")
        self.assertEqual(a["points"], 300)
        self.assertEqual(b["points"], 300)

    def test_transfer_records_transactions_on_both_sides(self):
        self.request("POST", "/api/customers", {"id": "tx_c", "points": 400})
        self.request("POST", "/api/customers", {"id": "tx_d", "points": 0})
        self.request("POST", "/api/customers/tx_c/transfer",
                     {"toCustomerId": "tx_d", "points": 150})
        _, sent = self.request("GET", "/api/customers/tx_c/transactions")
        out_txn = sent["transactions"][0]
        self.assertEqual(out_txn["type"], "transfer-out")
        self.assertEqual(out_txn["toCustomerId"], "tx_d")
        self.assertEqual(out_txn["points"], 150)
        self.assertEqual(out_txn["pointsBalance"], 250)
        _, recv = self.request("GET", "/api/customers/tx_d/transactions")
        in_txn = recv["transactions"][0]
        self.assertEqual(in_txn["type"], "transfer-in")
        self.assertEqual(in_txn["fromCustomerId"], "tx_c")
        self.assertEqual(in_txn["points"], 150)
        self.assertEqual(in_txn["pointsBalance"], 150)

    def test_transfer_not_enough_points_400(self):
        self.request("POST", "/api/customers", {"id": "tx_e", "points": 50})
        self.request("POST", "/api/customers", {"id": "tx_f", "points": 0})
        status, data = self.request("POST", "/api/customers/tx_e/transfer",
                                    {"toCustomerId": "tx_f", "points": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)
        # balances untouched
        _, e = self.request("GET", "/api/customers/tx_e")
        self.assertEqual(e["points"], 50)

    def test_transfer_to_self_rejected(self):
        self.request("POST", "/api/customers", {"id": "tx_g", "points": 100})
        status, data = self.request("POST", "/api/customers/tx_g/transfer",
                                    {"toCustomerId": "tx_g", "points": 10})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_transfer_unknown_recipient_404(self):
        self.request("POST", "/api/customers", {"id": "tx_h", "points": 100})
        status, data = self.request("POST", "/api/customers/tx_h/transfer",
                                    {"toCustomerId": "ghost", "points": 10})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_transfer_unknown_sender_404(self):
        self.request("POST", "/api/customers", {"id": "tx_i", "points": 100})
        status, data = self.request("POST", "/api/customers/ghost/transfer",
                                    {"toCustomerId": "tx_i", "points": 10})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_transfer_non_positive_points_400(self):
        self.request("POST", "/api/customers", {"id": "tx_j", "points": 100})
        self.request("POST", "/api/customers", {"id": "tx_k", "points": 0})
        status, data = self.request("POST", "/api/customers/tx_j/transfer",
                                    {"toCustomerId": "tx_k", "points": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: reward detail ----------
    def test_reward_detail_returns_single_reward(self):
        status, data = self.request("GET", "/api/rewards/voucher-5")
        self.assertEqual(status, 200)
        self.assertEqual(data["id"], "voucher-5")
        self.assertEqual(data["name"], "$5 Voucher")
        self.assertEqual(data["cost"], 500)

    def test_reward_detail_unknown_404(self):
        status, data = self.request("GET", "/api/rewards/spaceship")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: customer rank ----------
    def test_rank_reports_position_and_total(self):
        self.request("POST", "/api/customers", {"id": "rk_lo", "points": 100})
        self.request("POST", "/api/customers", {"id": "rk_hi", "points": 3000})
        self.request("POST", "/api/customers", {"id": "rk_mid", "points": 800})
        status, data = self.request("GET", "/api/customers/rk_mid/rank")
        self.assertEqual(status, 200)
        self.assertEqual(data["rank"], 2)
        self.assertEqual(data["totalCustomers"], 3)
        self.assertEqual(data["points"], 800)
        self.assertEqual(data["tier"], "Silver")

    def test_rank_top_customer_is_rank_one(self):
        self.request("POST", "/api/customers", {"id": "rk_a", "points": 10})
        self.request("POST", "/api/customers", {"id": "rk_b", "points": 5000})
        status, data = self.request("GET", "/api/customers/rk_b/rank")
        self.assertEqual(status, 200)
        self.assertEqual(data["rank"], 1)
        self.assertEqual(data["tier"], "Platinum")

    def test_rank_unknown_customer_404(self):
        status, data = self.request("GET", "/api/customers/ghost/rank")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: points goal (set / clear) ----------
    def test_set_goal_reports_remaining(self):
        self.request("POST", "/api/customers", {"id": "gl1", "points": 200})
        status, data = self.request("POST", "/api/customers/gl1/goal",
                                    {"goal": 500})
        self.assertEqual(status, 200)
        self.assertEqual(data["goal"], 500)
        self.assertEqual(data["remaining"], 300)
        self.assertFalse(data["reached"])
        # persisted: GET goal returns the same view
        status, view = self.request("GET", "/api/customers/gl1/goal")
        self.assertEqual(status, 200)
        self.assertEqual(view["goal"], 500)
        self.assertEqual(view["remaining"], 300)

    def test_set_goal_already_reached(self):
        self.request("POST", "/api/customers", {"id": "gl2", "points": 700})
        status, data = self.request("POST", "/api/customers/gl2/goal",
                                    {"goal": 500})
        self.assertEqual(status, 200)
        self.assertEqual(data["remaining"], 0)
        self.assertTrue(data["reached"])

    def test_clear_goal_with_zero(self):
        self.request("POST", "/api/customers", {"id": "gl3", "points": 100})
        self.request("POST", "/api/customers/gl3/goal", {"goal": 500})
        status, data = self.request("POST", "/api/customers/gl3/goal", {"goal": 0})
        self.assertEqual(status, 200)
        self.assertIsNone(data["goal"])
        self.assertFalse(data["reached"])

    def test_clear_goal_with_null(self):
        self.request("POST", "/api/customers", {"id": "gl4", "points": 100})
        self.request("POST", "/api/customers/gl4/goal", {"goal": 500})
        status, data = self.request("POST", "/api/customers/gl4/goal", {"goal": None})
        self.assertEqual(status, 200)
        self.assertIsNone(data["goal"])

    def test_set_goal_invalid_400(self):
        self.request("POST", "/api/customers", {"id": "gl5", "points": 100})
        status, data = self.request("POST", "/api/customers/gl5/goal",
                                    {"goal": "lots"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_set_goal_negative_400(self):
        self.request("POST", "/api/customers", {"id": "gl6", "points": 100})
        status, data = self.request("POST", "/api/customers/gl6/goal",
                                    {"goal": -50})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_set_goal_unknown_customer_404(self):
        status, data = self.request("POST", "/api/customers/ghost/goal",
                                    {"goal": 100})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: referrals (REFERRAL_BONUS for both parties) ----------
    def test_refer_creates_customer_and_rewards_both(self):
        self.request("POST", "/api/customers", {"id": "ref_a", "points": 200})
        status, data = self.request("POST", "/api/customers/ref_a/refer",
                                    {"newCustomerId": "ref_new"})
        self.assertEqual(status, 201)
        bonus = server.REFERRAL_BONUS
        self.assertEqual(data["bonus"], bonus)
        self.assertEqual(data["pointsBalance"], 200 + bonus)
        self.assertEqual(data["newCustomerBalance"], bonus)
        self.assertTrue(data["code"].startswith("REF-"))
        # both balances persisted
        _, a = self.request("GET", "/api/customers/ref_a")
        _, n = self.request("GET", "/api/customers/ref_new")
        self.assertEqual(a["points"], 200 + bonus)
        self.assertEqual(n["points"], bonus)

    def test_refer_records_transactions_on_both_sides(self):
        self.request("POST", "/api/customers", {"id": "ref_b", "points": 0})
        self.request("POST", "/api/customers/ref_b/refer",
                     {"newCustomerId": "ref_c"})
        _, sent = self.request("GET", "/api/customers/ref_b/transactions")
        out_txn = sent["transactions"][0]
        self.assertEqual(out_txn["type"], "referral")
        self.assertEqual(out_txn["referredCustomerId"], "ref_c")
        _, recv = self.request("GET", "/api/customers/ref_c/transactions")
        in_txn = recv["transactions"][0]
        self.assertEqual(in_txn["type"], "referral-bonus")
        self.assertEqual(in_txn["referredBy"], "ref_b")

    def test_refer_existing_customer_rejected_400(self):
        self.request("POST", "/api/customers", {"id": "ref_d", "points": 100})
        self.request("POST", "/api/customers", {"id": "ref_e", "points": 100})
        status, data = self.request("POST", "/api/customers/ref_d/refer",
                                    {"newCustomerId": "ref_e"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)
        # no bonus applied to the referrer
        _, d = self.request("GET", "/api/customers/ref_d")
        self.assertEqual(d["points"], 100)

    def test_refer_self_rejected_400(self):
        self.request("POST", "/api/customers", {"id": "ref_f", "points": 100})
        status, data = self.request("POST", "/api/customers/ref_f/refer",
                                    {"newCustomerId": "ref_f"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_refer_missing_new_id_400(self):
        self.request("POST", "/api/customers", {"id": "ref_g", "points": 100})
        status, data = self.request("POST", "/api/customers/ref_g/refer", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_refer_unknown_referrer_404(self):
        status, data = self.request("POST", "/api/customers/ghost/refer",
                                    {"newCustomerId": "ref_h"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)
        # the new customer must NOT have been created on a failed referral
        status, _ = self.request("GET", "/api/customers/ref_h")
        self.assertEqual(status, 404)

    # ---------- new: points estimator (anonymous, no customer) ----------
    def test_estimate_reports_points_to_earn(self):
        status, data = self.request("GET", "/api/estimate?subtotal=25")
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 25)
        self.assertEqual(data["discount"], 0)
        self.assertEqual(data["total"], 25)
        self.assertEqual(data["pointsToEarn"], 250)  # 25 * 10
        self.assertEqual(data["pointsPerDollar"], 10)

    def test_estimate_applies_redeem_discount(self):
        status, data = self.request("GET", "/api/estimate?subtotal=10&redeemPoints=200")
        self.assertEqual(status, 200)
        self.assertEqual(data["discount"], 2.0)   # 200 / 100
        self.assertEqual(data["total"], 8.0)
        self.assertEqual(data["pointsToEarn"], 80)
        self.assertEqual(data["pointsRedeemed"], 200)

    def test_estimate_does_not_persist_or_need_customer(self):
        self.request("GET", "/api/estimate?subtotal=50")
        status, data = self.request("GET", "/api/stats")
        self.assertEqual(data["customerCount"], 0)  # no customer created

    def test_estimate_bad_subtotal_400(self):
        status, data = self.request("GET", "/api/estimate?subtotal=lots")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_estimate_negative_subtotal_400(self):
        status, data = self.request("GET", "/api/estimate?subtotal=-5")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_estimate_bad_redeem_400(self):
        status, data = self.request("GET", "/api/estimate?subtotal=10&redeemPoints=abc")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ---------- new: single tier detail ----------
    def test_tier_detail_returns_one_tier(self):
        status, data = self.request("GET", "/api/tiers/Gold")
        self.assertEqual(status, 200)
        self.assertEqual(data["name"], "Gold")
        self.assertEqual(data["minPoints"], 2000)
        self.assertTrue(data["benefit"])

    def test_tier_detail_is_case_insensitive(self):
        status, data = self.request("GET", "/api/tiers/platinum")
        self.assertEqual(status, 200)
        self.assertEqual(data["name"], "Platinum")
        self.assertEqual(data["minPoints"], 5000)

    def test_tier_detail_reports_member_count(self):
        self.request("POST", "/api/customers", {"id": "td1", "points": 600})  # Silver
        status, data = self.request("GET", "/api/tiers/Silver")
        self.assertEqual(status, 200)
        self.assertEqual(data["customerCount"], 1)

    def test_tier_detail_unknown_404(self):
        status, data = self.request("GET", "/api/tiers/Diamond")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: code / voucher verification ----------
    def test_verify_reward_code(self):
        self.request("POST", "/api/customers", {"id": "vc1", "points": 600})
        _, r = self.request("POST", "/api/customers/vc1/redeem", {"rewardId": "voucher-5"})
        code = r["code"]
        status, data = self.request("GET", "/api/codes/%s" % code)
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["code"], code)
        self.assertEqual(data["transaction"]["type"], "reward")
        self.assertEqual(data["transaction"]["customerId"], "vc1")

    def test_verify_referral_code(self):
        self.request("POST", "/api/customers", {"id": "vc2", "points": 0})
        _, r = self.request("POST", "/api/customers/vc2/refer", {"newCustomerId": "vc2_new"})
        status, data = self.request("GET", "/api/codes/%s" % r["code"])
        self.assertEqual(status, 200)
        self.assertEqual(data["transaction"]["type"], "referral")

    def test_verify_unknown_code_404(self):
        status, data = self.request("GET", "/api/codes/RWD-99999")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: reward wishlist ----------
    def test_wishlist_empty_for_new_customer(self):
        self.request("POST", "/api/customers", {"id": "wl1", "points": 0})
        status, data = self.request("GET", "/api/customers/wl1/wishlist")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["wishlist"], [])

    def test_wishlist_add_reports_affordability_gap(self):
        self.request("POST", "/api/customers", {"id": "wl2", "points": 200})
        status, data = self.request("POST", "/api/customers/wl2/wishlist",
                                    {"rewardId": "voucher-5"})  # cost 500
        self.assertEqual(status, 201)
        self.assertEqual(data["count"], 1)
        item = data["wishlist"][0]
        self.assertEqual(item["id"], "voucher-5")
        self.assertFalse(item["affordable"])
        self.assertEqual(item["pointsNeeded"], 300)  # 500 - 200

    def test_wishlist_marks_affordable_when_enough_points(self):
        self.request("POST", "/api/customers", {"id": "wl3", "points": 400})
        self.request("POST", "/api/customers/wl3/wishlist", {"rewardId": "free-shipping"})
        status, data = self.request("GET", "/api/customers/wl3/wishlist")
        item = data["wishlist"][0]
        self.assertTrue(item["affordable"])      # 150 <= 400
        self.assertEqual(item["pointsNeeded"], 0)

    def test_wishlist_add_is_idempotent(self):
        self.request("POST", "/api/customers", {"id": "wl4", "points": 0})
        self.request("POST", "/api/customers/wl4/wishlist", {"rewardId": "coffee"})
        status, data = self.request("POST", "/api/customers/wl4/wishlist",
                                    {"rewardId": "coffee"})
        self.assertEqual(status, 201)
        self.assertEqual(data["count"], 1)  # not duplicated

    def test_wishlist_remove(self):
        self.request("POST", "/api/customers", {"id": "wl5", "points": 0})
        self.request("POST", "/api/customers/wl5/wishlist", {"rewardId": "coffee"})
        self.request("POST", "/api/customers/wl5/wishlist", {"rewardId": "voucher-5"})
        status, data = self.request("POST", "/api/customers/wl5/wishlist/remove",
                                    {"rewardId": "coffee"})
        self.assertEqual(status, 200)
        ids = {i["id"] for i in data["wishlist"]}
        self.assertNotIn("coffee", ids)
        self.assertIn("voucher-5", ids)

    def test_wishlist_remove_absent_is_noop(self):
        self.request("POST", "/api/customers", {"id": "wl6", "points": 0})
        status, data = self.request("POST", "/api/customers/wl6/wishlist/remove",
                                    {"rewardId": "coffee"})
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 0)

    def test_wishlist_add_unknown_reward_404(self):
        self.request("POST", "/api/customers", {"id": "wl7", "points": 0})
        status, data = self.request("POST", "/api/customers/wl7/wishlist",
                                    {"rewardId": "spaceship"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_wishlist_add_unknown_customer_404(self):
        status, data = self.request("POST", "/api/customers/ghost/wishlist",
                                    {"rewardId": "coffee"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_wishlist_get_unknown_customer_404(self):
        status, data = self.request("GET", "/api/customers/ghost/wishlist")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_wishlist_add_missing_reward_id_400(self):
        self.request("POST", "/api/customers", {"id": "wl8", "points": 0})
        status, data = self.request("POST", "/api/customers/wl8/wishlist", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_wishlist_persists_across_reads(self):
        self.request("POST", "/api/customers", {"id": "wl9", "points": 0})
        self.request("POST", "/api/customers/wl9/wishlist", {"rewardId": "voucher-10"})
        status, data = self.request("GET", "/api/customers/wl9/wishlist")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["wishlist"][0]["id"], "voucher-10")

    # ---------- new: daily check-in streak ----------
    def test_checkin_grants_base_bonus_first_time(self):
        self.request("POST", "/api/customers", {"id": "ck1", "points": 0})
        status, data = self.request("POST", "/api/customers/ck1/checkin")
        self.assertEqual(status, 200)
        self.assertEqual(data["streak"], 1)
        self.assertEqual(data["bonus"], server.CHECKIN_BASE_BONUS)  # 10
        self.assertEqual(data["pointsBalance"], server.CHECKIN_BASE_BONUS)
        self.assertEqual(data["nextBonus"], server.CHECKIN_BASE_BONUS + server.CHECKIN_STEP)

    def test_checkin_streak_grows_bonus(self):
        self.request("POST", "/api/customers", {"id": "ck2", "points": 0})
        # 1st: 10, 2nd: 15, 3rd: 20 -> total 45, streak 3
        b = 0
        for expect_streak, expect_bonus in [(1, 10), (2, 15), (3, 20)]:
            _, data = self.request("POST", "/api/customers/ck2/checkin")
            self.assertEqual(data["streak"], expect_streak)
            self.assertEqual(data["bonus"], expect_bonus)
            b += expect_bonus
        _, c = self.request("GET", "/api/customers/ck2")
        self.assertEqual(c["points"], b)  # 45

    def test_checkin_bonus_caps_at_max(self):
        self.request("POST", "/api/customers", {"id": "ck3", "points": 0})
        for _ in range(20):  # plenty to exceed the cap
            _, data = self.request("POST", "/api/customers/ck3/checkin")
        self.assertEqual(data["bonus"], server.CHECKIN_MAX_BONUS)  # capped at 50
        self.assertEqual(data["nextBonus"], server.CHECKIN_MAX_BONUS)

    def test_checkin_records_transaction(self):
        self.request("POST", "/api/customers", {"id": "ck4", "points": 0})
        self.request("POST", "/api/customers/ck4/checkin")
        status, data = self.request("GET", "/api/customers/ck4/transactions")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        txn = data["transactions"][0]
        self.assertEqual(txn["type"], "checkin")
        self.assertEqual(txn["streak"], 1)
        self.assertEqual(txn["bonus"], server.CHECKIN_BASE_BONUS)

    def test_streak_view_for_new_customer(self):
        self.request("POST", "/api/customers", {"id": "ck5", "points": 0})
        status, data = self.request("GET", "/api/customers/ck5/streak")
        self.assertEqual(status, 200)
        self.assertEqual(data["streak"], 0)
        self.assertEqual(data["lastBonus"], 0)
        self.assertEqual(data["nextBonus"], server.CHECKIN_BASE_BONUS)

    def test_streak_view_after_checkins(self):
        self.request("POST", "/api/customers", {"id": "ck6", "points": 0})
        self.request("POST", "/api/customers/ck6/checkin")
        self.request("POST", "/api/customers/ck6/checkin")
        status, data = self.request("GET", "/api/customers/ck6/streak")
        self.assertEqual(data["streak"], 2)
        self.assertEqual(data["lastBonus"], 15)
        self.assertEqual(data["nextBonus"], 20)

    def test_checkin_unknown_customer_404(self):
        status, data = self.request("POST", "/api/customers/ghost/checkin")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_streak_unknown_customer_404(self):
        status, data = self.request("GET", "/api/customers/ghost/streak")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: points statement ----------
    def test_statement_empty_for_new_customer(self):
        self.request("POST", "/api/customers", {"id": "st1", "points": 100})
        status, data = self.request("GET", "/api/customers/st1/statement")
        self.assertEqual(status, 200)
        self.assertEqual(data["transactionCount"], 0)
        self.assertEqual(data["totalEarned"], 0)
        self.assertEqual(data["totalRedeemed"], 0)
        self.assertEqual(data["net"], 0)
        self.assertEqual(data["pointsBalance"], 100)

    def test_statement_rolls_up_earned_and_redeemed(self):
        self.request("POST", "/api/customers", {"id": "st2", "points": 1000})
        # checkout: redeem 200 on $10 -> earns 80, redeems 200
        self.request("POST", "/api/checkout",
                     {"customerId": "st2", "subtotal": 10, "redeemPoints": 200})
        # reward: spend 300 (coffee)
        self.request("POST", "/api/customers/st2/redeem", {"rewardId": "coffee"})
        # promo: +100
        self.request("POST", "/api/customers/st2/promo", {"code": "SUMMER100"})
        status, data = self.request("GET", "/api/customers/st2/statement")
        self.assertEqual(status, 200)
        self.assertEqual(data["transactionCount"], 3)
        # earned = 80 (checkout) + 100 (promo) = 180
        self.assertEqual(data["totalEarned"], 180)
        # redeemed = 200 (checkout redeem) + 300 (reward) = 500
        self.assertEqual(data["totalRedeemed"], 500)
        self.assertEqual(data["net"], 180 - 500)
        self.assertEqual(data["countsByType"]["checkout"], 1)
        self.assertEqual(data["countsByType"]["reward"], 1)
        self.assertEqual(data["countsByType"]["promo"], 1)

    def test_statement_counts_adjustments_by_sign(self):
        self.request("POST", "/api/customers", {"id": "st3", "points": 100})
        self.request("POST", "/api/customers/st3/adjust", {"delta": 50})
        self.request("POST", "/api/customers/st3/adjust", {"delta": -30})
        status, data = self.request("GET", "/api/customers/st3/statement")
        self.assertEqual(data["totalEarned"], 50)
        self.assertEqual(data["totalRedeemed"], 30)
        self.assertEqual(data["countsByType"]["adjust"], 2)

    def test_statement_unknown_customer_404(self):
        status, data = self.request("GET", "/api/customers/ghost/statement")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ---------- new: reward categories ----------
    def test_categories_lists_distinct_categories(self):
        status, data = self.request("GET", "/api/categories")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], len(data["categories"]))
        cats = {c["category"] for c in data["categories"]}
        self.assertEqual(cats, {"shipping", "food", "voucher"})
        voucher = next(c for c in data["categories"] if c["category"] == "voucher")
        self.assertEqual(voucher["count"], 2)  # voucher-5 and voucher-10

    def test_rewards_include_category(self):
        status, data = self.request("GET", "/api/rewards")
        self.assertEqual(status, 200)
        by_id = {r["id"]: r for r in data["rewards"]}
        self.assertEqual(by_id["coffee"]["category"], "food")
        self.assertEqual(by_id["voucher-5"]["category"], "voucher")

    def test_rewards_filter_by_category(self):
        status, data = self.request("GET", "/api/rewards?category=voucher")
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "voucher")
        ids = {r["id"] for r in data["rewards"]}
        self.assertEqual(ids, {"voucher-5", "voucher-10"})
        self.assertEqual(data["count"], 2)

    def test_rewards_filter_unknown_category_empty(self):
        status, data = self.request("GET", "/api/rewards?category=spaceship")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["rewards"], [])

    def test_rewards_filter_with_affordability(self):
        self.request("POST", "/api/customers", {"id": "cat1", "points": 600})
        status, data = self.request("GET", "/api/rewards?customerId=cat1&category=voucher")
        self.assertEqual(status, 200)
        by_id = {r["id"]: r for r in data["rewards"]}
        self.assertTrue(by_id["voucher-5"]["affordable"])    # 500 <= 600
        self.assertFalse(by_id["voucher-10"]["affordable"])  # 1000 > 600

    def test_reward_detail_includes_category(self):
        status, data = self.request("GET", "/api/rewards/coffee")
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "food")

    # ---------- new: next-tier spending target ----------
    def test_next_tier_reports_points_and_dollars(self):
        self.request("POST", "/api/customers", {"id": "nt1", "points": 300})  # Bronze
        status, data = self.request("GET", "/api/customers/nt1/next-tier")
        self.assertEqual(status, 200)
        self.assertEqual(data["tier"], "Bronze")
        self.assertEqual(data["nextTier"], "Silver")
        self.assertEqual(data["pointsToNextTier"], 200)  # 500 - 300
        self.assertEqual(data["dollarsToSpend"], 20.0)   # 200 / 10
        self.assertFalse(data["atTopTier"])

    def test_next_tier_at_top_tier(self):
        self.request("POST", "/api/customers", {"id": "nt2", "points": 6000})  # Platinum
        status, data = self.request("GET", "/api/customers/nt2/next-tier")
        self.assertEqual(status, 200)
        self.assertEqual(data["tier"], "Platinum")
        self.assertIsNone(data["nextTier"])
        self.assertTrue(data["atTopTier"])
        self.assertEqual(data["dollarsToSpend"], 0)
        self.assertEqual(data["pointsToNextTier"], 0)

    def test_next_tier_unknown_customer_404(self):
        status, data = self.request("GET", "/api/customers/ghost/next-tier")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def _last_txn_id(self, cid):
        _, data = self.request("GET", "/api/customers/%s/transactions" % cid)
        return max(t["id"] for t in data["transactions"])

    # ----- achievements -----
    def test_achievements_catalog_lists_all_badges(self):
        status, data = self.request("GET", "/api/achievements")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], len(server.ACHIEVEMENTS))
        ids = [a["id"] for a in data["achievements"]]
        self.assertIn("first-purchase", ids)
        self.assertIn("top-tier", ids)
        for a in data["achievements"]:
            self.assertIn("name", a)
            self.assertIn("description", a)
            self.assertNotIn("unlocked", a)  # catalog has no per-customer state

    def test_new_customer_has_no_achievements(self):
        self.request("POST", "/api/customers", {"id": "newbie", "points": 0})
        status, data = self.request("GET", "/api/customers/newbie/achievements")
        self.assertEqual(status, 200)
        self.assertEqual(data["unlockedCount"], 0)
        self.assertEqual(data["totalCount"], len(server.ACHIEVEMENTS))
        self.assertTrue(all(not a["unlocked"] for a in data["achievements"]))

    def _unlocked_ids(self, cid):
        _, data = self.request("GET", "/api/customers/%s/achievements" % cid)
        return {a["id"] for a in data["achievements"] if a["unlocked"]}

    def test_first_purchase_achievement_unlocks_on_checkout(self):
        self.request("POST", "/api/customers", {"id": "fp", "points": 0})
        self.assertNotIn("first-purchase", self._unlocked_ids("fp"))
        self.request("POST", "/api/checkout", {"customerId": "fp", "subtotal": 5})
        self.assertIn("first-purchase", self._unlocked_ids("fp"))

    def test_big_spender_achievement(self):
        self.request("POST", "/api/customers", {"id": "bs", "points": 0})
        self.request("POST", "/api/checkout", {"customerId": "bs", "subtotal": 60})
        self.assertNotIn("big-spender", self._unlocked_ids("bs"))
        self.request("POST", "/api/checkout", {"customerId": "bs", "subtotal": 50})
        ids = self._unlocked_ids("bs")
        self.assertIn("big-spender", ids)  # 60 + 50 >= 100

    def test_high_roller_achievement_tracks_lifetime_earned(self):
        self.request("POST", "/api/customers", {"id": "hr", "points": 0})
        # Earn 1000+ lifetime points (100 * 10), even though spending later
        # reduces the live balance the achievement stays earned.
        self.request("POST", "/api/checkout", {"customerId": "hr", "subtotal": 100})
        self.assertIn("high-roller", self._unlocked_ids("hr"))
        _, prof = self.request("GET", "/api/customers/hr/achievements")
        self.assertEqual(prof["profile"]["lifetimeEarned"], 1000)

    def test_collector_achievement_on_reward_redeem(self):
        self.request("POST", "/api/customers", {"id": "col", "points": 200})
        self.assertNotIn("collector", self._unlocked_ids("col"))
        self.request("POST", "/api/customers/col/redeem", {"rewardId": "free-shipping"})
        self.assertIn("collector", self._unlocked_ids("col"))

    def test_streak_master_achievement(self):
        self.request("POST", "/api/customers", {"id": "sm", "points": 0})
        for _ in range(6):
            self.request("POST", "/api/customers/sm/checkin", {})
        self.assertNotIn("streak-master", self._unlocked_ids("sm"))
        self.request("POST", "/api/customers/sm/checkin", {})  # 7th day
        self.assertIn("streak-master", self._unlocked_ids("sm"))

    def test_philanthropist_achievement_on_transfer(self):
        self.request("POST", "/api/customers", {"id": "giver", "points": 300})
        self.request("POST", "/api/customers", {"id": "taker", "points": 0})
        self.assertNotIn("philanthropist", self._unlocked_ids("giver"))
        self.request("POST", "/api/customers/giver/transfer",
                     {"toCustomerId": "taker", "points": 50})
        self.assertIn("philanthropist", self._unlocked_ids("giver"))

    def test_recruiter_achievement_on_referral(self):
        self.request("POST", "/api/customers", {"id": "host", "points": 0})
        self.assertNotIn("recruiter", self._unlocked_ids("host"))
        self.request("POST", "/api/customers/host/refer", {"newCustomerId": "rookie"})
        self.assertIn("recruiter", self._unlocked_ids("host"))

    def test_goal_getter_achievement(self):
        self.request("POST", "/api/customers", {"id": "gg", "points": 500})
        self.request("POST", "/api/customers/gg/goal", {"goal": 400})
        self.assertIn("goal-getter", self._unlocked_ids("gg"))
        self.request("POST", "/api/customers/gg/goal", {"goal": 9000})
        self.assertNotIn("goal-getter", self._unlocked_ids("gg"))

    def test_top_tier_achievement(self):
        self.request("POST", "/api/customers", {"id": "vip", "points": 5000})
        self.assertIn("top-tier", self._unlocked_ids("vip"))

    def test_achievements_unknown_customer_404(self):
        status, data = self.request("GET", "/api/customers/ghost/achievements")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # ----- cart checkout -----
    def test_cart_checkout_totals_line_items_and_awards_points(self):
        self.request("POST", "/api/customers", {"id": "cart1", "points": 0})
        status, data = self.request("POST", "/api/checkout/cart", {
            "customerId": "cart1",
            "items": [{"name": "Latte", "price": 4.5, "qty": 2},
                      {"name": "Muffin", "price": 3.0, "qty": 1}],
        })
        self.assertEqual(status, 201)
        self.assertEqual(data["subtotal"], 12.0)   # 4.5*2 + 3
        self.assertEqual(data["pointsEarned"], 120)  # 12 * 10
        self.assertEqual(data["pointsBalance"], 120)
        self.assertEqual(data["itemCount"], 2)
        self.assertEqual(data["items"][0]["lineTotal"], 9.0)

    def test_cart_checkout_with_redeem(self):
        self.request("POST", "/api/customers", {"id": "cart2", "points": 300})
        status, data = self.request("POST", "/api/checkout/cart", {
            "customerId": "cart2",
            "items": [{"name": "Book", "price": 20, "qty": 1}],
            "redeemPoints": 100,
        })
        self.assertEqual(status, 201)
        self.assertEqual(data["discount"], 1.0)     # 100 pts / 100
        self.assertEqual(data["total"], 19.0)
        self.assertEqual(data["pointsRedeemed"], 100)
        self.assertEqual(data["pointsEarned"], 190)  # 19 * 10
        self.assertEqual(data["pointsBalance"], 390)  # 300 - 100 + 190

    def test_cart_checkout_default_qty_is_one(self):
        self.request("POST", "/api/customers", {"id": "cart3", "points": 0})
        status, data = self.request("POST", "/api/checkout/cart", {
            "customerId": "cart3", "items": [{"name": "Pen", "price": 2.0}],
        })
        self.assertEqual(status, 201)
        self.assertEqual(data["items"][0]["qty"], 1)
        self.assertEqual(data["subtotal"], 2.0)

    def test_cart_checkout_records_refundable_transaction(self):
        self.request("POST", "/api/customers", {"id": "cart4", "points": 0})
        _, data = self.request("POST", "/api/checkout/cart", {
            "customerId": "cart4", "items": [{"name": "Tea", "price": 10, "qty": 1}],
        })
        txid = data["transactionId"]
        # The cart checkout is a normal checkout txn, so refund works on it.
        status, refund = self.request("POST", "/api/checkout/refund",
                                      {"transactionId": txid})
        self.assertEqual(status, 200)
        self.assertEqual(refund["pointsBalance"], 0)  # earned points clawed back
        # And it shows up in the statement as spend.
        _, stmt = self.request("GET", "/api/customers/cart4/statement")
        self.assertEqual(stmt["countsByType"].get("checkout"), 1)

    def test_cart_preview_does_not_write(self):
        self.request("POST", "/api/customers", {"id": "cart5", "points": 50})
        status, data = self.request("POST", "/api/checkout/cart/preview", {
            "customerId": "cart5",
            "items": [{"name": "Soda", "price": 3, "qty": 4}],
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["preview"])
        self.assertEqual(data["subtotal"], 12.0)
        self.assertEqual(data["pointsEarned"], 120)
        # balance unchanged on the server
        _, c = self.request("GET", "/api/customers/cart5")
        self.assertEqual(c["points"], 50)
        _, txns = self.request("GET", "/api/customers/cart5/transactions")
        self.assertEqual(txns["count"], 0)

    def test_cart_preview_works_for_unknown_customer(self):
        # Preview should not require the customer to exist (balance defaults 0).
        status, data = self.request("POST", "/api/checkout/cart/preview", {
            "customerId": "nobody", "items": [{"name": "X", "price": 5, "qty": 1}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["pointsBalance"], 50)

    def test_cart_checkout_empty_items_400(self):
        self.request("POST", "/api/customers", {"id": "cart6", "points": 0})
        status, data = self.request("POST", "/api/checkout/cart",
                                    {"customerId": "cart6", "items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_cart_checkout_missing_items_400(self):
        self.request("POST", "/api/customers", {"id": "cart7", "points": 0})
        status, data = self.request("POST", "/api/checkout/cart",
                                    {"customerId": "cart7"})
        self.assertEqual(status, 400)

    def test_cart_checkout_negative_price_400(self):
        self.request("POST", "/api/customers", {"id": "cart8", "points": 0})
        status, data = self.request("POST", "/api/checkout/cart", {
            "customerId": "cart8", "items": [{"name": "Bad", "price": -1, "qty": 1}],
        })
        self.assertEqual(status, 400)
        self.assertIn("price", data["error"])

    def test_cart_checkout_zero_qty_400(self):
        self.request("POST", "/api/customers", {"id": "cart9", "points": 0})
        status, data = self.request("POST", "/api/checkout/cart", {
            "customerId": "cart9", "items": [{"name": "Bad", "price": 5, "qty": 0}],
        })
        self.assertEqual(status, 400)
        self.assertIn("qty", data["error"])

    def test_cart_checkout_missing_customer_id_400(self):
        status, data = self.request("POST", "/api/checkout/cart",
                                    {"items": [{"price": 5, "qty": 1}]})
        self.assertEqual(status, 400)

    def test_cart_checkout_redeem_more_than_balance_400(self):
        self.request("POST", "/api/customers", {"id": "cart10", "points": 10})
        status, data = self.request("POST", "/api/checkout/cart", {
            "customerId": "cart10",
            "items": [{"name": "Y", "price": 5, "qty": 1}],
            "redeemPoints": 999,
        })
        self.assertEqual(status, 400)

    def test_cart_checkout_unlocks_big_spender_achievement(self):
        # End-to-end: cart checkout feeds the achievement profile.
        self.request("POST", "/api/customers", {"id": "cart11", "points": 0})
        self.request("POST", "/api/checkout/cart", {
            "customerId": "cart11",
            "items": [{"name": "TV", "price": 120, "qty": 1}],
        })
        self.assertIn("big-spender", self._unlocked_ids("cart11"))


    # ---------- new: reward bundles ----------
    def test_bundles_catalog_lists_bundles(self):
        status, data = self.request("GET", "/api/bundles")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], len(data["bundles"]))
        self.assertEqual(data["count"], len(server.BUNDLES))
        ids = {b["id"] for b in data["bundles"]}
        self.assertIn("starter", ids)
        self.assertIn("premium", ids)
        # without a customer there is no affordability flag
        self.assertNotIn("affordable", data["bundles"][0])

    def test_bundles_catalog_reports_savings(self):
        # Every bundle must be cheaper than buying its rewards individually.
        status, data = self.request("GET", "/api/bundles")
        self.assertEqual(status, 200)
        for b in data["bundles"]:
            self.assertEqual(b["savings"], b["fullCost"] - b["cost"])
            self.assertGreater(b["savings"], 0)
        starter = next(b for b in data["bundles"] if b["id"] == "starter")
        # free-shipping (150) + coffee (300) = 450 à la carte vs 400 bundled
        self.assertEqual(starter["fullCost"], 450)
        self.assertEqual(starter["cost"], 400)
        self.assertEqual(starter["savings"], 50)
        self.assertEqual(starter["rewardCount"], 2)

    def test_bundles_catalog_marks_affordability(self):
        self.request("POST", "/api/customers", {"id": "bn1", "points": 500})
        status, data = self.request("GET", "/api/bundles?customerId=bn1")
        self.assertEqual(status, 200)
        self.assertEqual(data["points"], 500)
        by_id = {b["id"]: b for b in data["bundles"]}
        self.assertTrue(by_id["starter"]["affordable"])    # 400 <= 500
        self.assertEqual(by_id["starter"]["pointsNeeded"], 0)
        self.assertFalse(by_id["value"]["affordable"])     # 700 > 500
        self.assertEqual(by_id["value"]["pointsNeeded"], 200)

    def test_bundles_catalog_unknown_customer_404(self):
        status, data = self.request("GET", "/api/bundles?customerId=ghost")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_bundle_detail_expands_rewards(self):
        status, data = self.request("GET", "/api/bundles/starter")
        self.assertEqual(status, 200)
        self.assertEqual(data["id"], "starter")
        self.assertEqual(data["rewardCount"], 2)
        names = {r["id"] for r in data["rewards"]}
        self.assertEqual(names, {"free-shipping", "coffee"})
        coffee = next(r for r in data["rewards"] if r["id"] == "coffee")
        self.assertEqual(coffee["cost"], 300)
        self.assertEqual(coffee["category"], "food")

    def test_bundle_detail_unknown_404(self):
        status, data = self.request("GET", "/api/bundles/spaceship")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_bundle_deducts_points(self):
        self.request("POST", "/api/customers", {"id": "rb1", "points": 600})
        status, data = self.request("POST", "/api/customers/rb1/redeem-bundle",
                                    {"bundleId": "starter"})
        self.assertEqual(status, 200)
        self.assertEqual(data["cost"], 400)
        self.assertEqual(data["pointsBalance"], 200)
        self.assertEqual(data["bundleName"], "Starter Pack")
        self.assertEqual(set(data["rewardIds"]), {"free-shipping", "coffee"})
        self.assertTrue(data["code"].startswith("BND-"))
        # persisted
        _, c = self.request("GET", "/api/customers/rb1")
        self.assertEqual(c["points"], 200)

    def test_redeem_bundle_records_transaction(self):
        self.request("POST", "/api/customers", {"id": "rb2", "points": 800})
        _, r = self.request("POST", "/api/customers/rb2/redeem-bundle",
                            {"bundleId": "value"})
        status, data = self.request("GET", "/api/customers/rb2/transactions")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        txn = data["transactions"][0]
        self.assertEqual(txn["type"], "bundle")
        self.assertEqual(txn["bundleId"], "value")
        self.assertEqual(txn["cost"], 700)
        self.assertEqual(txn["pointsBalance"], 100)
        self.assertEqual(txn["code"], r["code"])

    def test_redeem_bundle_not_enough_points_400(self):
        self.request("POST", "/api/customers", {"id": "rb3", "points": 100})
        status, data = self.request("POST", "/api/customers/rb3/redeem-bundle",
                                    {"bundleId": "starter"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)
        # balance untouched
        _, c = self.request("GET", "/api/customers/rb3")
        self.assertEqual(c["points"], 100)

    def test_redeem_bundle_unknown_bundle_404(self):
        self.request("POST", "/api/customers", {"id": "rb4", "points": 9999})
        status, data = self.request("POST", "/api/customers/rb4/redeem-bundle",
                                    {"bundleId": "spaceship"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_bundle_unknown_customer_404(self):
        status, data = self.request("POST", "/api/customers/ghost/redeem-bundle",
                                    {"bundleId": "starter"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_redeem_bundle_missing_bundle_id_400(self):
        self.request("POST", "/api/customers", {"id": "rb5", "points": 9999})
        status, data = self.request("POST", "/api/customers/rb5/redeem-bundle", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_redeem_bundle_code_is_verifiable(self):
        self.request("POST", "/api/customers", {"id": "rb6", "points": 600})
        _, r = self.request("POST", "/api/customers/rb6/redeem-bundle",
                            {"bundleId": "starter"})
        status, data = self.request("GET", "/api/codes/%s" % r["code"])
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["transaction"]["type"], "bundle")
        self.assertEqual(data["transaction"]["customerId"], "rb6")

    def test_redeem_bundle_counts_as_redeemed_in_statement(self):
        self.request("POST", "/api/customers", {"id": "rb7", "points": 900})
        self.request("POST", "/api/customers/rb7/redeem-bundle", {"bundleId": "value"})
        status, data = self.request("GET", "/api/customers/rb7/statement")
        self.assertEqual(status, 200)
        self.assertEqual(data["totalEarned"], 0)
        self.assertEqual(data["totalRedeemed"], 700)  # bundle cost spent
        self.assertEqual(data["net"], -700)
        self.assertEqual(data["countsByType"]["bundle"], 1)
        self.assertEqual(data["pointsBalance"], 200)


    # ---------- new: gift a catalog reward to another member ----------
    def test_gift_reward_deducts_sender_and_issues_code(self):
        self.request("POST", "/api/customers", {"id": "gf_a", "points": 600})
        self.request("POST", "/api/customers", {"id": "gf_b", "points": 50})
        status, data = self.request("POST", "/api/customers/gf_a/gift-reward",
                                    {"toCustomerId": "gf_b", "rewardId": "voucher-5"})
        self.assertEqual(status, 201)
        self.assertEqual(data["cost"], 500)
        self.assertEqual(data["rewardName"], "$5 Voucher")
        self.assertEqual(data["pointsBalance"], 100)       # 600 - 500
        self.assertEqual(data["recipientBalance"], 50)      # recipient pays nothing
        self.assertTrue(data["code"].startswith("GFT-"))
        # persisted: sender charged, recipient untouched
        _, a = self.request("GET", "/api/customers/gf_a")
        _, b = self.request("GET", "/api/customers/gf_b")
        self.assertEqual(a["points"], 100)
        self.assertEqual(b["points"], 50)

    def test_gift_reward_records_transactions_on_both_sides(self):
        self.request("POST", "/api/customers", {"id": "gf_c", "points": 400})
        self.request("POST", "/api/customers", {"id": "gf_d", "points": 0})
        _, r = self.request("POST", "/api/customers/gf_c/gift-reward",
                            {"toCustomerId": "gf_d", "rewardId": "coffee"})
        _, sent = self.request("GET", "/api/customers/gf_c/transactions")
        out_txn = sent["transactions"][0]
        self.assertEqual(out_txn["type"], "gift-reward")
        self.assertEqual(out_txn["rewardId"], "coffee")
        self.assertEqual(out_txn["toCustomerId"], "gf_d")
        self.assertEqual(out_txn["cost"], 300)
        self.assertEqual(out_txn["code"], r["code"])
        _, recv = self.request("GET", "/api/customers/gf_d/transactions")
        in_txn = recv["transactions"][0]
        self.assertEqual(in_txn["type"], "gift-received")
        self.assertEqual(in_txn["fromCustomerId"], "gf_c")
        self.assertEqual(in_txn["rewardId"], "coffee")
        self.assertEqual(in_txn["code"], r["code"])

    def test_gift_reward_code_is_verifiable(self):
        self.request("POST", "/api/customers", {"id": "gf_e", "points": 600})
        self.request("POST", "/api/customers", {"id": "gf_f", "points": 0})
        _, r = self.request("POST", "/api/customers/gf_e/gift-reward",
                            {"toCustomerId": "gf_f", "rewardId": "voucher-5"})
        status, data = self.request("GET", "/api/codes/%s" % r["code"])
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["transaction"]["type"], "gift-reward")
        self.assertEqual(data["transaction"]["customerId"], "gf_e")

    def test_gift_reward_not_enough_points_400(self):
        self.request("POST", "/api/customers", {"id": "gf_g", "points": 100})
        self.request("POST", "/api/customers", {"id": "gf_h", "points": 0})
        status, data = self.request("POST", "/api/customers/gf_g/gift-reward",
                                    {"toCustomerId": "gf_h", "rewardId": "voucher-5"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)
        # both balances untouched
        _, g = self.request("GET", "/api/customers/gf_g")
        self.assertEqual(g["points"], 100)

    def test_gift_reward_unknown_reward_404(self):
        self.request("POST", "/api/customers", {"id": "gf_i", "points": 9999})
        self.request("POST", "/api/customers", {"id": "gf_j", "points": 0})
        status, data = self.request("POST", "/api/customers/gf_i/gift-reward",
                                    {"toCustomerId": "gf_j", "rewardId": "spaceship"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_gift_reward_unknown_sender_404(self):
        self.request("POST", "/api/customers", {"id": "gf_k", "points": 0})
        status, data = self.request("POST", "/api/customers/ghost/gift-reward",
                                    {"toCustomerId": "gf_k", "rewardId": "coffee"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_gift_reward_unknown_recipient_404(self):
        self.request("POST", "/api/customers", {"id": "gf_l", "points": 9999})
        status, data = self.request("POST", "/api/customers/gf_l/gift-reward",
                                    {"toCustomerId": "ghost", "rewardId": "coffee"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_gift_reward_to_self_rejected_400(self):
        self.request("POST", "/api/customers", {"id": "gf_m", "points": 9999})
        status, data = self.request("POST", "/api/customers/gf_m/gift-reward",
                                    {"toCustomerId": "gf_m", "rewardId": "coffee"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_gift_reward_missing_recipient_400(self):
        self.request("POST", "/api/customers", {"id": "gf_n", "points": 9999})
        status, data = self.request("POST", "/api/customers/gf_n/gift-reward",
                                    {"rewardId": "coffee"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_gift_reward_missing_reward_id_400(self):
        self.request("POST", "/api/customers", {"id": "gf_o", "points": 9999})
        self.request("POST", "/api/customers", {"id": "gf_p", "points": 0})
        status, data = self.request("POST", "/api/customers/gf_o/gift-reward",
                                    {"toCustomerId": "gf_p"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_gift_reward_counts_as_redeemed_in_sender_statement(self):
        self.request("POST", "/api/customers", {"id": "gf_q", "points": 900})
        self.request("POST", "/api/customers", {"id": "gf_r", "points": 0})
        self.request("POST", "/api/customers/gf_q/gift-reward",
                     {"toCustomerId": "gf_r", "rewardId": "voucher-5"})
        status, data = self.request("GET", "/api/customers/gf_q/statement")
        self.assertEqual(status, 200)
        self.assertEqual(data["totalEarned"], 0)
        self.assertEqual(data["totalRedeemed"], 500)   # the gifted reward cost
        self.assertEqual(data["net"], -500)
        self.assertEqual(data["countsByType"]["gift-reward"], 1)
        self.assertEqual(data["pointsBalance"], 400)

    def test_gift_received_is_neutral_in_recipient_statement(self):
        self.request("POST", "/api/customers", {"id": "gf_s", "points": 600})
        self.request("POST", "/api/customers", {"id": "gf_t", "points": 70})
        self.request("POST", "/api/customers/gf_s/gift-reward",
                     {"toCustomerId": "gf_t", "rewardId": "voucher-5"})
        status, data = self.request("GET", "/api/customers/gf_t/statement")
        self.assertEqual(status, 200)
        # the perk moved, but no points did, so earned/redeemed stay zero
        self.assertEqual(data["totalEarned"], 0)
        self.assertEqual(data["totalRedeemed"], 0)
        self.assertEqual(data["net"], 0)
        self.assertEqual(data["countsByType"]["gift-received"], 1)
        self.assertEqual(data["pointsBalance"], 70)

    def test_gifts_view_lists_sent_and_received(self):
        self.request("POST", "/api/customers", {"id": "gf_u", "points": 1000})
        self.request("POST", "/api/customers", {"id": "gf_v", "points": 1000})
        # u gifts v a coffee; v gifts u a free-shipping
        self.request("POST", "/api/customers/gf_u/gift-reward",
                     {"toCustomerId": "gf_v", "rewardId": "coffee"})
        self.request("POST", "/api/customers/gf_v/gift-reward",
                     {"toCustomerId": "gf_u", "rewardId": "free-shipping"})
        status, data = self.request("GET", "/api/customers/gf_u/gifts")
        self.assertEqual(status, 200)
        self.assertEqual(data["sentCount"], 1)
        self.assertEqual(data["receivedCount"], 1)
        self.assertEqual(data["sent"][0]["rewardId"], "coffee")
        self.assertEqual(data["sent"][0]["toCustomerId"], "gf_v")
        self.assertEqual(data["received"][0]["rewardId"], "free-shipping")
        self.assertEqual(data["received"][0]["fromCustomerId"], "gf_v")

    def test_gifts_view_empty_for_new_customer(self):
        self.request("POST", "/api/customers", {"id": "gf_w", "points": 0})
        status, data = self.request("GET", "/api/customers/gf_w/gifts")
        self.assertEqual(status, 200)
        self.assertEqual(data["sentCount"], 0)
        self.assertEqual(data["receivedCount"], 0)
        self.assertEqual(data["sent"], [])
        self.assertEqual(data["received"], [])

    def test_gifts_view_unknown_customer_404(self):
        status, data = self.request("GET", "/api/customers/ghost/gifts")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_gift_reward_invalid_json_body_400(self):
        self.request("POST", "/api/customers", {"id": "gf_x", "points": 9999})
        c = self.conn()
        c.request("POST", "/api/customers/gf_x/gift-reward", "{bad json",
                  {"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        status = r.status
        c.close()
        self.assertEqual(status, 400)


if __name__ == "__main__":
    # use a temp data file so tests don't clobber real data
    server.DATA_FILE = os.path.join(server.HERE, "test_data.json")
    try:
        unittest.main(verbosity=2)
    finally:
        if os.path.exists(server.DATA_FILE):
            os.remove(server.DATA_FILE)
