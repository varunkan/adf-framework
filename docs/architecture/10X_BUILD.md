# ADF 10× — System Design, Contracts, DAG & Test Strategy

> **Canonical source of truth.** Every implementation task reads its relevant
> section + the contract it implements before writing code. Never guess an
> interface. If reality diverges from this doc, fix the doc first, then the code.

---

## §0 — North Star (immutable; check every decision against it)

**Goal:** ADF 10× better than Lovable = (1) **credible capability** — generate real
**React+Vite+Tailwind+SQLite** multi-file apps; (2) **the governed/local moat** —
verifiable, self-hosted, offline-capable, $0-crew, agent-operable, audit-sealed.

**Review rule:** at every stage boundary, ask: *does this still serve the goal? are
we building the right product?* Drift → stop, correct, log the decision.

**Definition of done for the FOUNDATION milestone (Phases 0–1):** a user types one
prompt → ADF generates a real React+Vite+Tailwind+SQLite app → it builds, tests
pass, boots → renders live in the dashboard App tab → a one-box edit hot-refreshes
it → data persists in SQLite. All under the existing proof/integrity pipeline.

---

## §1 — System Design (architect-grade)

### 1.1 Component model (what changes vs. today)
```
 Dashboard (Flutter web)        UNCHANGED: App-tab iframe, chat, one-box edit
        │ HTTP
 Orchestration API (Dart)       + stack on feature state; + /edit already; AppRunner multi-stack
        │ spawns
 Runner (Python agent_runner)   + StackProfile: generate/verify/boot/edit per stack
        │ writes + runs
 apps/<id>/  (generated)        NEW shape: React+Vite+Tailwind front + Fastify+SQLite server
        ▲ reads
 templates/react-vite-sqlite/   NEW: checked-in working scaffold (scaffold-then-diff)
 Crew + spec pipeline           UNCHANGED (stack-agnostic): produces spec/plan/tasks/tests
 Integrity + audit + proof      EXTENDED later (Phase 4): proof bundle ships WITH the app
```

### 1.2 The generated-app architecture (the key decision)
A generated app is **one Node process** that serves everything on `PORT`:
- **Fastify** server: serves the built Vite `dist/` (static) + `/api/*` (JSON) and
  owns the SQLite file via **better-sqlite3** (synchronous, zero-config, one file).
- Frontend: **React + Vite + TypeScript + Tailwind**, built to `dist/`, talks to
  `/api/*` with relative same-origin fetch.
- One process, one port → fits AppRunner's existing spawn-on-PORT + iframe model
  with near-zero change. (Vite dev-server + HMR is a Phase-2 optimization, not v1.)

Rationale: minimizes moving parts, keeps same-origin (no CORS), and means the
**existing** live-preview + one-box-edit + auto-refresh machinery works unchanged.

### 1.3 The runner pipeline (state machine; scaffold-then-diff)
```
 select stack ─▶ scaffold (copy template) ─▶ plan files (from crew tasks)
   ─▶ generate per file in dep order (schema→data→api→components→app→tests)
   ─▶ install (npm ci, cached) ─▶ verify (typecheck→build→vitest→boot)
   ─▶ PASS �/ FAIL→self-heal (feed failing file+error) → re-verify (≤N) → blocked
```
Per-file generation (not 500-line one-shot) is what makes current LLMs reliable.

### 1.4 Preview runtime & isolation (security — generated code runs!)
Threat model: generated Node code + npm deps execute locally. Posture for v1
(local, trusted operator): **(a)** deps are PINNED to a vetted allowlist in the
template's `package.json` + committed lockfile → `npm ci` only (no arbitrary
install); **(b)** server binds **127.0.0.1** only; **(c)** child process with a
cwd jail under `apps/<id>/`, killed/reaped by AppRunner; **(d)** an idle/lifetime
cap. Docker-per-app isolation + a network-egress policy gate are deferred to the
governance phase (Phase 4) for untrusted/multi-tenant use.

### 1.5 npm-install latency (the honest cost)
First `npm ci` is ~1–3 min. Mitigation: a **warm template store** — the template is
installed once; each app reuses it via a shared store / copy-on-write `node_modules`
(or `npm ci --offline` against a prewarmed cache). Target per-app install < 10s after
the first.

---

## §2 — Contracts (exact interfaces; the anti-hallucination spec)

### C1 — `.adf-stack.json` (each app carries this; the runner writes it, AppRunner reads it)
```json
{ "stack": "react-vite-sqlite",
  "build_cmd": ["npm","ci","--no-audit","--no-fund"],
  "post_build": ["npm","run","build"],
  "run_cmd": ["node","server/index.js"],
  "port_env": "PORT",
  "health_path": "/" }
```
`stdlib` apps either carry `{stack:"stdlib", run_cmd:["python3","server.py"], ...}`
or omit the file (AppRunner defaults to stdlib). **No language guessing.**

### C2 — Runner StackProfile (Python, `scripts/orch/agent_runner.py`)
- `STACK_STDLIB="stdlib"`, `STACK_REACT="react-vite-sqlite"`, `DEFAULT_STACK` (env `ADF_STACK`).
- `detect_stack(app_dir) -> str` — reads `.adf-stack.json` if present, else package.json→react, else stdlib.
- `current_app_files(app_dir) -> list[(relpath, content)]` — ALL source files (skip `node_modules/dist/build/__pycache__/.git`, lockfiles); capped (≤60 files / 200KB).
- `build_messages(fid, ctx, stack) -> (system, user)` — dispatch to `_stdlib_build_messages` / `_react_build_messages`.
- `build_edit_messages(fid, files, instruction, stack)` — multi-file diff (stack-agnostic body).
- `stack_profile(stack) -> dict{name, verify, boot, ...}` — fallback to stdlib for unknown.
- `verify_app(app_root, stack) -> (ok, output)` — dispatch: stdlib=`python3 test_app.py`+boot; react=`npm ci`→`tsc --noEmit`→`vite build`→`vitest run`→boot.

### C3 — AppRunner (Dart, `tools/orchestration_server/lib/app_runner.dart`)
- `resolveStack(id) -> {run_cmd, build_cmd, port_env} | null` — reads `apps/<id>/.adf-stack.json`; falls back to `server.py`→python.
- `ensureRunning(id)` — if `build_cmd`/`post_build` present and not yet built, run them once (cached marker), then spawn `run_cmd` with `PORT`, wait-for-listen, return `{available,url,port}`. Same return contract as today.

### C4 — Template (`templates/react-vite-sqlite/`) — must satisfy:
`npm ci && npm run build && PORT=NNNN node server/index.js` → GET `/` 200 (serves the
SPA) and `/api/health` 200. Ships: `package.json` (pinned), `vite.config.ts`,
`tsconfig.json`, `tailwind.config.js`, `index.html`, `src/**` (App + a sample
feature), `server/index.ts`→built `server/index.js` (Fastify + better-sqlite3 +
static), `schema.sql`, `test/**` (vitest), `.adf-stack.json`, `README.md`.

### C5 — Feature stack selection (server + dashboard)
`POST /features` accepts `stack`; persisted in `state.json` (`state.stack`); runner
invoked with `ADF_STACK`/arg = that stack. Dashboard "New feature" picks stack
(default `react-vite-sqlite`).

---

## §3 — Dependency DAG (nodes = tasks, edges = deps; topological levels)

Granularity target ~30 min of focused agent work per node (the user's "30s" =
*atomic*; we split any node whose tests can't be written independently). Each node
has an explicit TEST GATE that must be RED before and GREEN after.

| Node | Task | Depends on | Test gate |
|---|---|---|---|
| **L0** | | | |
| `N1 stack-contract` | Write C1–C3 contracts into this doc + a JSON schema for `.adf-stack.json` | — | doc/schema lints |
| `N2 template` | Build `templates/react-vite-sqlite/` working scaffold (C4) | — | `template_build_test` (npm ci+build+boot→200) |
| `N3 npm-cache` | Warm-store strategy so per-app install < 10s | N2 | `install_speed_test` |
| **L1** | | | |
| `N4 runner-profile` | StackProfile + multi-file `current_app_files` + react build prompt (Python) | N1 | `test_agent_runner.StackProfiles` |
| `N5 runner-verify` | `verify_app` react pipeline (typecheck→build→vitest→boot) | N1,N2 | `runner_verify_react_test` |
| `N6 apprunner` | `resolveStack` via `.adf-stack.json` + per-stack build/run (Dart) | N1,N2 | `app_runner_test` (node app) |
| **L2** | | | |
| `N7 runner-generate` | Scaffold-then-diff generate flow (copy template→per-file gen→verify) | N2,N4,N5 | `runner_generate_react_test` |
| `N8 stack-select` | Persist `state.stack`; New-feature picker; thread to runner | N1,N6 | `stack_select_test` (server+widget) |
| **L3** | | | |
| `N9 e2e-build` | One prompt → React+Vite+SQLite app builds, boots, renders live | N6,N7,N8 | `e2e_build` (manual+script) |
| `N10 e2e-edit` | One-box edit hot-refreshes the multi-file React app | N9,N4 | `e2e_edit` |

Topological order: **L0 {N1,N2,N3} → L1 {N4,N5,N6} → L2 {N7,N8} → L3 {N9,N10}**.
Within a level, nodes are independent → parallel agents. Edges enforce order.

**STATUS (2026-06-15): FOUNDATION MILESTONE MET. ✅** N1,N2,N4,N5,N6,N7,N8,N9,N10
done + gated (N3 npm-warm-cache is the only optional/deferred node). The e2e gate
`scripts/test/e2e_react_app.py` proves the §0 definition of done end-to-end: one
prompt → a real React+Vite+Tailwind+SQLite app that builds (npm ci + tsc + vite +
vitest), boots exactly as AppRunner boots it (`node server/index.mjs` on PORT),
serves the SPA at `/`, round-trips its API with SQLite persistence, and a one-box
edit applies the smallest multi-file change + rebuilds + re-serves with the change
compiled into the live bundle (12/12 checks, ~8s, deterministic/offline).

**Adjustment policy:** if a node's implementation can't reach its green gate in one
agent pass, split it (e.g. N2 → N2a template-frontend, N2b template-server,
N2c template-tests) and re-topologize. Log the split in the Decision Log (§6).

---

## §4 — Test Strategy (red-first; gates at every boundary)

**Levels & when they run:**
- **Unit** — per node, immediately after that code unit. (`dart test <file>`,
  `python3 -m unittest`, `flutter test <file>`.)
- **System** — after a *system* is complete (a system = a coherent subsystem:
  the template app; the runner verify pipeline; AppRunner). Runs that subsystem in
  isolation against real inputs.
- **Integration** — when interdependent systems are wired (server stack-select +
  runner generate + AppRunner serve): create→build→serve through the real API.
- **E2E** — full path: prompt → crew → generate → verify → render → edit, in the
  live dashboard preview.

**Gate schedule:** write ALL test stubs first → run → confirm RED → implement node →
its unit test GREEN → when a system's nodes are green, run its system test → when a
level completes, run integration for that level → after L3, run E2E.

**Representative cases (red first):**
- N2: `template_build_test` — `npm ci && npm run build`; spawn `node server/index.js`
  on a free PORT; assert GET `/`→200 (HTML) and `/api/health`→200 JSON.
- N4: `StackProfiles` (already written, RED) — detect_stack, multi-file files,
  react-vs-stdlib prompt, registry fallback.
- N5: `runner_verify_react_test` — point `verify_app` at the template → returns ok;
  at a deliberately broken template (type error) → returns the tsc error.
- N6: `app_runner_test` node case — write a tiny `.adf-stack.json`+node server →
  `ensureRunning` builds (if needed) + serves 200; idempotent; restart; reap.
- N7: `runner_generate_react_test` — given a spec, the generate flow produces a
  buildable app dir (npm ci+build pass) with the expected file set.
- N8: server test (state.stack persisted + echoed) + a widget test (picker default).
- N9/N10: scripted E2E + manual live-preview verification.

---

## §5 — Execution & Context Engineering (how the agents run)

- **Isolated task contexts:** each DAG node is one subagent (Workflow `agent()`),
  spawned with ONLY: (a) the North Star (§0), (b) its node row + the exact contract
  it implements (§2), (c) the outputs/paths of its dependency nodes, (d) the
  specific file excerpts it edits. This keeps each context small and grounded →
  no hallucination.
- **Memory grounding:** agents cite this doc; the durable `adf-10x-north-star`
  memory survives compaction; a **Decision Log (§6)** is appended as choices are
  made so later agents inherit them.
- **Review gates (goal-alignment):** between levels, a review agent reads the
  current repo state + §0 and returns `on_track | drift(+correction)`. We do not
  advance a level on drift.
- **Test-first protocol:** the level's test stubs are written and confirmed RED
  before any implementation agent runs.
- **Context compaction:** when the working context grows large, compact; the North
  Star + this doc + the Decision Log are the rehydration anchors (nothing critical
  lives only in volatile context).
- **Verification ownership:** the orchestrator (not the implementing agent) runs the
  gate command after each node and refuses to mark a node done on a red gate.

---

## §6 — Decision Log (append-only; inherited by all agents)

- 2026-06-14 — Stack = React+Vite+Tailwind+SQLite; 10× bet = Balanced. (User.)
- 2026-06-14 — Generated app = single Fastify+better-sqlite3 process serving built
  Vite `dist/` + `/api/*` on PORT (not Vite dev-server) for v1 — fits existing
  AppRunner/iframe; HMR deferred.
- 2026-06-14 — `.adf-stack.json` manifest is the AppRunner↔runner contract (no
  language detection guessing).
- 2026-06-14 — Security v1 = pinned-dep allowlist + `npm ci` + loopback bind + cwd
  jail; Docker isolation deferred to Phase 4.
- 2026-06-15 — N5 done: `verify_app(app_root, stack)` dispatches stdlib vs react;
  react = npm ci → `tsc --noEmit && vite build` → vitest → `node` boot (GET `/` +
  `/api/health` = 200). Each stage's failure attributed verbatim for self-heal.
  Gates: fast `VerifyDispatch` units + slow `runner_verify_check.py` (real pipeline).
- 2026-06-15 — N7 done: scaffold-then-diff generate flow. The react generation
  prompt was CORRECTED to the real template shape — server is plain-ESM `.mjs`
  (never tsc-compiled), routes are RELATIVE to the `/api` prefix, db via
  `import {db} from '../db.mjs'`, tests are `*.test.mjs` using `app.inject`. Only
  `src/**` is TypeScript. `scaffold_app()` copies the template (keeps lockfile +
  `.adf-stack.json`), strips the sample feature, resets `schema.sql`; `main()`
  scaffolds a fresh react build then generates only the feature's files; self-heal
  + edit prompts are now stack-aware. Gate `runner_generate_check.py` drives real
  `main()` with a stubbed model → a verified, booting app (8/8 checks).
- 2026-06-15 — N8 done: per-feature stack selection (C5). `FeatureStore.stackFor`
  + `state.stack` persisted; `PhaseRunner.childEnvFor` injects `ADF_STACK` into the
  phase-7 runner subprocess; `POST /features` validates+echoes `stack`; dashboard
  New-feature picker defaults to react-vite-sqlite. Legacy features → stdlib.
- 2026-06-15 — N9+N10 done → FOUNDATION MILESTONE MET. `e2e_react_app.py` (stubbed
  model, real build/boot/HTTP) proves prompt → buildable+booting+serving+persisting
  React app, and a one-box edit that rebuilds + re-serves with the change in the
  live bundle (12/12). Also fixed a pre-existing stale dashboard test (requirement
  moved to the Overview tab when the App-tab iframe became the default).
- 2026-06-15 — MOAT shipped: **Proof of Build**. Every verified build is sealed
  into a Merkle root over (all source files) + (the spec, copied to
  `.adf-proof/spec.md`) + (the build verdict), written INTO the app as
  `.adf-proof.json` + human `PROOF.md`. `scripts/orch/proof_of_build.py`
  (compute/seal/verify) + `verify_proof.py` (offline CLI, `--json`) +
  `agent_runner.py` seals after verify. Recomputable offline by anyone — no
  network/trust/key — VERIFIED or TAMPERED-naming-the-file. Surfaced live in the
  dashboard: `GET /features/<id>/proof` (Dart `ProofCheck` relays the canonical
  python verifier) + a `ProofBadge` in the live-preview header (🔏 Verified·seal /
  TAMPERED, tap to re-verify). Gates: `test_proof_of_build.py` 10/10,
  `proof_of_build_demo.py` 5/5 (real app → seal → VERIFIED → tamper → TAMPERED),
  `proof_check_test.dart` 3/3, `proof_badge_test.dart` 3/3.
- 2026-06-15 — MOAT extended: **Policy Gates** (governance). Static, deterministic,
  offline checks over the app's source — `no_secrets`, `no_network_egress`,
  `offline_capable`, `no_plaintext_pii`, `dependency_allowlist` — each violation
  located to `file:line`. `scripts/orch/policy_gate.py` (`DEFAULT_POLICY`
  `adf-default-secure`; app `.adf-policy.json` > repo `adf-policy.json` > default;
  `check_policy`/`policy_summary` + `--json` CLI). The runner runs the gate after a
  verified build, writes `.adf-policy-report.json`, and SEALS the policy verdict into
  the Proof of Build (`_verdict_bytes` now folds `policy` into the Merkle root, so the
  governance verdict is tamper-evident too). Surfaced live: `ProofCheck.checkPolicy`
  re-runs the gate and rides along on `GET /features/<id>/proof`; `ProofBadge` shows
  🛡 (compliant) or ⚠ policy (violations, failing rules in tooltip). Single source of
  truth = Python; Dart shells the CLI (no drift). Gates: `test_policy_gate.py` 11/11,
  `policy_gate_demo.py` (template COMPLIANT + all 5 violations caught/located),
  `proof_check_test.dart` 4/4, `proof_badge_test.dart` 4/4. Why this matters: the
  proof now answers not just "is this the build that was verified?" but "does this
  build obey the org's security policy?" — the exact question regulated/IP-sensitive
  buyers ask, and the one Lovable structurally cannot answer.
- 2026-06-15 — Next: rest of governed/local moat (Data tab, share/export, proof+policy
  folded into the audit-bundle + agent-operable MCP for the react stack, air-gapped
  Ollama build) + Phase 5 ADF-vs-Lovable scorecard. N3 npm-warm-cache optional.
