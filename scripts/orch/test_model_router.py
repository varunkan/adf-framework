#!/usr/bin/env python3
"""Unit tests for model_router.py — capability→model routing across NVIDIA + Claude.

    python3 scripts/orch/test_model_router.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_router as mr  # noqa: E402

KEYED = {"ANTHROPIC_API_KEY": "x"}  # pretend Anthropic is available


class Candidates(unittest.TestCase):
    def test_science_assignment(self):
        # reasoning → verify on DeepSeek; drafting → Nemotron Super; head → Opus.
        # (ids validated live against the NIM catalog.)
        self.assertEqual(mr.candidates("verify", KEYED)[0], ("nvidia", "deepseek-ai/deepseek-v4-pro"))
        self.assertEqual(mr.candidates("draft", KEYED)[0][1], "nvidia/llama-3.3-nemotron-super-49b-v1.5")
        self.assertEqual(mr.candidates("synthesis", KEYED)[0], ("anthropic", "claude-opus-4-8"))
        self.assertEqual(mr.candidates("extract", KEYED)[0][1], "meta/llama-3.3-70b-instruct")

    def test_generator_ne_verifier(self):
        # drafts and verification must be DIFFERENT model lineages (uncorrelated errors)
        self.assertNotEqual(mr.candidates("draft", KEYED)[0][1],
                            mr.candidates("verify", KEYED)[0][1])

    def test_po_lenses_are_perspective_diverse(self):
        # the PO's two reasoners (verify ∥ judge) must be different models
        self.assertNotEqual(mr.candidates("verify", KEYED)[0][1],
                            mr.candidates("judge", KEYED)[0][1])

    def test_heads_fast_by_default_ultra_under_quality_max(self):
        ultra = "nvidia/nemotron-3-ultra-550b-a55b"
        qwen = "qwen/qwen3.5-397b-a17b"
        # DEFAULT (free): heads are FAST Qwen (so a run finishes in minutes), not Ultra
        self.assertEqual(mr.candidates("split", {})[0], ("nvidia", qwen))
        self.assertEqual(mr.candidates("converge", {})[0][1], qwen)
        self.assertEqual(mr.candidates("judge", {})[0][1], qwen)
        self.assertNotEqual(mr.candidates("synthesis", {})[0][1], ultra)
        # ADF_QUALITY=max → swap in the high-power (slow) Nemotron Ultra HEAD
        self.assertEqual(mr.candidates("split", {"ADF_QUALITY": "max"})[0], ("nvidia", ultra))
        self.assertEqual(mr.candidates("converge", {"ADF_QUALITY": "max"})[0][1], ultra)
        self.assertEqual(mr.candidates("synthesis", {"ADF_QUALITY": "max"})[0][1], ultra)
        # but the high-VOLUME workers stay FAST even under max
        self.assertNotEqual(mr.candidates("draft", {"ADF_QUALITY": "max"})[0][1], ultra)
        self.assertNotEqual(mr.candidates("verify", {"ADF_QUALITY": "max"})[0][1], ultra)

    def test_role_override(self):
        env = {**KEYED, "ORCH_MODEL_DRAFT": "anthropic:claude-sonnet-4-6"}
        self.assertEqual(mr.candidates("draft", env)[0], ("anthropic", "claude-sonnet-4-6"))

    def test_quality_high_upgrades_draft(self):
        env = {**KEYED, "ORCH_QUALITY": "high"}
        self.assertEqual(mr.candidates("draft", env)[0], ("anthropic", "claude-sonnet-4-6"))

    def test_free_only_drops_anthropic(self):
        # no ANTHROPIC_API_KEY → synthesis head falls to NVIDIA (Nemotron Ultra), no Claude
        cands = mr.candidates("synthesis", {})
        self.assertTrue(all(p != "anthropic" for p, _ in cands))
        self.assertEqual(cands[0][0], "nvidia")

    def test_unknown_role_uses_default(self):
        self.assertEqual(mr.candidates("zzz", KEYED)[0][0], "nvidia")


class Complete(unittest.TestCase):
    def test_returns_first_nonempty(self):
        calls = []

        def fake(provider, messages, timeout, model):
            calls.append((provider, model))
            return ("ok-from-" + model, {"tok": 1})

        out = mr.complete("hi", "verify", env=KEYED, call=fake)
        self.assertEqual(out[0], "ok-from-deepseek-ai/deepseek-v4-pro")
        self.assertEqual(len(calls), 1)  # first candidate succeeded

    def test_falls_through_on_empty(self):
        seen = []

        def fake(provider, messages, timeout, model):
            seen.append(provider)
            if provider == "anthropic":
                return ("", {})            # Opus "down" → empty
            return ("nemotron-head", {})   # NVIDIA fallback succeeds

        out = mr.complete("synthesize", "synthesis", env=KEYED, call=fake)
        self.assertEqual(out[0], "nemotron-head")
        self.assertEqual(seen, ["anthropic", "nvidia"])  # tried Opus, fell to NIM

    def test_system_prompt_is_passed(self):
        captured = {}

        def fake(provider, messages, timeout, model):
            captured["messages"] = messages
            return ("x", {})

        mr.complete("draft this", "draft", system="You are a PM", env=KEYED, call=fake)
        roles = [m["role"] for m in captured["messages"]]
        self.assertEqual(roles, ["system", "user"])


class RateLimitRetry(unittest.TestCase):
    def test_429_is_retried_not_dropped(self):
        # the free-tier resilience the swarm needs: a 429 must retry (via
        # call_with_retry), not silently drop the worker.
        import agent_runner
        from unittest import mock
        n = {"c": 0}

        def flaky(messages, timeout, model=None):
            n["c"] += 1
            if n["c"] == 1:
                raise agent_runner.HttpError(429, "rate limited", None)
            return ("ok after retry", {})

        with mock.patch.object(agent_runner, "call_nvidia", flaky), \
                mock.patch.object(agent_runner.time, "sleep", lambda *_a, **_k: None):
            out = mr.complete("hi", "extract", env={})   # extract → free NVIDIA
        self.assertEqual(out[0], "ok after retry")
        self.assertEqual(n["c"], 2)                        # 1 throttle + 1 retry


if __name__ == "__main__":
    unittest.main()
