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
        # no ANTHROPIC_API_KEY → synthesis head falls to NVIDIA (Qwen), no Claude
        cands = mr.candidates("synthesis", {})
        self.assertTrue(all(p != "anthropic" for p, _ in cands))
        self.assertEqual(cands[0][0], "nvidia")

    def test_free_only_synthesis_falls_to_qwen_not_ultra(self):
        """Regression anchor (G23): on the free path, synthesis head is Qwen, not Nemotron Ultra."""
        cands = mr.candidates("synthesis", {})  # no ANTHROPIC_API_KEY
        self.assertTrue(all(p != "anthropic" for p, _ in cands))
        self.assertEqual(cands[0][0], "nvidia")
        # Pin the specific model: Qwen, not Ultra (Ultra only under ADF_QUALITY=max)
        self.assertEqual(cands[0][1], mr._M["qwen"])
        self.assertNotEqual(cands[0][1], mr._M["ultra"])

    def test_plan_role_does_not_route_to_ultra(self):
        """G23 anchor: plan routes to Super, not Ultra (Ultra is HEAD_ROLES only)."""
        self.assertEqual(mr.candidates("plan", {})[0][1], mr._M["super"])
        self.assertNotEqual(mr.candidates("plan", {})[0][1], mr._M["ultra"])
        self.assertNotIn("plan", mr._HEAD_ROLES)  # Ultra never prepended to plan

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

    # --- G28: cross-provider None-fallthrough (documented invariant guard) ---
    def test_falls_through_on_none(self):
        """A provider that exhausts retries returns None (call_with_retry contract);
        complete() must treat None as a miss and advance to the next candidate."""
        seen = []

        def fake(provider, messages, timeout, model):
            seen.append(provider)
            if provider == "anthropic":
                return None  # simulate call_with_retry exhaustion
            return ("fallback-text", {})

        out = mr.complete("synthesize", "synthesis", env=KEYED, call=fake)
        self.assertEqual(out[0], "fallback-text")
        self.assertEqual(seen[:2], ["anthropic", "nvidia"])

    # --- G08: default timeout reads ADF_NVIDIA_TIMEOUT_SEC ---
    def test_complete_default_timeout_reads_nvidia_env(self):
        """RED (G08): with ADF_NVIDIA_TIMEOUT_SEC=240, the default timeout forwarded is 240."""
        captured = []

        def fake(provider, messages, timeout, model):
            captured.append(timeout)
            return ("ok", {})

        mr.complete("hi", "extract", env={"ADF_NVIDIA_TIMEOUT_SEC": "240"}, call=fake)
        self.assertEqual(captured[0], 240)

    def test_complete_default_timeout_unset_is_120(self):
        """GUARD (G08): with the env var absent, the effective default stays 120."""
        captured = []

        def fake(provider, messages, timeout, model):
            captured.append(timeout)
            return ("ok", {})

        mr.complete("hi", "extract", env={}, call=fake)
        self.assertEqual(captured[0], 120)

    def test_complete_explicit_timeout_is_honored(self):
        """GUARD (G08): an explicit caller timeout wins over the env-derived default."""
        captured = []

        def fake(provider, messages, timeout, model):
            captured.append(timeout)
            return ("ok", {})

        mr.complete("hi", "extract",
                    env={"ADF_NVIDIA_TIMEOUT_SEC": "240"}, timeout=30, call=fake)
        self.assertEqual(captured[0], 30)

    def test_complete_malformed_timeout_falls_back_to_120(self):
        """GUARD (G08): empty/non-numeric ADF_NVIDIA_TIMEOUT_SEC must not raise; falls to 120."""
        captured = []

        def fake(provider, messages, timeout, model):
            captured.append(timeout)
            return ("ok", {})

        mr.complete("hi", "extract", env={"ADF_NVIDIA_TIMEOUT_SEC": ""}, call=fake)
        mr.complete("hi", "extract", env={"ADF_NVIDIA_TIMEOUT_SEC": "abc"}, call=fake)
        self.assertEqual(captured, [120, 120])

    # --- G11 (router side): served (provider, model) stamped into usage ---
    def test_complete_usage_carries_served_model_identity(self):
        """RED (G11): the winning (provider, model) must be stamped into the returned usage."""
        def fake(provider, messages, timeout, model):
            return ("ok", {"tok": 1})

        out = mr.complete("hi", "verify", env=KEYED, call=fake)
        self.assertEqual(out[1]["provider"], "nvidia")
        self.assertEqual(out[1]["model"], "deepseek-ai/deepseek-v4-pro")
        # additive: existing usage keys are preserved (setdefault, non-destructive)
        self.assertEqual(out[1]["tok"], 1)

    def test_complete_usage_stamp_does_not_overwrite_existing(self):
        """GUARD (G11): if a backend already supplied provider/model, do not clobber it."""
        def fake(provider, messages, timeout, model):
            return ("ok", {"provider": "custom", "model": "custom-model"})

        out = mr.complete("hi", "verify", env=KEYED, call=fake)
        self.assertEqual(out[1]["provider"], "custom")
        self.assertEqual(out[1]["model"], "custom-model")


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
