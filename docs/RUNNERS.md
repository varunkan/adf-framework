# ADF runners — drive the pipeline with any agent CLI

ADF's orchestration server executes phases, self-heal attempts, and dashboard
chat by shelling out to a headless **agent runner**. As of v3.2.0 the runner is
pluggable: the same pipeline can be driven by Cursor, Claude Code, or any other
agent CLI, on any IDE.

## Selecting a runner

The active runner is chosen at server start from the `ADF_RUNNER` environment
variable (typically loaded from `.adf/runner.env`, which the installer writes):

| `ADF_RUNNER` | Binary driven                  | Auth                                   |
|--------------|--------------------------------|----------------------------------------|
| `cursor`     | `cursor-agent --print`         | `cursor-agent login` or `CURSOR_API_KEY` |
| `claude`     | `claude -p`                    | `claude login` or `ANTHROPIC_API_KEY`  |
| `custom`     | `$ADF_RUNNER_BIN`              | `$ADF_RUNNER_API_KEY_ENV` (optional)   |
| `auto` / unset | custom if configured, else cursor, else claude | — |

`auto` keeps existing Cursor installs working unchanged: if `cursor-agent`
resolves it is used; otherwise ADF falls back to `claude`.

`adf install -r ollama` is a special case: it writes a pre-filled `custom`
config that drives a local Ollama model — see [Ollama](#ollama-local-model-0).

## Model routing (complexity-based)

On top of the runner, the orchestration server routes every LLM task to the
cheapest tier that can handle it. Each task is scored for complexity (task
length, kind — chat/artifact lean local or fast, review/plan lean balanced,
implement/architecture lean deep — presence of code blocks, explicit user
escalation words) and the router returns a logged decision:
`{tier, model, reason}`.

| Tier | Model | $/MTok in | $/MTok out |
|------|-------|-----------|------------|
| `instant` | none — answered from server state | $0 | $0 |
| `local` | Ollama, `ORCH_OLLAMA_MODEL` (default Nemotron GGUF) | $0 | $0 |
| `fast` | `ORCH_MODEL_FAST` (default `claude-haiku-4-5`) | $1.00 | $5.00 |
| `balanced` | `ORCH_MODEL_BALANCED` (default `claude-sonnet-4-6`) | $3.00 | $15.00 |
| `deep` | `ORCH_MODEL_DEEP` (default `claude-opus-4-8`) | $5.00 | $25.00 |

Decision flow: instant state answer → router picks `local` \| `fast` \|
`balanced` \| `deep` → on failure, fallback chain to the next tier up.

Simple work **never** pays cloud prices: short chat and artifact tasks resolve
at the `instant` or `local` tier ($0), and the cloud tiers only engage when the
complexity score demands them. Every cloud call's token usage and cost lands in
the per-feature cost meter (`/features/<id>/cost` and the dashboard cost chip).

| Variable | Purpose |
|----------|---------|
| `ORCH_ROUTER` | `auto` \| `local-only` \| `cloud-only` (default `auto`) |
| `ORCH_MODEL_FAST` | Fast-tier model (default `claude-haiku-4-5`) |
| `ORCH_MODEL_BALANCED` | Balanced-tier model (default `claude-sonnet-4-6`) |
| `ORCH_MODEL_DEEP` | Deep-tier model (default `claude-opus-4-8`) |
| `ANTHROPIC_API_KEY` | Required for the cloud tiers; when unset the router degrades to local-only (never an error) |
| `ORCH_AGENT_TIMEOUT_SEC` | Cap per brain/crew LLM task in seconds (default `30`) |
| `ORCH_RUNNER_TIMEOUT_SEC` | Cap per spawned runner-CLI agent in seconds (default `30`) |

**Timeouts and escalation.** Every LLM task is capped at
`ORCH_AGENT_TIMEOUT_SEC` (default 30 s); spawned runner-CLI agents at
`ORCH_RUNNER_TIMEOUT_SEC` (default 30 s). On timeout the task is killed and
recorded as `timed_out` with its elapsed ms, then escalated **once** to the
next-higher tier (`local → fast → balanced → deep`) with the same task; if that
attempt also times out, the task is marked blocked.

## Claude Code

```bash
npm install -g @anthropic-ai/claude-code
claude login                      # or: export ANTHROPIC_API_KEY=...
adf install -t . -i claude -r claude
set -a && . .adf/runner.env && set +a
adf doctor      # should report: OK claude / runner: claude
adf start all
```

ADF invokes Claude headlessly as:

```
claude -p --output-format stream-json --verbose \
  --dangerously-skip-permissions --add-dir <repo> "<prompt>"
```

Claude Code's `stream-json` events (`assistant` message blocks plus a terminal
`{"type":"result","result":"…"}`) are parsed by the same code path that handles
Cursor, so phase logs, partial streaming, and the `[ACTION:…]` chat protocol all
work identically.

## Ollama (local model, $0)

Run the whole pipeline against a model served by [Ollama](https://ollama.com)
on your own machine: zero marginal cost per run, no API key, fully offline.
ADF ships a wrapper (`scripts/orch/ollama_runner.sh`) that adapts Ollama's
HTTP API to the custom-runner contract — `adf install -r ollama` wires it up
out of the box.

Prerequisites:

```bash
ollama serve                      # local API on http://127.0.0.1:11434
ollama pull hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M   # default model
```

Install and start:

```bash
adf install -t . -i generic -r ollama
set -a && . .adf/runner.env && set +a
adf start all
```

The wrapper POSTs each prompt to `$OLLAMA_HOST/api/generate` (`stream:false`)
and emits the terminal `{"type":"result","result":"…"}` event the server
parses. Pick a different model or host in `.adf/runner.env`:

```bash
ORCH_OLLAMA_MODEL=llama3.2                # any pulled model, e.g. qwen2.5-coder
OLLAMA_HOST=http://127.0.0.1:11434        # remote Ollama works too
```

Note: Ollama models are plain text generators with no filesystem or tool
access, so quality depends heavily on the model you pull — but every run is
free and never leaves your machine.

### Local Nemotron (NVIDIA)

ADF's default local model is NVIDIA's Nemotron 3 Nano (4B) — small enough for
a laptop, capable enough for dashboard chat. Pull the official NVIDIA GGUF
once:

```bash
ollama pull hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M
```

Then set (or uncomment) in `.adf/runner.env`:

```bash
ORCH_CHAT_LLM=auto                          # auto | ollama | cursor
ORCH_OLLAMA_MODEL=hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M
ORCH_OLLAMA_HOST=http://127.0.0.1:11434
```

Alternatives: `nemotron-mini` (smallest) or
`hf.co/MaziyarPanahi/NVIDIA-Nemotron-Nano-12B-v2-GGUF` (higher quality).

**Latency expectations.** Questions the server can answer from its own state
(status, URLs, phase progress) are answered instantly — milliseconds,
regardless of which model is configured (`llm_source: state`). Free-form chat
goes through the local model, so latency is bounded by local inference speed —
typically a few seconds per reply for the 4B model on recent hardware.

**Chat fallback order.** With `ORCH_CHAT_LLM=auto` each dashboard chat message
resolves as: instant state answer first, then the local Ollama model when
`ORCH_OLLAMA_HOST` is reachable, then the existing `cursor-agent` path.

## Any other agent CLI (custom)

Point ADF at any binary. `{prompt}` is always passed as a single argument;
`{workspace}` is replaced with the repo/worktree path.

```bash
adf install -t . -i generic -r custom
# then edit .adf/runner.env:
ADF_RUNNER=custom
ADF_RUNNER_BIN=/usr/local/bin/my-agent
ADF_RUNNER_ARGS=run --json --dir {workspace} {prompt}
ADF_RUNNER_API_KEY_ENV=MY_AGENT_TOKEN     # optional
ADF_RUNNER_KILL_PATTERN=my-agent          # optional, for stale-process cleanup
```

For a custom runner to stream nicely, emit JSON lines with a terminal
`{"type":"result","result":"<final text>"}`; otherwise ADF falls back to
treating raw stdout as the reply.

## Install on any IDE

```bash
adf install -t . -i cursor      # .adf/orchestration + skills + hooks
adf install -t . -i vscode      # .adf/orchestration + Copilot instructions
adf install -t . -i windsurf    # .adf/orchestration + .windsurf/rules
adf install -t . -i claude      # CLAUDE.md + .claude/skills + runner.env
adf install -t . -i generic     # .adf/orchestration + AGENTS.md
adf install -t . -i all         # every adapter above, one project
```

The IDE adapter controls *where docs/skills land*; the runner controls *which
agent executes the pipeline*. They are independent — e.g. you can install the
Cursor adapter but drive it with Claude (`-i cursor -r claude`).

## Environment reference

| Variable | Purpose |
|----------|---------|
| `ADF_RUNNER` | `auto` \| `cursor` \| `claude` \| `custom` |
| `CURSOR_API_KEY` | Cursor unattended auth |
| `CURSOR_AGENT_PATH` | Override cursor-agent binary location |
| `ANTHROPIC_API_KEY` | Claude unattended auth |
| `ADF_CLAUDE_PATH` / `CLAUDE_PATH` | Override claude binary location |
| `ADF_RUNNER_BIN` | Custom runner executable |
| `ADF_RUNNER_ARGS` | Custom argv template (`{prompt}`, `{workspace}`) |
| `ADF_RUNNER_API_KEY_ENV` | Name of the custom runner's API-key env var |
| `ADF_RUNNER_KILL_PATTERN` | `pkill -f` pattern for stale custom runs |
| `ORCH_OLLAMA_MODEL` | Model for the Ollama runner and chat (default `hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M`) |
| `OLLAMA_HOST` | Ollama base URL for the runner wrapper (default `http://127.0.0.1:11434`) |
| `ORCH_OLLAMA_HOST` | Ollama base URL for dashboard chat (default `http://127.0.0.1:11434`) |
| `ORCH_CHAT_LLM` | Dashboard chat backend: `auto` \| `ollama` \| `cursor` (default `auto`) |
