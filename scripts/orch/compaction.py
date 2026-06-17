#!/usr/bin/env python3
"""ADF context compaction — the `/compact` engine.

Long-lived agent tasks accumulate context: the runner's edit-mode payload (ALL
app files), self-heal history, and a feature's unbounded chat log. This module is
the single, deterministic, **offline** source of truth for budgeting that context
and compacting it — keeping the high-value content verbatim and folding the rest
into ONE reviewable summary, then recording the decision into a durable,
lossless-by-anchor context card.

It is complementary to `headroom` (the transparent byte-squeeze applied before a
model call): headroom crushes payload bytes; compaction makes a *logical, durable*
decision — which whole turns/files to keep, which to summarize — that a human (or
an auditor) can read back. Offline by default ($0, no model); an optional
`summarizer` callable only upgrades the prose.

CLI:
    python3 compaction.py [--json] [--apply] [--budget N] <dir>
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from dataclasses import dataclass, field

__all__ = [
    "estimate_tokens", "context_budget", "should_compact",
    "compact_messages", "compact_files", "compact_conversation",
    "write_context_card", "CompactionResult",
]

DEFAULT_BUDGET = 120_000
SUMMARY_PREFIX = "[compacted"
CONTEXT_DIR = ".adf-context"

# --- token estimation -------------------------------------------------------


def estimate_tokens(x) -> int:
    """A cheap, deterministic, model-agnostic token estimate (~chars/4 + a small
    per-message overhead). Accepts a str, a message/entry dict, a (path, content)
    file tuple, or a list of any of those. Documented as an estimate — used for
    budgeting decisions, not billing."""
    if x is None:
        return 0
    if isinstance(x, str):
        return (len(x) + 3) // 4
    if isinstance(x, dict):
        text = x.get("content") or x.get("text") or ""
        return ((len(text) + 3) // 4) + (4 if text else 0)
    if isinstance(x, tuple) and len(x) == 2 \
            and isinstance(x[0], str) and isinstance(x[1], str):
        return estimate_tokens(x[0]) + estimate_tokens(x[1])  # a file
    if isinstance(x, (list, tuple)):
        return sum(estimate_tokens(i) for i in x)
    return estimate_tokens(str(x))


def context_budget(env=None) -> int:
    """Token ceiling for assembled context. `ADF_CONTEXT_BUDGET_TOKENS` overrides
    the default; a malformed value falls back to the default."""
    env = os.environ if env is None else env
    raw = env.get("ADF_CONTEXT_BUDGET_TOKENS")
    if raw is None:
        return DEFAULT_BUDGET
    try:
        n = int(str(raw).strip())
        return n if n > 0 else DEFAULT_BUDGET
    except (TypeError, ValueError):
        return DEFAULT_BUDGET


def should_compact(items, budget=None) -> bool:
    budget = context_budget() if budget is None else budget
    return estimate_tokens(items) > budget


# --- result -----------------------------------------------------------------


@dataclass
class CompactionResult:
    items: list
    tokens_before: int
    tokens_after: int
    n_summarized: int = 0
    summary: str = ""
    did_compact: bool = False
    summarized_paths: list = field(default_factory=list)


# --- summarizers (deterministic, offline) -----------------------------------


_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?"
    r"(?:async\s+)?(?:function|class|const|let|var|def)\s+([A-Za-z_$][\w$]*)",
    re.M,
)


def _symbols(content: str, limit=6):
    seen, out = set(), []
    for m in _SYMBOL_RE.finditer(content):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
        if len(out) >= limit:
            break
    return out


def _first_line(text: str, n=70) -> str:
    for ln in (text or "").strip().splitlines():
        ln = ln.strip()
        if ln:
            return ln[:n]
    return ""


def _digest_messages(msgs) -> str:
    parts = []
    for m in msgs:
        role = m.get("role", "?")
        parts.append(f"{role}: {_first_line(m.get('content') or m.get('text') or '')}")
    body = "; ".join(parts)
    return body[:600]


# Structured-section summary templates (adopted from oh-my-pi's compaction-summary /
# compaction-update-summary; see docs/ADF_VS_OH_MY_PI.md §5.5). A model `summarizer`
# is fed these so the fold captures task STATE (goal/progress/decisions/next) instead
# of a flat first-line digest, and a re-fold updates the prior summary LOSSLESSLY.
COMPACTION_SUMMARY_TEMPLATE = (
    "Summarize the conversation so far into these exact sections, preserving every "
    "detail needed to continue the work. Output ONLY the sections:\n"
    "Goal: <the overall objective>\n"
    "Constraints: <hard requirements / decisions that must hold>\n"
    "Progress: Done — <…>; In Progress — <…>; Blocked — <…>\n"
    "Key Decisions: <choices made and why>\n"
    "Next Steps: <what to do next>\n"
    "Critical Context: <file paths, names, values needed to resume>"
)
COMPACTION_UPDATE_TEMPLATE = (
    "Update the previous summary with the new turns. You MUST preserve all "
    "information from the previous summary; only move items from In Progress to "
    "Done and append new facts — never drop earlier context. Output ONLY the same "
    "sections (Goal, Constraints, Progress, Key Decisions, Next Steps, Critical "
    "Context)."
)


def _summary_body(msg) -> str:
    """The body of a prior `[compacted N earlier turn(s)] <body>` summary message."""
    c = msg.get("content") or msg.get("text") or ""
    return c.split("] ", 1)[-1] if "] " in c else c


def _summary_prompt(turns_digest, carried="") -> str:
    """Wrap the foldable turns in the structured template for a model summarizer;
    on a re-fold (a prior summary exists), use the lossless update template."""
    if carried:
        return (COMPACTION_UPDATE_TEMPLATE
                + f"\n\n<previous-summary>\n{carried}\n</previous-summary>"
                + f"\n\n<new-turns>\n{turns_digest}\n</new-turns>")
    return COMPACTION_SUMMARY_TEMPLATE + f"\n\n<turns>\n{turns_digest}\n</turns>"


def _structured_digest(msgs, carried="") -> str:
    """Deterministic OFFLINE structured digest (no model call): Goal (first user
    turn), Progress (per-turn first lines), Next (last user turn) — carrying any
    prior summary forward so a re-fold keeps earlier state. Replaces the flat
    600-char digest so task state survives a fold even at $0."""
    def line(m):
        return _first_line(m.get("content") or m.get("text") or "", 120)
    users = [m for m in msgs if m.get("role") == "user"]
    goal = line(users[0]) if users else (line(msgs[0]) if msgs else "")
    nxt = line(users[-1]) if users else ""
    parts = []
    if carried:
        parts.append(f"Prior: {carried[:300]}")
    if goal:
        parts.append(f"Goal: {goal}")
    progress = _digest_messages(msgs)
    if progress:
        parts.append(f"Progress: {progress}")
    if nxt and nxt != goal:
        parts.append(f"Next: {nxt}")
    return " | ".join(parts) if parts else _digest_messages(msgs)


def _outline_files(files) -> str:
    lines = []
    for path, content in files:
        nlines = content.count("\n") + 1
        syms = _symbols(content)
        tail = f" — {', '.join(syms)}" if syms else ""
        lines.append(f"- {path} ({nlines} lines){tail}")
    return "\n".join(lines)


_STOPWORDS = {
    "the", "and", "for", "make", "add", "change", "update", "set", "please",
    "with", "this", "that", "into", "from", "your", "you", "its", "use", "new",
    "app", "page", "should", "must", "when", "then", "also", "but", "not",
}


def _terms(text: str):
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(t) >= 3 and t not in _STOPWORDS}


def _relevance(instruction_terms, path, content) -> int:
    path_terms = _terms(path.replace("/", " ").replace(".", " "))
    sym_terms = set()
    for s in _symbols(content, limit=40):
        sym_terms |= _terms(s)
    return 3 * len(instruction_terms & path_terms) + len(instruction_terms & sym_terms)


# --- the three transforms ---------------------------------------------------


def _is_summary(msg) -> bool:
    c = msg.get("content") or msg.get("text") or ""
    return c.startswith(SUMMARY_PREFIX)


def compact_messages(messages, budget=None, *, preserve_last=2, summarizer=None):
    """Keep all `system` messages + the last `preserve_last` non-system turns
    verbatim; fold the middle into ONE `[compacted ...]` summary turn. A no-op if
    already under budget OR if nothing foldable remains (→ idempotent)."""
    budget = context_budget() if budget is None else budget
    before = estimate_tokens(messages)
    system = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    tail = non_system[-preserve_last:] if preserve_last else []
    middle = non_system[:-preserve_last] if preserve_last else list(non_system)
    prior = [m for m in middle if _is_summary(m)]
    foldable = [m for m in middle if not _is_summary(m)]
    if before <= budget or not foldable:
        return CompactionResult(messages, before, before, 0, "", False)

    n = len(foldable)
    # Carry any earlier `[compacted ...]` summary FORWARD — the old code dropped it
    # on a re-fold (lossy); now its captured state is preserved (§5.5).
    carried = " ".join(_summary_body(m) for m in prior).strip()
    if summarizer:
        body = summarizer(_summary_prompt(_digest_messages(foldable), carried))
    else:
        body = _structured_digest(foldable, carried)
    content = f"{SUMMARY_PREFIX} {n} earlier turn(s)] {body}"
    summary_msg = {"role": "user", "content": content}
    items = system + [summary_msg] + tail
    return CompactionResult(items, before, estimate_tokens(items), n, content, True)


def compact_files(files, instruction, budget=None, *, summarizer=None):
    """Edit-mode payload compaction: keep the files most relevant to `instruction`
    whole (always at least the single most relevant), summarize the rest into a
    one-line-per-file outline. The biggest real win on large apps."""
    budget = context_budget() if budget is None else budget
    before = estimate_tokens(files)
    if before <= budget:
        return CompactionResult(list(files), before, before, 0, "", False)

    iterms = _terms(instruction)
    order = sorted(
        range(len(files)),
        key=lambda i: (-_relevance(iterms, files[i][0], files[i][1]),
                       estimate_tokens(files[i]), i),
    )
    keep_idx, running = set(), 0
    for rank, i in enumerate(order):
        ft = estimate_tokens(files[i])
        if rank == 0 or running + ft <= budget:  # always keep the top-ranked file
            keep_idx.add(i)
            running += ft
    kept = [files[i] for i in range(len(files)) if i in keep_idx]
    dropped = [files[i] for i in range(len(files)) if i not in keep_idx]
    if not dropped:
        return CompactionResult(kept, before, estimate_tokens(kept), 0, "", False)

    outline = _outline_files(dropped)
    if summarizer:
        outline = summarizer(outline)
    summary = (f"{SUMMARY_PREFIX} {len(dropped)} file(s) not central to this change "
               f"— outline only]\n{outline}")
    after = estimate_tokens(kept) + estimate_tokens(summary)
    return CompactionResult(kept, before, after, len(dropped), summary, True,
                            summarized_paths=[p for p, _ in dropped])


def compact_conversation(entries, budget=None, *, preserve_last=6, summarizer=None):
    """Fold an unbounded feature chat log: keep the last `preserve_last` entries
    verbatim, summarize everything older into one leading summary entry."""
    budget = context_budget() if budget is None else budget
    before = estimate_tokens(entries)
    tail = entries[-preserve_last:] if preserve_last else []
    middle = entries[:-preserve_last] if preserve_last else list(entries)
    foldable = [e for e in middle if not _is_summary(e)]
    if before <= budget or not foldable:
        return CompactionResult(list(entries), before, before, 0, "", False)

    n = len(foldable)
    body = summarizer(_digest_messages(foldable)) if summarizer \
        else _digest_messages(foldable)
    content = f"{SUMMARY_PREFIX} {n} earlier message(s)] {body}"
    summary_entry = {"role": "system", "text": content, "compacted": True}
    items = [summary_entry] + tail
    return CompactionResult(items, before, estimate_tokens(items), n, content, True)


# --- durable, lossless-by-anchor context card -------------------------------


def write_context_card(target_dir, result: CompactionResult, *, kind="messages",
                       meta=None) -> str:
    """Write the compaction decision into `<dir>/.adf-context/`: an append-only
    `compaction-<n>.json` (the machine record — preserves the summary digest so the
    fold is reviewable, never a silent drop) + a human `CONTEXT.md` (latest)."""
    cdir = os.path.join(target_dir, CONTEXT_DIR)
    os.makedirs(cdir, exist_ok=True)
    n = 1 + sum(1 for f in os.listdir(cdir)
                if f.startswith("compaction-") and f.endswith(".json"))
    rec = {
        "kind": kind,
        "tokens_before": result.tokens_before,
        "tokens_after": result.tokens_after,
        "n_summarized": result.n_summarized,
        "did_compact": result.did_compact,
        "summarized_paths": result.summarized_paths,
        "summary": result.summary,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if meta:
        rec.update(meta)
    path = os.path.join(cdir, f"compaction-{n}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2)
    saved = max(0, result.tokens_before - result.tokens_after)
    with open(os.path.join(cdir, "CONTEXT.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# Context card — {kind}\n\n"
            f"- compacted: **{result.did_compact}** "
            f"({result.tokens_before} → {result.tokens_after} tokens, "
            f"~{saved} saved)\n"
            f"- items summarized: {result.n_summarized}\n"
            f"- when: {rec['created_at']}\n\n"
            f"## Summary (the folded content, preserved)\n\n{result.summary}\n")
    return path


# --- CLI --------------------------------------------------------------------


_SKIP_DIRS = {"node_modules", "dist", "build", ".git", "__pycache__",
              CONTEXT_DIR, ".adf-proof"}
_TEXT_EXT = (".py", ".mjs", ".js", ".ts", ".tsx", ".jsx", ".json", ".html",
             ".css", ".sql", ".md", ".txt", ".yml", ".yaml", ".sh")


def _collect_files(root):
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in sorted(files):
            if not fn.endswith(_TEXT_EXT):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8") as f:
                    out.append((os.path.relpath(fp, root), f.read()))
            except (OSError, UnicodeDecodeError):
                continue
    return out


def _main(argv=None):
    ap = argparse.ArgumentParser(description="ADF /compact — estimate + compact context")
    ap.add_argument("dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--budget", type=int, default=None)
    args = ap.parse_args(argv)

    budget = args.budget if args.budget is not None else context_budget()
    files = _collect_files(args.dir)
    tokens = estimate_tokens(files)
    report = {
        "dir": args.dir,
        "tokens": tokens,
        "budget": budget,
        "over": tokens > budget,
        "n_files": len(files),
    }
    if args.apply:
        res = compact_files(files, "", budget=budget)
        card = write_context_card(args.dir, res, kind="files",
                                  meta={"trigger": "cli"})
        report["card"] = card
        report["did_compact"] = res.did_compact
        report["tokens_after"] = res.tokens_after
    if args.json:
        print(json.dumps(report))
    else:
        print(f"{args.dir}: {tokens} tokens vs budget {budget} "
              f"({'OVER' if report['over'] else 'ok'}), {len(files)} files")
        if args.apply:
            print(f"wrote {report['card']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
