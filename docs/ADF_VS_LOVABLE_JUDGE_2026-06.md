# ADF vs Lovable — The Honest Judge's Report

**Date:** 2026-06-19 · **Scope:** Is "make ADF 10x better than Lovable — very cheap, extremely efficient, especially in security/governance/performance" real today? Where is it achievable cheaply, grounded in ADF's existing seams?

**Method:** Every load-bearing claim below was re-verified against the source (agent_runner.py, policy_gate.py, proof_of_build.py, verify_proof.py, feature_shapes.py, templates/, the shipped proven apps, and the recorded bench artifacts). Findings that contradict ADF's own docs or the per-axis comparisons are flagged explicitly. I am a judge, not a cheerleader.

---

## Top-line verdict

**"10x better" is true on ONE axis, narrowly true on a SECOND, and marketing on the other five.**

ADF has a genuine, defensible wedge Lovable structurally cannot copy: **VERIFY, don't TRUST** — an offline-recomputable Merkle Proof of Build + an offline policy gate, so a buyer recomputes (no network, no key, no trust) that the app is byte-for-byte what was built and reads its policy verdict. Lovable has *zero* build attestation, SBOM, provenance, or reproducibility. That is the moat.

But the moat is **under-enforced and partly mis-attested today**, and three honesty holes must close before the 10x security/governance claim is real:

1. **The policy gate is ADVISORY.** `agent_runner.py:2214` runs it only inside `if verified:`, hardcodes `"verified": True` into the seal (line 2243), and the process exits on tests only (`sys.exit(0 if verified else 6)`, line 2296). `policy_ok` is computed (2224) and never gates anything. **An app with a leaked `sk-` key ships "verified + sealed."** ADF *labels* insecure apps; it does not yet *refuse* them.
2. **The one shipped mobile-auth primitive is insecure-by-construction.** `apps/mobile-auth-login/src/auth.ts` uses **FNV-1a** (a non-cryptographic hash) under a deliberately misnamed `sha256ish()`, with **`Math.random()`** for both salt and session token — not a CSPRNG, not SHA-256. The gate does not catch it. The comparison's claim that "mobile already does on-device SHA-256" is **false**.
3. **The only shipped per-app proof currently seals a FALSEHOOD.** `apps/mobile-auth-login/.adf-proof.json` on disk records `policy ok=false, n_violations=6` (false positives on TS signatures + test fixtures), while the *current* gate returns **COMPLIANT / 0 violations** (verified by live re-run). The seal predates the false-positive fix (commit 7bffbac) and was never re-sealed — a tamper-evident seal attesting a falsehood, with **no revocation mechanism**.

The good news: the highest-leverage fixes are **cheap and reuse existing seams**. The hard gate is ~1hr. The signed seal is ~30 lines. The authorization proof rides the feature_shapes contract seam.

---

## Scorecard (1–10, today)

| Axis | Leader | ADF | Lovable | One-line rationale |
|---|---|---|---|---|
| Security (app-level) | **ADF** | 7 | 4 | Real scrypt/HMAC web auth + offline detectors over loopback/local-SQLite (sidesteps RLS class) — but gate advisory, mobile auth broken, no authz rule |
| Governance / auditability | **Tie** | 7 | 6 | ADF uniquely proves *what was built* (Merkle proof) — Lovable can't; Lovable owns org-compliance (SOC2/ISO/SSO) ADF lacks entirely |
| Performance | **Lovable** | 5 | 7 | Lovable hot-reloads in seconds; ADF full re-verify every edit. ADF's 42.5s is an honest *render-verified* number; code-gen determinism is *worse* than claimed |
| Cost / efficiency | **Tie** | 7 | 6 | ADF leads true marginal cost; "$0 default" is misleading (free path built 0/3 in bench; $0.37 was paid Claude); cost never sealed |
| Iteration DX / live preview | **Lovable** | 4 | 8 | Lovable: click-to-edit, multiplayer, shareable URLs. ADF: governed but batch-grained, single-player, localhost-only |
| Deploy / public URL | **Lovable** | 3 | 8 | ADF has *no* hosted deploy (grep-confirmed); only a self-verifying export + air-gap guarantee |
| Integrations / backend | **Lovable** | 3 | 8 | Lovable: Postgres/OAuth/Stripe/storage from a prompt. ADF: embedded SQLite, web-only auth, *zero* external integrations |
| Breadth + mobile + polish | **Lovable** | 5 | 7 | ADF *only* one emitting native code + governed dark-mode theming; trails on signed binary, Android render, deploy |

---

## Per-axis verdict

**Security — ADF leads, narrowly, under-enforced.** Verified real: `auth.mjs` (scryptSync + per-user `randomBytes(16)` salt + `timingSafeEqual` + HMAC-SHA256 sessions + per-app `.adf-auth-secret` with a fail-loud `_resolveSecret`, *no* world-known fallback). The 5 offline detectors locate every violation `file:line`. The loopback + local-SQLite architecture genuinely sidesteps the anon-key/RLS class behind CVE-2025-48757 (10.3% of Lovable showcase apps leaked PII) — **market this as an advantage, not a gap.** Gaps: advisory gate, FNV-1a mobile auth, no authz/owner-scoping rule, no entropy fallback in `_SECRET_PATTERNS`, no security-headers rule.

**Governance — genuine TIE.** ADF answers "prove what was built matches spec" (Merkle root, `verify_proof.py` returns VERIFIED/TAMPERED-naming-the-file) — Lovable structurally cannot. But ADF's seal is **keyless** (tamper-*evident*, not unforgeable — `verify_proof.py` has no signature check), policy is *recorded* not *enforced*, there's no SBOM (lockfiles skipped, `proof_of_build.py:119`), and no revocation. Lovable decisively owns the org-compliance half (SOC2/ISO/DPA/SSO/RBAC/audit-logs) ADF has *none* of.

**Performance — Lovable leads the felt number.** ADF re-runs the *full* verify pipeline on every edit (no HMR/incremental/persistent dev server — grep-confirmed). Correcting the comparison: code-gen is *more* non-deterministic than stated — `call_anthropic` sends **no temperature** (default ~1.0); `temperature:0.2` is **NVIDIA-only**; the Messages API has **no `seed`**. The "bit-reproducible build, a moat Lovable can't match" bar is **partly infeasible** and must be downgraded to "deterministic *proof* over whatever was generated." Only the governance layer is truly deterministic.

**Cost — TIE, but "$0" is misleading.** Verified: the free NVIDIA path built **0/3** in the recorded bench (`build-nvidia.json`: todo/kanban/expense-tracker all `built:false`, 0 tokens, timeout); the real governed `$0.37/3-app` result used **paid cloud Claude**. Cost is tracked but **never sealed** — the `$0.37` is a hardcoded string in `scorecard-input.json`. A sealed USD receipt is a winnable wedge Lovable's opaque credits can't match.

**Iteration DX — Lovable leads.** ADF's loop is governed ($0/offline/policy-checked/proof-resealed) but batch-grained, single-player, localhost-only; edit guards default to `warn` (overwrites *written*), so even the governance lead is under-enforced.

**Deploy — Lovable owns it.** ADF has *nothing* on the literal prompt→public-URL axis (zero tunnel/hosted path, grep-confirmed). Its only seam is a self-verifying export + air-gap guarantee. A proof is not a URL.

**Integrations — Lovable owns it.** ADF ships one embedded offline data plane and *zero* external integrations. For any app that takes a card / logs in with Google / sends email / serves concurrent traffic, ADF literally cannot today.

**Breadth + mobile — honest split.** ADF is the *only* one emitting native-target code (Lovable is web-only output) with governed light/dark theming (`no_raw_hex` enforced) and sealed render facts (web + opportunistic real iOS screenshot). Trails on: no signed `.ipa/.aab` in the seal, Android has a toolchain hook but **zero render attestation** (iOS-proven / Android-unproven), and the stale-proof bug undercuts the "governed theming proven per app" claim.

---

## Prioritized roadmap

**Wave 1 — Make the moat HONEST (days, mostly seam tweaks).** Hard-gate the policy (`ADF_POLICY=strict`, gate critical rules at *both* line 2243 and 2296 — the verdict's correction: it's two edits, not one); re-seal `mobile-auth-login` + add `.adf-proof/history.jsonl` revocation; add the executed authorization proof (401/200) to `feature_shapes.py`; fix stale docs.

**Wave 2 — Make it UNFORGEABLE + close real holes (~1 week).** Ed25519-sign the merkle_root (~30 lines, biggest moat win); seal an SBOM from package-lock; ship a *tested* `templates/expo-rn/src/auth.ts` (real expo-crypto SHA-256 + CSPRNG) and rewire `_MOBILE_CONTRACTS[auth]` to import it + a rule failing `Math.random()`-derived tokens; add an owner-scoping policy rule (ADF's static answer to RLS); harden detectors (entropy fallback, security-headers).

**Wave 3 — Make the governed loop FEEL fast + carry a sealed receipt (1–2 weeks).** Incremental verify (`vitest related` + targeted render, full build behind the seal only); seal a cost/USD receipt + budget-abort via the existing `estimate_tokens()`; Android render attestation symmetric to iOS; lower-variance generation where supported + honest determinism messaging.

**Wave 4 — Governed share/integrations WITHOUT Lovable's failure modes (weeks, opt-in).** `adf serve` + in-browser `verify.html` (SubtleCrypto) on the user's static host; payments/email/storage as governed server-side adapters (per-integration egress allowlist, `.adf-secrets`, `no_secrets` over the client bundle). **Do NOT** chase managed CDN/Postgres/SOC2 — off-wedge.

---

## Honest risks (where "10x" is marketing, where the moat is thin, what needs the user's infra)

- **"10x across the board" is false.** It's real only on governance, narrowly on security. Pitch the wedge, not the board.
- **Keyless seal** = the app matches its *own* seal, not "ADF issued it." Until Ed25519 lands, "cryptographic proof" overstates it.
- **Advisory gate** = "we label insecure apps," not "we won't ship them." The cheapest fix, not yet shipped.
- **Shipped mobile auth is broken** (FNV-1a + `Math.random()`) — the exact failure class ADF markets against, in its own proven app.
- **Bit-reproducible code-gen is infeasible** (no `seed`, benched backend at temp ~1.0). Sell deterministic *governance*, not reproducible code.
- **"$0/offline" is misleading** on the proven path — free backend built 0/3; the real result used paid Claude.
- **Org-compliance, deploy, and integrations need the USER's infra/business** (SOC2/SSO are absent and correctly deferred; deploy needs the user's host; payments/email need the user's Stripe/SMTP).
- **Regex detectors ≠ proof of safety** — same epistemic trap as Lovable's RLS-presence scanner; the entropy gap *already* produced a false-non-compliant seal.
- **No SBOM** — a swapped allowlisted dep passes the seal.
- **The felt perf loss (edit latency) is the hardest cheap fix** — the React single-origin design makes true HMR a real architecture change; position as "within ~2–3x of Lovable while $0/offline/proven," not "faster."