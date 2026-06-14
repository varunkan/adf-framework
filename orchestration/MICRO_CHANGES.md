# Micro-changes (Track S) — fast path for one-line edits

The full ADF pipeline (spec → decompose → implement → review → repo-wide L100)
is the right amount of ceremony for a feature. It is the wrong amount for
changing a timeout constant in a 180-file codebase. ADF auto-detects tiny diffs
and downgrades them to a **scoped** path that keeps every gate but narrows each
one to what the change actually touches.

## What counts as "micro"

A working diff is micro when **both** hold:

| Knob | Default | Meaning |
|------|---------|---------|
| `ADF_MICRO_MAX_FILES` | `1` | at most this many changed files |
| `ADF_MICRO_MAX_LINES` | `10` | at most this many added+removed lines |

Detection is automatic (`micro_change_detect.sh`); nothing special to type.
Force the full pipeline with `ADF_SCOPE_MODE=repo`, or disable scoping entirely
with `ADF_SCOPE_MODE=off`.

## What "auto-scoped gates" means

The change's **blast radius** = the changed `lib/*.dart` files plus every file
that imports them, out to `ADF_BLAST_DEPTH` hops (default `1`). Import matching
covers both `package:<pkg>/...` and relative imports, and deliberately
over-includes — for a gate, an extra file is cheap and a missed dependent is
not.

| Gate | Full mode | Micro mode |
|------|-----------|------------|
| `coverage_gate` | 100% on all `lib/**` | 100% on **changed** files; dependents reported (gate them too with `ADF_MICRO_COVER_DEPS=1`) |
| `lint_gate` | `flutter analyze` whole project | `analyze` only the affected files |
| `security_gate` | scan all `lib/` | scan only the affected files |
| `performance_gate` | scan all `lib/` | scan only the affected files |

The rule that survives: **you still owe 100% coverage and zero lint/security/
performance violations on the code you changed.** What you no longer owe is
re-proving the entire repository to land a one-liner.

## Tools you can run by hand

```bash
# "What does this change touch?" — changed files + importers.
./scripts/orch/blast_radius.sh

# "Is this micro, and what's the scope?" — exits 0 if micro. --json for machines.
./scripts/orch/micro_change_detect.sh
./scripts/orch/micro_change_detect.sh --json

# Run a gate; it scopes itself automatically when the diff is micro.
./scripts/orch/coverage_gate.sh my-fix 100      # -> micro mode auto-selected
./scripts/orch/lint_gate.sh my-fix
./scripts/orch/security_gate.sh my-fix
```

Diff against a branch instead of the working tree with `ADF_DIFF_BASE`:

```bash
ADF_DIFF_BASE=origin/main ./scripts/orch/blast_radius.sh
```

## Tunable summary

| Env var | Default | Effect |
|---------|---------|--------|
| `ADF_DIFF_BASE` | `HEAD` | ref to diff against (uncommitted by default) |
| `ADF_MICRO_MAX_FILES` | `1` | file-count ceiling for micro |
| `ADF_MICRO_MAX_LINES` | `10` | line-count ceiling for micro |
| `ADF_BLAST_DEPTH` | `1` | import hops of dependents to include |
| `ADF_MICRO_COVER_DEPS` | `0` | also enforce 100% on dependents |
| `ADF_SCOPE_MODE` | `auto` | `auto` / `repo` (force full) / `off` (disable) |
| `ADF_AFFECTED_FILES` | — | explicit file list, skips git/import discovery |
