# ADF vs Lovable — the honest scorecard

> **What "10x" means here.** Not out-shipping Lovable's funded mass-market polish —
> that isn't realistic and chasing it loses the real edge. It means winning the
> wedge Lovable *structurally cannot serve* (verifiable, governed, self-hosted,
> offline, $0-crew, agent-operable, audit-sealed) **and** reaching credible
> capability parity on the core build loop. This page states both — and says
> plainly where ADF still trails.

**Measured governance (bench):** 3/3 apps fully governed (proven + policy-compliant + offline-capable); proven 3/3, compliant 3/3, offline 3/3. See `scripts/bench/`.

**Measured capability (bench --build):** a live **$0, offline** build was attempted with ollama qwen2.5-coder:32b (local, $0, offline); 0/1 finished within the 600s budget on a single dev machine (local-model latency is real — see *time-to-first-app* below). The build/test/run **pipeline** itself is proven by the deterministic e2e (`scripts/test/e2e_react_app.py`: prompt → build → boot → serve → persist → hot-edit, with real npm + Vite + Vitest + Node — measured at ~10.7s end to end). So the pipeline is fast; the variable cost is the model's generation time, which you control by choosing the backend.

## Governance & ownership — the moat (ADF wins 9/9)

These are structural. Lovable is a hosted SaaS; it cannot offer offline builds,
self-hosting, or "own + verify your code" without abandoning its model.

| Axis | ADF | Lovable | Notes |
|---|:--:|:--:|---|
| Proof of Build (offline, tamper-evident) | ✅ | ❌ | Merkle seal over every source file + spec + verdict; recompute anywhere. |
| Policy gates (secrets / egress / PII / deps) | ✅ | ❌ | deterministic, sealed into the proof; 'does this obey our policy?' |
| Offline / air-gapped build | ✅ | ❌ | proven: build+test pass with the network blocked (regulated/offline teams). |
| Self-hosted (your infra, your data) | ✅ | ❌ | Lovable is SaaS; ADF runs entirely on your machine. |
| Own your code (portable, verifiable export) | ✅ | ⚠️ | one-click zip: source + audit bundle + proof, verifiable offline. |
| Sealed audit bundle (provenance + chain) | ✅ | ❌ | one self-verifying document a machine can hand to an auditor. |
| Agent-operable (headless MCP loop) | ✅ | ❌ | create→build→verify→prove→govern→compact→audit→export, no UI. |
| $0 / local-model crew | ✅ | ❌ | runs on local Ollama; the spec crew is zero-token. |
| Context compaction (/compact, durable cards) | ✅ | ⚠️ | logical, reviewable folds recorded as lossless-by-anchor cards. |

## Capability — the parity target

ADF reaches credible parity on the core prompt → real React+Vite+Tailwind+SQLite
app → live-preview + one-box edit loop, and is *stricter* on one axis (tests are a
hard build gate).

| Axis | ADF | Lovable | Notes |
|---|:--:|:--:|---|
| React + Vite + Tailwind multi-file app | ✅ | ✅ |  |
| Database persistence | ✅ | ✅ | ADF: SQLite (owned). Lovable: Supabase Postgres. |
| Live preview + one-box edit loop | ✅ | ✅ |  |
| Generated tests enforced as a build gate | ✅ | ⚠️ | ADF fails the build if tests don't pass; Lovable doesn't enforce. |
| Browse your live data | ✅ | ✅ | ADF: read-only Data tab. Lovable: Supabase UI. |
| Built-in auth | ⚠️ | ✅ | ADF: roll-your-own; Lovable: Supabase auth. |
| Hosted deploy + instant public URL | ⚠️ | ✅ | ADF favors self-host/export; a tunnel is deferred (not the wedge). |
| Third-party integrations (payments, etc.) | ❌ | ✅ | Lovable's ecosystem is broader; ADF has none yet. |
| Time-to-first-app | ⚠️ | ✅ | ADF ~1-3 min (npm install, cached after); Lovable is faster (hosted). |
| Template gallery / community / polish | ⚠️ | ✅ | Lovable's funded mass-market polish is ahead; by design we don't chase it. |

## Where ADF still trails (the honest part)

- Hosted deploy + instant public share URL — Lovable's hosting is better; ADF deliberately favors self-host + verifiable export (own your code).
- Ecosystem — built-in auth, payments, and third-party integrations: Lovable has them, ADF doesn't yet.
- Time-to-first-app — ADF trades ~1-3 min (npm install, cached after) for capability + verifiability; Lovable's hosted path is faster to first paint.
- Mass-market polish, template gallery, and community size — Lovable is funded and ahead; chasing this would lose the real advantage.

## Verdict

ADF wins the **governed / owned / local / agent-operable** wedge **decisively** —
every governance axis above is real, tested, and offline-verifiable (Proof of
Build, Policy Gates, air-gapped build, sealed audit bundle, portable export, the
headless MCP loop). It reaches **credible capability parity** on the core build
loop. It **trails** on hosted polish, ecosystem, and time-to-first-app — by design.

For a regulated, IP-sensitive, offline, or self-hosting team, ADF isn't 10% better —
it's the only option that can *prove* what it built. For a hobbyist who wants the
fastest hosted path to a shareable URL, Lovable is still the smoother ride. We say
so on purpose.

_Generated by `scripts/bench/scorecard.py`._
