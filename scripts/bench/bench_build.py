#!/usr/bin/env python3
"""Drive ONE real ADF build per prompt and MEASURE the capability axes — built?,
tests pass?, file count, wall-clock seconds, tokens — so the scorecard's capability
columns rest on measured runs, not claims. It reuses the runner's own build path
(scaffold → generate → verify → self-heal → seal), so what the bench measures is
exactly what ADF ships. The model/verify steps are injectable so the orchestration
is testable without a live model or npm."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))

import agent_runner as ar  # noqa: E402


def build_one(item, workspace, *, stack=None, timeout=240, fix_iters=3,
              generate=None, verify=None, seal=True):
    """Build the app for one suite item; return its measured capability scorecard.

    `generate` / `verify` default to the runner's real `generate` / `verify_app`
    and are injectable for deterministic tests."""
    stack = stack or ar.STACK_REACT
    generate = generate or ar.generate
    verify = verify or ar.verify_app
    fid, prompt = item["id"], item["prompt"]
    app_dir = os.path.join(workspace, "apps", fid)
    ctx = {"requirement": prompt, "problem": "", "spec": "", "plan": "", "tasks": ""}

    tpl = ar.template_dir(ROOT, workspace, stack)
    if not tpl:
        return {"id": fid, "built": False, "error": "no template", "seconds": 0}
    os.makedirs(app_dir, exist_ok=True)
    ar.scaffold_app(app_dir, tpl)

    system, user = ar.build_messages(fid, ctx, stack)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    t0 = time.monotonic()
    built = False
    attempts = files_written = in_tok = out_tok = 0
    for attempt in range(1, fix_iters + 1):
        attempts = attempt
        gen = generate(messages, timeout)
        if not gen:
            break
        text, usage = gen
        in_tok += (usage or {}).get("prompt_tokens", 0)
        out_tok += (usage or {}).get("completion_tokens", 0)
        files = ar.parse_files(text)
        if not files:
            continue
        app_root, written = ar.write_files(workspace, fid, files)
        files_written = len(written)
        ok, _output = verify(app_root, stack)
        if ok:
            built = True
            break
        messages = ar.fix_messages(system, user, files, _output, stack)
    seconds = round(time.monotonic() - t0, 1)

    if built and seal:
        try:
            import policy_gate
            import proof_of_build
            pol = policy_gate.check_policy(app_dir)
            proof_of_build.seal_app(
                app_dir, fid, stack, prompt,
                {"verified": True, "policy": policy_gate.policy_summary(pol)})
        except Exception:
            pass

    return {
        "id": fid,
        "built": built,
        "tests_pass": built,
        "files": files_written,
        "seconds": seconds,
        "attempts": attempts,
        "in_tokens": in_tok,
        "out_tokens": out_tok,
    }


def capability_summary(results):
    n = len(results)
    built = [r for r in results if r.get("built")]
    secs = [r["seconds"] for r in built if r.get("seconds")]
    return {
        "apps": n,
        "built": len(built),
        "tests_pass": sum(1 for r in results if r.get("tests_pass")),
        "avg_seconds": round(sum(secs) / len(secs), 1) if secs else 0,
        "total_out_tokens": sum(r.get("out_tokens", 0) for r in results),
    }
