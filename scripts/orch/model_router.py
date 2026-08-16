#!/usr/bin/env python3
"""ADF model router (Python) — route each requirements-crew subagent to the model BEST
SUITED to its task, across NVIDIA NIM (free) + Anthropic (paid), by capability.

The science (see the plan): REASONING models verify/plan/judge; INSTRUCTION models
draft/extract at volume; LONG-CONTEXT models digest corpora; FRONTIER judgment (Opus)
does only the final synthesis + the human-facing questions. Free NVIDIA does the bulk;
paid Opus is spent only where quality is the deliverable. **Generator ≠ verifier** and
**perspective-diverse verification** are enforced right here by ROLE→model assignment
(drafts go to Nemotron Super/Sonnet; verification goes to deepseek-ai/deepseek-v4-pro —
strong reasoning, a different pretraining lineage than the Qwen judge lens).

  candidates(role, env)            -> ordered [(provider, model), …]
  complete(prompt, role, …)        -> (text, usage) | None  (tries candidates in order)

Every model id is overridable (`ORCH_MODEL_<ROLE>=provider:model`,
`ORCH_NVIDIA_MODEL_*`) so a changing NIM catalog never hard-breaks routing.
"""
import os

# Concrete model ids — VALIDATED live against the NVIDIA NIM catalog (free endpoint).
# (DeepSeek R1 and Nemotron-Ultra-253B are listed but NOT served for inference there —
# 404 — so the strong free reasoner is deepseek-v4-pro; Qwen is qwen3.5-397b-a17b.)
_M = {
    "deepseek": "deepseek-ai/deepseek-v4-pro",                  # strong reasoning (verifier)
    "ultra": "nvidia/nemotron-3-ultra-550b-a55b",              # FREE high-power head (550B MoE,
                                                               # reliable + deep; slow → heads only)
    "super": "nvidia/llama-3.3-nemotron-super-49b-v1.5",        # fast structured gen
    "llama70": "meta/llama-3.3-70b-instruct",                   # fast general
    "qwen": "qwen/qwen3.5-397b-a17b",                           # long context + fast reasoner
    "vision_nim": "meta/llama-3.2-90b-vision-instruct",         # free VLM
    "opus": "claude-opus-4-8",                                  # frontier judgment (paid)
    "sonnet": "claude-sonnet-4-6",                              # vision + quality draft
}

# role → ordered (provider, model) candidates. First AVAILABLE wins; the rest are
# cross-provider fallback. The science (generator≠verifier, perspective diversity) is
# enforced by the assignment: drafts go to Super, verification to DeepSeek, and the PO's
# two lenses are DIFFERENT lineages (verify=DeepSeek ∥ judge=Qwen).
_ROSTER = {
    # plan is structured DECOMPOSITION (queries/categories/urls) — a fast, reliable
    # JSON-emitter (Nemotron Super) beats a slow reasoning model that rambles past the
    # JSON; DeepSeek is the fallback. (Reasoning is reserved for the PO/verify roles.)
    "plan":       [("nvidia", _M["super"]), ("nvidia", _M["deepseek"])],
    # PO lens B — reasoning, a DIFFERENT lineage than verify → perspective-diverse. Qwen
    # (fast + reliable) by default; Nemotron Ultra under ADF_QUALITY=max (see candidates).
    "judge":      [("nvidia", _M["qwen"])],
    "verify":     [("nvidia", _M["deepseek"])],                  # PO lens A — adversarial (fast)
    "cross_check": [("nvidia", _M["deepseek"])],                 # 2nd-opinion on the head
    "draft":      [("nvidia", _M["super"])],                     # high-throughput drafting
    "extract":    [("nvidia", _M["llama70"])],                   # mechanical extraction
    "longctx":    [("nvidia", _M["qwen"])],                      # digest big corpora
    "vision":     [("anthropic", _M["sonnet"]), ("nvidia", _M["vision_nim"])],
    # HEADS / judgment: Opus (paid) → Qwen (free, FAST + reliable) → Super by DEFAULT, so
    # a crew/swarm run finishes in minutes. ADF_QUALITY=max prepends Nemotron Ultra 550B
    # (high-power but slow) for these few low-volume head calls. DeepSeek is excluded
    # from the heads (it rambles on big structured output).
    "synthesis":  [("anthropic", _M["opus"]), ("nvidia", _M["qwen"]), ("nvidia", _M["super"])],
    "questions":  [("anthropic", _M["opus"]), ("nvidia", _M["qwen"]), ("nvidia", _M["super"])],
    "split":      [("anthropic", _M["opus"]), ("nvidia", _M["qwen"]), ("nvidia", _M["super"])],
    "converge":   [("anthropic", _M["opus"]), ("nvidia", _M["qwen"]), ("nvidia", _M["super"])],
}

# Roles where ADF_QUALITY=max swaps in the slow high-power Nemotron Ultra head (these are
# LOW-VOLUME judgment calls; never the 1000s of workers).
_HEAD_ROLES = {"split", "converge", "synthesis", "questions", "judge"}

_DEFAULT = [("nvidia", _M["super"]), ("anthropic", _M["opus"]), ("ollama", None)]


def _env(env):
    return env if env is not None else os.environ


def candidates(role, env=None):
    """The ordered (provider, model) list for `role`, honoring overrides:
    `ORCH_MODEL_<ROLE>=provider:model` prepends a forced choice; `ORCH_QUALITY=high`
    upgrades the free draft to Sonnet. With no `ANTHROPIC_API_KEY`, Anthropic candidates
    are dropped (the free-only path → synthesis/questions/vision fall to NVIDIA)."""
    e = _env(env)
    base = list(_ROSTER.get(role, _DEFAULT))
    override = (e.get(f"ORCH_MODEL_{role.upper()}") or "").strip()
    if override and ":" in override:
        prov, mdl = override.split(":", 1)
        base = [(prov.strip(), mdl.strip())] + base
    quality = (e.get("ADF_QUALITY") or e.get("ORCH_QUALITY") or "").strip().lower()
    if role == "draft" and quality == "high":
        base = [("anthropic", _M["sonnet"])] + base
    # ADF_QUALITY=max → swap the slow high-power Nemotron Ultra into the judgment HEADS
    # (a few low-volume calls). Default keeps the FAST Qwen head so runs finish in minutes.
    if role in _HEAD_ROLES and quality == "max":
        base = [("nvidia", _M["ultra"])] + base
    if not (e.get("ANTHROPIC_API_KEY") or "").strip():
        base = [(p, m) for (p, m) in base if p != "anthropic"] or list(_DEFAULT)
    return base


def _dispatch(provider, messages, timeout, model):
    import agent_runner
    fn = {"nvidia": agent_runner.call_nvidia,
          "anthropic": agent_runner.call_anthropic,
          "ollama": agent_runner.call_ollama}.get(provider)
    if fn is None:
        return None
    # Route through call_with_retry so a free-tier rate-limit (HTTP 429) or transient
    # 5xx is retried with bounded backoff (honoring Retry-After) instead of silently
    # dropping the agent — ESSENTIAL when the swarm fires hundreds/thousands of free
    # NIM calls at once. A non-retryable status / exhausted attempts returns None
    # (then complete() falls to the next provider candidate).
    return agent_runner.call_with_retry(
        lambda m, t: fn(m, t, model=model), messages, timeout)


def complete(prompt, role, system=None, env=None, timeout=None, call=None):
    """Run `role`'s task on the best available model. Tries each (provider, model)
    candidate until one returns non-empty text. `call(provider, messages, timeout,
    model)` is injectable for tests. Returns (text, usage) or None.

    timeout=None means: resolve the per-call wall from ADF_NVIDIA_TIMEOUT_SEC in the
    effective env (the injected `env` dict, else os.environ), defaulting to 120s and
    falling back to 120 on a malformed value. This makes ADF_NVIDIA_TIMEOUT_SEC the
    single knob: it governs BOTH this caller-default AND agent_runner.call_nvidia's
    own min() ceiling, so the swarm's setdefault(240) actually takes effect end-to-end
    (min(240, 240) = 240) instead of being silently capped at 120. A non-None timeout
    is forwarded verbatim (an explicit caller value always wins).

    On a successful candidate, the served (provider, model) is stamped into the
    returned usage dict via setdefault (non-destructive — existing usage keys survive),
    so callers can observe which model actually served the call without changing the
    (text, usage) return arity."""
    e = _env(env)
    if timeout is None:
        try:
            timeout = int(str(e.get("ADF_NVIDIA_TIMEOUT_SEC") or "").strip() or "120")
        except ValueError:
            timeout = 120
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    runner = call or _dispatch
    last = None
    for prov, model in candidates(role, e):
        try:
            res = runner(prov, messages, timeout, model)
        except Exception:  # noqa: BLE001 — an outage on one provider must fall to next
            res = None
        if res and res[0] and res[0].strip():
            # Stamp the served identity so callers (e.g. requirements_crew) can record
            # which model actually served each role. setdefault keeps any provider-
            # supplied keys (prompt_tokens/completion_tokens/…); the dict guard is
            # defensive — all live backends return a dict for usage.
            if isinstance(res[1], dict):
                res[1].setdefault("provider", prov)
                res[1].setdefault("model", model)
            return res
        last = res
    return last
