#!/usr/bin/env python3
"""ADF model router (Python) — route each requirements-crew subagent to the model BEST
SUITED to its task, across NVIDIA NIM (free) + Anthropic (paid), by capability.

The science (see the plan): REASONING models verify/plan/judge; INSTRUCTION models
draft/extract at volume; LONG-CONTEXT models digest corpora; FRONTIER judgment (Opus)
does only the final synthesis + the human-facing questions. Free NVIDIA does the bulk;
paid Opus is spent only where quality is the deliverable. **Generator ≠ verifier** and
**perspective-diverse verification** are enforced right here by ROLE→model assignment
(drafts go to Nemotron/Sonnet; verification goes to DeepSeek R1 — a different lineage).

  candidates(role, env)            -> ordered [(provider, model), …]
  complete(prompt, role, …)        -> (text, usage) | None  (tries candidates in order)

Every model id is overridable (`ORCH_MODEL_<ROLE>=provider:model`,
`ORCH_NVIDIA_MODEL_*`) so a changing NIM catalog never hard-breaks routing.
"""
import os

# Concrete model ids per provider (NIM catalog ids; overridable via env).
_M = {
    "r1": "deepseek-ai/deepseek-r1",                              # o1-class reasoning
    "ultra": "nvidia/llama-3.1-nemotron-ultra-253b-v1",          # agentic reasoning
    "super": "nvidia/llama-3.3-nemotron-super-49b-v1.5",         # fast structured gen
    "llama70": "meta/llama-3.3-70b-instruct",                    # fast general
    "qwen": "qwen/qwen3-235b-a22b",                              # long context
    "vision_nim": "meta/llama-3.2-90b-vision-instruct",         # free VLM
    "opus": "claude-opus-4-8",                                  # frontier judgment
    "sonnet": "claude-sonnet-4-6",                              # vision + quality draft
}

# role → ordered (provider, model) candidates. First AVAILABLE wins; the rest are
# cross-provider fallback. Keyed by the CAPABILITY each role needs (the science above).
_ROSTER = {
    "plan":       [("nvidia", _M["ultra"])],                     # decompose / plan
    "judge":      [("nvidia", _M["ultra"])],                     # holistic judgment (lens A)
    "verify":     [("nvidia", _M["r1"])],                        # adversarial verification
    "cross_check": [("nvidia", _M["r1"])],                       # 2nd-opinion on the head
    "draft":      [("nvidia", _M["super"])],                     # high-throughput drafting
    "extract":    [("nvidia", _M["llama70"])],                   # mechanical extraction
    "longctx":    [("nvidia", _M["qwen"])],                      # digest big corpora
    "vision":     [("anthropic", _M["sonnet"]), ("nvidia", _M["vision_nim"])],
    "synthesis":  [("anthropic", _M["opus"]), ("nvidia", _M["ultra"])],  # the HEAD
    "questions":  [("anthropic", _M["opus"]), ("nvidia", _M["ultra"])],  # human-facing
}

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
    if role == "draft" and e.get("ORCH_QUALITY", "").strip().lower() == "high":
        base = [("anthropic", _M["sonnet"])] + base
    if not (e.get("ANTHROPIC_API_KEY") or "").strip():
        base = [(p, m) for (p, m) in base if p != "anthropic"] or list(_DEFAULT)
    return base


def _dispatch(provider, messages, timeout, model):
    import agent_runner
    if provider == "nvidia":
        return agent_runner.call_nvidia(messages, timeout, model=model)
    if provider == "anthropic":
        return agent_runner.call_anthropic(messages, timeout, model=model)
    if provider == "ollama":
        return agent_runner.call_ollama(messages, timeout, model=model)
    return None


def complete(prompt, role, system=None, env=None, timeout=120, call=None):
    """Run `role`'s task on the best available model. Tries each (provider, model)
    candidate until one returns non-empty text. `call(provider, messages, timeout,
    model)` is injectable for tests. Returns (text, usage) or None."""
    e = _env(env)
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
            return res
        last = res
    return last
