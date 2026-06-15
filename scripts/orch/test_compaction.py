#!/usr/bin/env python3
"""Unit tests for compaction.py — ADF's `/compact` engine: the single,
deterministic, OFFLINE source of truth for context budgeting and the logical
compaction transforms (messages, edit-mode files, conversation). It keeps the
high-value content verbatim and folds the rest into a reviewable summary, then
records the decision into a durable, lossless-by-anchor context card.

    python3 scripts/orch/test_compaction.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compaction as cx  # noqa: E402


def _msg(role, content):
    return {"role": role, "content": content}


def _big(label, n):
    """A chunk of ~n characters tagged with a label so we can find it."""
    body = (label + " ") * (max(1, n // (len(label) + 1)))
    return body[:n]


class EstimateTokens(unittest.TestCase):
    def test_deterministic(self):
        s = "the quick brown fox " * 50
        self.assertEqual(cx.estimate_tokens(s), cx.estimate_tokens(s))

    def test_empty_is_zero(self):
        self.assertEqual(cx.estimate_tokens(""), 0)

    def test_longer_text_costs_more(self):
        self.assertGreater(cx.estimate_tokens("x" * 4000),
                           cx.estimate_tokens("x" * 40))

    def test_accepts_message_dict_and_list(self):
        m = _msg("user", "hello there friend")
        self.assertGreater(cx.estimate_tokens(m), 0)
        total = cx.estimate_tokens([m, _msg("assistant", "hi")])
        self.assertGreaterEqual(total, cx.estimate_tokens(m))


class Budget(unittest.TestCase):
    def test_default(self):
        self.assertEqual(cx.context_budget({}), 120_000)

    def test_env_override(self):
        self.assertEqual(
            cx.context_budget({"ADF_CONTEXT_BUDGET_TOKENS": "5000"}), 5000)

    def test_bad_env_falls_back(self):
        self.assertEqual(
            cx.context_budget({"ADF_CONTEXT_BUDGET_TOKENS": "nonsense"}), 120_000)


class ShouldCompact(unittest.TestCase):
    def test_under_budget_false(self):
        self.assertFalse(cx.should_compact([_msg("user", "tiny")], budget=10_000))

    def test_over_budget_true(self):
        big = [_msg("user", _big("payload", 8000))]
        self.assertTrue(cx.should_compact(big, budget=100))


class CompactMessages(unittest.TestCase):
    def setUp(self):
        # 1 system + 6 user/assistant turns, each ~800 chars (~200 tokens).
        self.system = _msg("system", "You are the builder. Keep the rules.")
        self.turns = [
            _msg("user" if i % 2 == 0 else "assistant", _big(f"turn{i}", 800))
            for i in range(6)
        ]
        self.messages = [self.system] + self.turns

    def test_compacts_when_over_budget(self):
        res = cx.compact_messages(self.messages, budget=300, preserve_last=2)
        self.assertTrue(res.did_compact)
        self.assertLess(res.tokens_after, res.tokens_before)

    def test_preserves_system_and_last_turns_verbatim(self):
        res = cx.compact_messages(self.messages, budget=300, preserve_last=2)
        items = res.items
        # system survives, verbatim, still first
        self.assertEqual(items[0], self.system)
        # the last two turns are kept verbatim, in order, at the end
        self.assertEqual(items[-2:], self.turns[-2:])

    def test_middle_becomes_one_summary_turn(self):
        res = cx.compact_messages(self.messages, budget=300, preserve_last=2)
        # exactly one synthetic summary message, marked, between system + tail
        middle = res.items[1:-2]
        self.assertEqual(len(middle), 1)
        self.assertIn("compacted", middle[0]["content"].lower())
        self.assertEqual(res.n_summarized, 4)  # 6 turns - 2 preserved

    def test_no_op_when_already_small(self):
        small = [self.system, _msg("user", "hi")]
        res = cx.compact_messages(small, budget=120_000)
        self.assertFalse(res.did_compact)
        self.assertEqual(res.items, small)

    def test_idempotent_under_fixed_budget(self):
        once = cx.compact_messages(self.messages, budget=300, preserve_last=2)
        twice = cx.compact_messages(once.items, budget=300, preserve_last=2)
        self.assertFalse(twice.did_compact)
        self.assertEqual(twice.items, once.items)

    def test_model_summarizer_is_used_when_provided(self):
        res = cx.compact_messages(
            self.messages, budget=300, preserve_last=2,
            summarizer=lambda text: "MODEL_SAYS: four turns happened")
        middle = res.items[1:-2]
        self.assertIn("MODEL_SAYS", middle[0]["content"])

    def test_offline_summary_needs_no_model(self):
        # summarizer=None must still produce a useful, deterministic summary.
        res = cx.compact_messages(self.messages, budget=300, preserve_last=2)
        self.assertTrue(res.summary)
        self.assertEqual(
            res.summary,
            cx.compact_messages(self.messages, budget=300, preserve_last=2).summary)


class CompactFiles(unittest.TestCase):
    def setUp(self):
        self.files = [
            ("src/Header.tsx", _big("header", 400)),
            ("src/BigUnrelated.tsx", _big("widget", 4000)),
            ("server/api/orders.mjs", _big("orders", 4000)),
            ("schema.sql", "CREATE TABLE items (id INTEGER PRIMARY KEY);"),
        ]

    def test_keeps_relevant_file_whole_summarizes_rest(self):
        res = cx.compact_files(self.files, "make the Header blue", budget=200)
        kept_paths = [p for p, _ in res.items]
        self.assertIn("src/Header.tsx", kept_paths)
        # the relevant file is kept with its FULL content
        kept = dict(res.items)
        self.assertEqual(kept["src/Header.tsx"], dict(self.files)["src/Header.tsx"])
        # something large + irrelevant got summarized, not kept whole
        self.assertLess(len(res.items), len(self.files))
        self.assertGreaterEqual(res.n_summarized, 1)

    def test_summary_block_outlines_dropped_files(self):
        res = cx.compact_files(self.files, "make the Header blue", budget=200)
        # the dropped files appear by path in the summary outline
        self.assertIn("server/api/orders.mjs", res.summary)
        self.assertIn("src/BigUnrelated.tsx", res.summary)

    def test_reduces_tokens(self):
        res = cx.compact_files(self.files, "make the Header blue", budget=200)
        self.assertTrue(res.did_compact)
        self.assertLess(res.tokens_after, res.tokens_before)

    def test_no_op_when_under_budget(self):
        res = cx.compact_files(self.files, "anything", budget=120_000)
        self.assertFalse(res.did_compact)
        self.assertEqual(res.items, self.files)


class CompactConversation(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "text": _big(f"msg{i}", 600)}
            for i in range(10)
        ]

    def test_keeps_recent_folds_old(self):
        res = cx.compact_conversation(self.entries, budget=300, preserve_last=3)
        self.assertTrue(res.did_compact)
        self.assertEqual(res.items[-3:], self.entries[-3:])
        self.assertLess(res.tokens_after, res.tokens_before)
        # one synthetic summary entry leads the kept tail
        self.assertEqual(res.n_summarized, 7)


class ContextCard(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        msgs = [_msg("system", "rules")] + [
            _msg("user", _big(f"t{i}", 800)) for i in range(6)]
        self.res = cx.compact_messages(msgs, budget=300, preserve_last=2)

    def test_writes_json_and_human_card(self):
        path = cx.write_context_card(self.app, self.res, kind="messages")
        self.assertTrue(os.path.isfile(path))
        rec = json.load(open(path))
        self.assertEqual(rec["kind"], "messages")
        self.assertEqual(rec["tokens_before"], self.res.tokens_before)
        self.assertEqual(rec["tokens_after"], self.res.tokens_after)
        self.assertEqual(rec["n_summarized"], self.res.n_summarized)
        self.assertIn("summary", rec)
        # a human-readable companion is written too
        self.assertTrue(os.path.isfile(
            os.path.join(self.app, ".adf-context", "CONTEXT.md")))

    def test_cards_increment(self):
        p1 = cx.write_context_card(self.app, self.res, kind="messages")
        p2 = cx.write_context_card(self.app, self.res, kind="messages")
        self.assertNotEqual(p1, p2)
        self.assertEqual(
            len(os.listdir(os.path.join(self.app, ".adf-context"))), 3)  # 2 json + CONTEXT.md


class Cli(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        with open(os.path.join(self.app, "big.txt"), "w") as f:
            f.write(_big("payload", 8000))

    def _run(self, *args):
        import subprocess
        here = os.path.dirname(os.path.abspath(__file__))
        return subprocess.run(
            [sys.executable, os.path.join(here, "compaction.py"), *args],
            capture_output=True, text=True)

    def test_json_reports_estimate_and_verdict(self):
        r = self._run("--json", "--budget", "100", self.app)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIn("tokens", out)
        self.assertIn("budget", out)
        self.assertTrue(out["over"])

    def test_apply_writes_a_card(self):
        r = self._run("--apply", "--budget", "100", self.app)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.app, ".adf-context")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
