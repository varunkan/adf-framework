# ADF — Vision, Requirements & Roadmap

> **Provenance.** Authored 2026-06-17 by a 3-perspective design panel (product
> strategy · mobile architecture · reliability skeptic → synthesis), every claim
> verified against the real repo. This is the durable anchor for ADF's North Star:
> the best agentic framework for building **any web + iOS/Android app**, verifiable
> and governed. EARS requirements are written to be testable; the capability DAG
> names the ordered nodes; §5 is the first node implemented test-first.

I now have every cited pattern verified against the real repo. I have enough to produce the document. The detect_stack manifest-authoritative behavior, the StackProfiles/VerifyDispatch/ScaffoldThenDiff test classes, the `_react_verify` stage order, visual_verify's skip-unless-strict, the policy gate's web-file-type coupling, and proof_of_build's opaque `stack` are all confirmed.

---

# ADF — Vision, Requirements & Roadmap

*Maintainer doc. Every claim cites a real file. Web-shaped facts verified at `scripts/orch/{agent_runner,visual_verify,policy_gate,proof_of_build,feature_shapes}.py` and `scripts/orch/test_agent_runner.py`.*

---

## 1. Vision

ADF is the best **agentic framework** for building **any web AND iOS/Android app from a prompt** — not a terminal coding agent, but a governed, end-to-end app-generation framework where every build is **verifiable** (a cryptographic offline-recomputable Proof-of-Build), **gated** (deterministic policy rules sealed into the proof), and **rendered-checked** (the app is proven to actually mount, not just return HTTP 200). The $1B thesis, honestly: regulated, IP-sensitive, and enterprise buyers will pay enterprise prices to **prove what their AI built** across web and mobile — a guarantee hosted black boxes (Lovable, v0, Bolt, Replit Agent) structurally cannot offer — but that revenue requires a commercial layer (accounts, billing, multi-tenant isolation) that **does not exist in the repo today**.

---

## 2. What ADF is today vs the vision

| Dimension | Today (verified in repo) | Vision | Gap |
|---|---|---|---|
| **Platforms** | **Web only.** Two StackProfiles in `agent_runner.py:564`: `STACK_STDLIB` (single-file Python) and `STACK_REACT` (`react-vite-sqlite`, default). One template (`templates/react-vite-sqlite`). Zero mobile tokens. | Web + iOS + Android | **THE headline gap.** No `expo`/`react-native` stack, no native verify, no simulator render gate. |
| **Generation seam** | Clean `_STACK_PROFILES` registry + `detect_stack` (manifest-authoritative, `agent_runner.py:255`) + `build_messages`/`verify_app` dispatch + `_STACK_TEMPLATES` scaffold-then-diff. | Same seam, N stacks | Seam is genuinely built for this; adding a stack = 1 constant + 1 detect signal + `_build_messages` + `_verify` + 1 registry entry + 1 template. |
| **Trust moat** | **Real & tested.** Proof-of-Build (`proof_of_build.py`: SHA-256 Merkle over files + `@spec` + `@build` verdict, offline-recomputable, treats `stack` as opaque). Render gate (`visual_verify.py:99 assess_dom` drives headless Chrome `--dump-dom`). | Same guarantees on mobile | **Render gate is web-shaped** (HTML DOM + localhost + Chrome) — does NOT port to native. Proof-of-Build **does** port cleanly. |
| **Policy gate** | 5 rules, **web-file-type-coupled** (`policy_gate.py:137` scans only `.html`; `:148` only `.sql`; `:165` only `package.json`). | Platform-aware, fail-closed | On a mobile app every rule passes **vacuously** (scans nothing) → false "policy: compliant" seal. Must be fixed before any mobile seal. |
| **Commercial layer** | **None.** No pricing/billing/accounts/multi-tenant isolation anywhere. README sells $0/self-hosted. | Paid hosted/enterprise tier | $1B is 100% aspirational; technology moat earned, commercial moat unbuilt. |

**Verdict: ~30% real, ~70% aspirational** against "the best framework for any web+mobile app, $1B."

---

## 3. EARS Requirements

### 3.A — Capability (web + mobile generation)

- **C1** — WHEN `build_messages(fid, ctx, stack)` is called with a registered stack, the system SHALL return a `(system, user)` prompt pair tailored to that stack, using the `<<<FILE: path>>>…<<<END>>>` protocol. *(mirrors `agent_runner.py:270`)*
- **C2** — WHEN `stack == STACK_EXPO` (`"expo-rn"`), the system SHALL emit a prompt naming **Expo + React Native + react-native-web + TypeScript + expo-sqlite**, SHALL forbid DOM-only React (`react-dom`/`index.html` rendering), and SHALL inject the `feature_shapes.skeleton_contract` the same way the react path does. *(extends `_react_build_messages`)*
- **C3** — WHEN a new stack is registered, the system SHALL add exactly one entry to `_STACK_PROFILES` with `{name, build_messages, verify}` and SHALL require no change to crew, dashboard, proof, or policy code. *(`agent_runner.py:564`)*
- **C4** — WHEN `detect_stack(app_dir)` runs, the system SHALL treat `.adf-stack.json` `stack` as authoritative over any file signal (`app.json`, `package.json`). *(`agent_runner.py:255` — `.adf-stack.json` already wins)*

### 3.B — Trust / Verification (must hold for mobile too)

- **T1** — WHEN any stack's verify runs, the system SHALL surface each failing stage's output verbatim and attributed (e.g. `BUILD FAILED (tsc --noEmit && vite build): …`), and SHALL NEVER emit a stack trace as the result. *(`agent_runner.py:1104` `_react_verify`)*
- **T2** — WHEN an app is missing its entrypoint, verify SHALL return `(False, <message naming the missing file>)`, not raise. *(tested `test_react_verify_missing_package_json_is_clear_error`)*
- **T3** — WHEN no render toolchain is present (no Chrome for web; no simulator for mobile) and strict mode is off, the render gate SHALL **SKIP** and return ok=True, recording `status='not-evaluated'` — never a silent `rendered`. *(`visual_verify.py:159`, `ADF_VISUAL_VERIFY=strict`; mobile analog gated `ADF_MOBILE_NATIVE`)*
- **T4** — WHEN the render gate runs, the system SHALL assert real content mounted (`assess_dom`: text ≥3 chars AND ≥1 interactive, or ≥4 elements) and SHALL return the specific missing controls per feature shape (`check_expected_dom`). *(`visual_verify.py:99,120`)*
- **T5** — WHEN a proof is sealed, the system SHALL Merkle-hash all editable source files + `@spec` + `@build` verdict with `stack` as an opaque field, offline-recomputable to VERIFIED/TAMPERED. *(`proof_of_build.py:59,73`)*
- **T6** *(NEW — fail-closed policy)* — WHEN a policy rule cannot meaningfully run for a stack (its target file types are absent), the system SHALL record `status='not-evaluated'` in the sealed verdict, NEVER a silent `pass`. *(closes the `policy_gate.py:137/148/165` vacuous-green hole — currently unmet)*

### 3.C — Determinism

- **D1** — WHEN a stack has a template, the build SHALL scaffold from `templates/<stack>/`, strip the sample feature, and instruct the model to emit ONLY feature files. *(`scaffold_app` `agent_runner.py:477`; tested `test_scaffold_app_copies_wiring_and_strips_sample`)*
- **D2** — WHEN generating, the system SHALL reuse `feature_shapes.classify()` to drive a fixed shape contract (crud-list/form/dashboard/single-record/auth), removing the highest-variance surface. *(`feature_shapes.py:90`)*
- **D3** — WHEN re-verifying, the system SHALL reuse warm `node_modules` cloned from the template (skip `npm ci`) to keep builds reproducible and offline. *(`agent_runner.py:536`)*

### 3.D — Business / Operability

- **B1** — WHEN a build completes for any stack, the summary SHALL emit stack-correct run/test hints. *(`agent_runner.py:1759` — currently react-only branch)*
- **B2** *(NEW)* — WHEN the offline/$0 path runs, the system SHALL document a per-stack **capability matrix** stating what builds offline, what renders, and what each policy rule evaluates vs `not-evaluated`. *(unmet; honest-scope requirement)*
- **B3** *(NEW, gated)* — WHEN a native distributable is requested, the system SHALL require an explicit online-signing scope and SHALL NOT claim a signed `.ipa`/`.aab` from the deterministic offline path. *(prevents the "green check that lies")*

---

## 4. Capability DAG (here → vision)

```
[done] Web seam: stdlib + react-vite-sqlite stacks, proof, policy, render gate
   │
   ├─► M1  expo-rn StackProfile: build_messages + verify CONTRACT + dispatch (mocked)   [BUILDABLE NOW] ★ FIRST
   │      └─► M2  templates/expo-rn/ scaffold (expo + react-native-web + Fastify API)   [buildable now]
   │             └─► M3  expo-web export+boot+EXISTING render gate end-to-end           [buildable now; needs npm]
   │                    └─► M4  mobile feature_shapes contracts (View/Text/TextInput/Pressable)  [buildable now]
   │                           └─► M5  native verify stage (eas/xcodebuild/gradle), skip-unless-strict  [NEEDS TOOLCHAIN]
   │                                  └─► M6  simulator render-equivalence gate (a11y-tree assert)  [pure core NOW / live = NEEDS SIM]
   │                                         └─► M7  signed device build + store submit  [NEEDS INFRA: Xcode/Mac/signing/EAS]
   │
   ├─► X1  policy_gate fail-closed: not-evaluated on unknown stack + mobile detectors (plist/ATS/Pod/Gradle)  [BUILDABLE NOW] ‼ trust-critical
   ├─► X2  per-stack capability matrix doc (honest offline/$0 scope)                     [buildable now]
   └─► X3  proof_of_build: confirm binary assets / platform manifests are sealed         [buildable now]

[$1B track — parallel, mostly NOT code]
   P1  hosted Proof-as-a-Service control plane (accounts, dashboards)   [NEEDS INFRA]
   P2  billing + multi-tenant isolation (Docker/VM-per-app, egress policy)  [NEEDS INFRA; security-critical]
   P3  one paying regulated WEB customer on the existing moat            [GTM, no code]
```

**Sequencing note:** **X1 (fail-closed policy) gates M3+** — no mobile app may be sealed until the policy gate reports `not-evaluated` instead of vacuous pass, or the proof signs a governance check it never ran.

---

## 5. The FIRST node to build NOW — **M1: `expo-rn` StackProfile contract + dispatch (mocked)**

The single highest-leverage node that is **fully implementable and unit-testable on a normal dev box this iteration**, with zero device/simulator/npm dependency. It mirrors the existing `StackProfiles` / `VerifyDispatch` / `ScaffoldThenDiff` test classes exactly. It unblocks every downstream mobile node (M2–M7). It does **not** claim a signed artifact — "verified" will later mean *typechecks + tests + renders on expo-web*, an honest claim.

### EARS (precise, for M1)

1. WHEN stack profiles register, `_STACK_PROFILES` SHALL include `STACK_EXPO = "expo-rn"` with `build_messages` and `verify` callables.
2. WHEN `detect_stack(dir)` reads `.adf-stack.json` with `stack:"expo-rn"`, it SHALL return `"expo-rn"` (manifest authoritative over `package.json`/`app.json`).
3. WHEN `stack_profile("expo-rn")` is called it SHALL return the mobile profile; `stack_profile("bogus")` SHALL fall back to `STACK_STDLIB` without raising.
4. WHEN `build_messages(fid, ctx, stack="expo-rn")` is called it SHALL return a 2-tuple naming **React Native + Expo + react-native-web + expo-sqlite + TypeScript** and the `<<<FILE:>>>` protocol, differing from both react and stdlib prompts, and SHALL NOT contain `"Python 3 standard library"`.
5. WHEN `_STACK_TEMPLATES["expo-rn"]` is consulted it SHALL map to `"expo-rn"` (template body = M2).
6. WHEN `_expo_verify` runs without a native toolchain and `ADF_MOBILE_NATIVE != strict`, it SHALL SKIP the native stage as ok=True; WHEN `=strict` and toolchain absent, it SHALL fail with an explicit "native build required, toolchain not found" message.
7. WHEN `_expo_verify` runs on an app missing its entrypoint, it SHALL return `(False, <message naming app.json/package.json>)` with no traceback.

### RED test plan — add `class MobileStackProfile(unittest.TestCase)` to `scripts/orch/test_agent_runner.py`

| Test | Assertions (RED until M1 lands) |
|---|---|
| `test_expo_stack_registered` | `ar.STACK_EXPO == "expo-rn"`; `"expo-rn" in ar._STACK_PROFILES`; profile has `"build_messages"` and `"verify"` keys. |
| `test_detect_stack_reads_expo_manifest` | Write `.adf-stack.json` `{"stack":"expo-rn"}` (+ conflicting `package.json`); `ar.detect_stack(dir) == ar.STACK_EXPO` (manifest wins). |
| `test_stack_profile_lookup_and_unknown_fallback` | `ar.stack_profile(ar.STACK_EXPO)["name"] == "expo-rn"`; `ar.stack_profile("bogus")["name"] == ar.STACK_STDLIB` (no raise). |
| `test_build_messages_emits_expo_prompt` | `blob = sys+usr` from `build_messages("kb", ctx, stack=ar.STACK_EXPO)`; assert `"React Native"`, `"Expo"`, `"react-native-web"`, `"expo-sqlite"` in blob; `"<<<FILE:"` in blob; `"Python 3 standard library" not in sys`; blob differs from the react blob. |
| `test_template_mapping` | `ar._STACK_TEMPLATES[ar.STACK_EXPO] == "expo-rn"`. |
| `test_stack_profile_exposes_expo_verify_callable` | `ar.stack_profile(ar.STACK_EXPO)["verify"] is ar._expo_verify`. |
| `test_expo_verify_missing_entrypoint_is_clear_error` | `ok, out = ar.verify_app(empty_dir, ar.STACK_EXPO)`; `ok is False`; `("app.json" in out or "package.json" in out)`; `"Traceback" not in out`. |
| `test_verify_app_detects_expo_from_manifest` | Write only `.adf-stack.json` `{"stack":"expo-rn"}`; `ar.verify_app(dir)` (no stack arg) → expo pipeline ran (proven by the expo-specific missing-entrypoint message), not stdlib. |
| `test_native_build_skipped_when_toolchain_absent_and_not_strict` | Monkeypatch native-toolchain locator → `None`; unset `ADF_MOBILE_NATIVE`; native-stage helper returns `(True, <skip msg>)`. |
| `test_native_build_strict_fails_when_toolchain_absent` | Same monkeypatch + `ADF_MOBILE_NATIVE=strict` → `(False, <msg mentioning native build required>)`. |

**Implementation surface (all in `scripts/orch/agent_runner.py`):** add `STACK_EXPO` constant near line 242; add `_expo_build_messages` near the react one; add `_expo_verify` near line 1104 (deterministic stages stubbed/fail-closed for now, native stage gated by `ADF_MOBILE_NATIVE`); add `_STACK_TEMPLATES[STACK_EXPO] = "expo-rn"` at line 455; add the registry entry at line 564 and the `["verify"]` wire-up near line 1146; add the `STACK_EXPO` branch in `verify_app` at line 1138. **No proof/policy/dashboard change** (they treat `stack` as opaque). Run: `python -m pytest scripts/orch/test_agent_runner.py -k MobileStackProfile` → RED, then implement → GREEN.

---

## 6. Honest $1B reality check

**Is it realistic? Not on the current trajectory, and not soon.** The *technology* moat is genuinely earned and tested — offline cryptographic Proof-of-Build, sealed policy verdicts, a render gate that catches white-screens, air-gapped builds, own-your-code export. But three things are true and unflattering: (1) ADF is **web-only**, so the "any web+mobile app" claim is presently false; (2) there is **zero commercial scaffolding** — no billing, accounts, hosting, or multi-tenant isolation — and the repo's own framing ($0/self-hosted) is *anti-revenue*; (3) the independent `JUDGE_REVIEW` already found the real capability number is **cloud Opus ~$0.37/app, with local 32B/70B timing out** — so even the web $0 headline is partly aspirational, and mobile codegen is strictly harder than what already times out.

**Timeline (honest):** mobile *generation+verify contract* (M1–M4) is weeks. A trustworthy *mobile render-equivalence gate* (M6) and *signed device builds* (M7) are quarters and need a Mac/Xcode/Android SDK/signing custody that breaks the offline/$0 posture. The *commercial layer* (P1–P3) is a multi-quarter program of work that is mostly **not code** (GTM, SOC2, support, infra spend). A credible path to $1B is **years**, contingent on revenue, not engineering alone.

**The 3 hard prerequisites (in order):**
1. **Re-earn the render gate on-device.** The Chrome-DOM gate (`visual_verify.py`) does NOT port to a native binary. Without a simulator a11y-tree render assertion, the mobile Proof-of-Build seals unverified builds — the moat becomes a liability.
2. **Make the policy gate fail-closed (X1) before any mobile seal.** Today every rule (`policy_gate.py:137/148/165`) passes *vacuously* on a non-web app — sealing "policy: compliant" on an app with a hardcoded key in `Info.plist` it never read. That single false governance assurance would destroy the enterprise wedge the day a buyer finds it.
3. **Prove willingness-to-pay.** The entire $1B thesis rests on regulated/IP-sensitive buyers paying a premium for offline-verifiable provenance. **No paying customer exists in the repo.** This is the riskiest unvalidated assumption — and the only one that decides whether ADF is a $1B product or a better free framework.

**Cheapest measurable milestone that PROVES the mobile direction before betting big:** a **mobile render-equivalence spike** — boot a trivial Expo app on **expo-web** and run it through the **existing, unchanged** `visual_verify.assess_dom` + `check_expected_dom` (react-native-web emits real `<input>`/`<button>` DOM). If the existing render gate goes green on an Expo app with **zero new browser code**, the cheapest possible proof that the moat survives the web→mobile jump is in hand — for the price of one template and one boot, not a quarter of native codegen. M1 (this iteration's first node) is the test-first foundation that spike rides on.

---

**Key files referenced:** `scripts/orch/agent_runner.py` (`_STACK_PROFILES`:564, `detect_stack`:255, `build_messages`:270, `verify_app`:1133, `_react_verify`:1104, `_STACK_TEMPLATES`:455, `scaffold_app`:477, warm-deps:536), `scripts/orch/visual_verify.py` (`assess_dom`:99, `check_expected_dom`:120, skip-unless-strict:159), `scripts/orch/policy_gate.py` (web-coupled rules:137/148/165), `scripts/orch/proof_of_build.py` (opaque `stack`:59/73), `scripts/orch/feature_shapes.py` (`classify`:90, shapes:25), `scripts/orch/test_agent_runner.py` (`StackProfiles`:77, `VerifyDispatch`:123, `ScaffoldThenDiff`:158).