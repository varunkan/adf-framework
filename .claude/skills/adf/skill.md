---
name: ADF Studio
description: Launch the ADF Studio UI to build apps from a plain-language prompt. Boots the orchestration server on 127.0.0.1:3847, opens the dashboard in the browser, and drives builds with the Claude CLI runner (free NVIDIA/Opus fallback when no Claude token is live). Use when the user types /adf or asks to open, start, or run ADF Studio.
---

## ADF Studio

`/adf` boots **ADF Studio** — the prompt-to-app build UI — and drives builds through
the **Claude CLI runner** (`claude -p`), falling back to the free NVIDIA/Opus runner
when no live Claude subscription token is present.

Claude Code itself does **not** render the UI. The UI is a web dashboard the
orchestration server hosts; this skill just boots that server and opens the URL.

### What to do

1. **Find the framework root** — the git repo containing
   `scripts/orch/adf_studio_up.sh`. If the current working directory is inside it,
   use that. Otherwise ask the user for the path.

2. **Launch Studio detached.** It is a long-lived server, so it must outlive this
   turn — run it in the background (Bash tool with `run_in_background: true`):

   ```bash
   bash scripts/orch/adf_studio_up.sh
   ```

   The script starts the server with `setsid`/`nohup`, waits for
   `http://127.0.0.1:3847/health`, prints which runner was selected, and opens the
   dashboard.

3. **Report to the user:**
   - the dashboard URL — `http://127.0.0.1:3847`;
   - the active runner (read the launch log, `/tmp/adf-studio.log`):
     `(runner = Claude Code subscription …)` → the **Claude CLI drives builds**;
     `(runner = custom: NVIDIA …)` → the token was missing/expired (a 401 on the
     probe) and the **free fallback runner** is building instead;
   - that they should type their build request **in the dashboard**, not here.

### If the Claude CLI runner is wanted but the log shows the fallback

The Claude runner needs a live subscription token. Tell the user to run
`claude setup-token` in a normal Terminal, paste the `sk-ant-oat01-…` token into
`.adf/secrets.env` as `CLAUDE_CODE_OAUTH_TOKEN=…`, then re-run `/adf`.

### Do not

- **Do not** start the server as a foreground Bash call — it gets reaped seconds
  after the turn ends. Always background it (step 2).
- **Do not** try to render or embed the UI inside Claude Code — point the user to
  the browser dashboard URL.
