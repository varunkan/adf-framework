"""Free-text elicitation from synthetic respondents via Groq.

Paper method (App. A.4): prime the LLM with the persona, show the stimulus,
ask the survey question, sample a BRIEF textual response — never a number.
We elicit one short answer per construct in a single JSON-mode call
(separate texts per construct keep the SSR mapping clean), plus open
likes/dislikes feedback for qualitative mining (paper App. E).
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib

import httpx

from .personas import persona_system_prompt

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
TEMPERATURE = 0.8          # diversity across samples (paper varies T_LLM)
# free tier = 12k tokens/min; each call ~1.5-2k tokens -> ~6-8 calls/min.
# Low concurrency + patient Retry-After-aware backoff beats a 429 storm.
MAX_CONCURRENCY = 3
MAX_ATTEMPTS = 14


def load_groq_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        env = (pathlib.Path(__file__).resolve().parents[2]
               / "services" / "dossier" / ".env")
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("GROQ_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        raise RuntimeError("GROQ_API_KEY not found (env or services/dossier/.env)")
    return key


def _question_block(constructs: list[str]) -> str:
    q = {
        "ease": 'How easy or hard would this be for you to use? ("ease")',
        "clarity": 'How clear is it what you are supposed to do, and what the terms mean? ("clarity")',
        "trust": 'Would you rely on this part for a real Health Canada submission? Why or why not? ("trust")',
        "adoption": 'Based on everything you have seen, how likely is it that you / your organization would adopt this product? ("adoption")',
    }
    lines = [q[c] for c in constructs]
    keys = ", ".join(f'"{c}"' for c in constructs)
    return (
        "Answer the following questions, each in 2-4 first-person sentences:\n- "
        + "\n- ".join(lines)
        + '\n- What specifically do you like, and what do you dislike or would '
        'change? Be concrete. ("feedback")\n\n'
        f"Reply as a JSON object with exactly these string keys: {keys}, \"feedback\"."
    )


async def _one(client: httpx.AsyncClient, key: str, persona: dict,
               stimulus: dict, constructs: list[str], sample_idx: int,
               sem: asyncio.Semaphore) -> dict:
    messages = [
        {"role": "system", "content": persona_system_prompt(persona)},
        {"role": "user", "content":
            f"Product walkthrough — {stimulus['title']}:\n\n"
            f"{stimulus['walkthrough']}\n\n" + _question_block(constructs)},
    ]
    body = {
        "model": MODEL, "messages": messages, "temperature": TEMPERATURE,
        "top_p": 0.9, "max_tokens": 500,   # 4 short answers + feedback fit;
        # every completion token counts against the Groq daily budget
        "response_format": {"type": "json_object"},
    }
    trace = os.environ.get("PANEL_TRACE", "")

    def _t(msg: str) -> None:
        if trace:
            with open(trace, "a") as f:
                f.write(f"{persona['id']}/{stimulus['flow_key']}#{sample_idx} "
                        f"{msg}\n")

    async with sem:
        for attempt in range(MAX_ATTEMPTS):
            try:
                _t(f"attempt {attempt} POST")
                r = await client.post(
                    GROQ_URL, json=body,
                    headers={"Authorization": f"Bearer {key}"}, timeout=60)
                _t(f"attempt {attempt} -> {r.status_code}")
                if r.status_code == 429:
                    retry_after = float(r.headers.get("retry-after", 0) or 0)
                    await asyncio.sleep(max(retry_after, 2.0) + attempt)
                    continue
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                answers = json.loads(content)
                if not all(isinstance(answers.get(c), str) and answers[c].strip()
                           for c in constructs + ["feedback"]):
                    raise ValueError("missing construct answers")
                return {
                    "persona_id": persona["id"], "flow_key": stimulus["flow_key"],
                    "sample": sample_idx, "answers": answers,
                }
            except Exception as exc:
                _t(f"attempt {attempt} EXC {type(exc).__name__}: {exc}")
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(2 * (attempt + 1))


async def elicit_all(personas: list[dict], stimuli: list[dict],
                     n_samples: int = 2,
                     on_progress=None,
                     checkpoint_path=None,
                     done: list[dict] | None = None) -> list[dict]:
    """All (persona x stimulus x sample) elicitations, concurrently.

    checkpoint_path: partial results are flushed there every few completions,
    so an interrupted run resumes (pass its content back via `done`).
    """
    key = load_groq_key()
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    out: list[dict] = list(done or [])
    have = {(r["persona_id"], r["flow_key"], r["sample"]) for r in out}
    async with httpx.AsyncClient() as client:
        tasks = []
        for p in personas:
            for s in stimuli:
                constructs = ["ease", "clarity", "trust"]
                if s["flow_key"] == "overall":
                    constructs = ["ease", "clarity", "trust", "adoption"]
                for i in range(n_samples):
                    if (p["id"], s["flow_key"], i) in have:
                        continue
                    tasks.append(_one(client, key, p, s, constructs, i, sem))
        total = len(tasks) + len(out)
        for fut in asyncio.as_completed(tasks):
            out.append(await fut)
            if checkpoint_path and len(out) % 10 == 0:
                pathlib.Path(checkpoint_path).write_text(json.dumps(out))
            if on_progress:
                on_progress(len(out), total)
    if checkpoint_path:
        pathlib.Path(checkpoint_path).write_text(json.dumps(out))
    return out
