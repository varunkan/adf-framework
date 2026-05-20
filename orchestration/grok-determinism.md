# Grok Determinism — Side-car (Principles A–E)

Read after `constitution.md` on every agent spin. Grok pack source: `tools/ultimate-ai-dev-framework/`.

## Principle A — Minimum information

- Pass **at most 4 files** per agent invocation (plus this side-car when needed).
- Never pass full chat history or repo-wide dumps.
- Conductor destroys broad context after each phase.

## Principle B — Graph ordering (DAG)

- Work is declared in `specs/<id>/task-graph.yaml` with `depends_on` per node.
- Execution follows **topological order**; parallel only among ready nodes (v3.1 batch).
- `validate_adf_artifacts.sh` rejects cycles and orphan nodes.

## Principle C — Proof before progress

- No phase advance without artifacts on disk and machine/BMAD verification.
- LLM self-attestation is not proof; scripts and tests are.

## Principle D — Tiny safe steps (30–90 seconds)

- Each micro-task in `specs/<id>/tasks/task-NNN.md` targets **30–90 seconds** of agent time.
- `max_duration_seconds` must be ≤ 90.
- Explicit pre/post conditions and allowed paths required.

## Principle E — Isolation

- Each micro-task runs in a **fresh git worktree** via `scripts/orch/adf_worktree.sh`.
- No cross-task file visibility; destroy worktree after successful commit.

## §3 Coding rules (non-negotiable)

1. **TDD order:** RED → GREEN → REFACTOR → commit. No production code before failing test.
2. **One responsibility** per file/function; names describe the job.
3. **No magic numbers** — use named constants or config.
4. **Explicit error handling** — no bare catch/ignore.
5. **Security:** validate input; no secrets in logs; prepared statements for DB.
6. **Performance:** simple first; optimize only after measurement.
7. **Documentation:** public APIs documented; update docs when behavior changes.

## §7 Efficiency targets

- Agent context target: **~400 tokens** (runner logs `context_budget_warn` when exceeded).
- Micro-task wall-clock target: 30–90 seconds per task file scope.
- Feature (10–20 tasks): under 15 minutes wall-clock with parallel dispatch (v3.1).

## §9 Conflict precedence

1. `grok-determinism.md` (deterministic execution)
2. `.cursor/orchestration/constitution.md` (POS + RACI + coverage)
3. `specs/<id>/spec.md` → `plan.md` → `tasks.md`
4. Feature `state.json`

Human dashboard approval on phases 1–3 and 9 overrides automated unblock when explicitly required.

## Self-improvement (v3.2+)

After each feature, update `specs/<id>/lessons-learned.md`. Constitution changes require human RFC approval.
