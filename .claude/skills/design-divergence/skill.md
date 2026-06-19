---
name: Design Divergence
description: Use when starting something new — explore 2–5 design options with trade-offs and pick one BEFORE writing a plan or code
---

## Design Divergence

Even "simple" tasks hide unexamined assumptions. Before convergent planning, diverge:
generate multiple design options, weigh them, and choose deliberately. ADF can record
the chosen-from-options as the advisory `design_options_considered` fact
(`scripts/orch/process_facts.py::record_design_options`).

### The discipline

1. **Explore context.** Read the requirement, existing files, recent commits.
2. **Diverge.** Propose 2–5 genuinely distinct approaches (e.g. MVP-first, risk-first,
   reuse-first), each with its trade-offs (complexity, blast radius, cost).
3. **Choose.** Pick one and write a one-line rationale for WHY over the runners-up.
4. **Converge.** Only now write the spec/plan and build.

### How to run it in ADF

- A real divergence step emits `{options, chosen, rationale}`; record it with
  `record_design_options(app_root, options, chosen, rationale)`. The fact is `proven`
  only with ≥2 REAL options — ADF never fabricates options, and a single idea seals as
  `skipped`.
- This is advisory by design: it is never enforced (enforcing it would invite padding
  the option list to clear a gate).

### Common mistakes

- Jumping straight to the first idea. → You lock in unexamined assumptions; one bad
  default propagates through the whole build.
- Fake divergence (three near-identical options). → Self-defeating; the value is in
  genuinely different trade-offs.

### Hard gate

`design_options_considered` is honest ONLY when `options` is a real captured divergence
output — never the model self-asserting "I considered 3 options" in its file output.
