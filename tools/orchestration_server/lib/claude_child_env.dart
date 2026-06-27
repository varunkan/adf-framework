import 'dart:io';

/// Shapes the environment handed to a spawned `claude` coding-agent CLI child so
/// it bills the **$0 Claude Code subscription**, not the paid Anthropic API.
///
/// CONTRACT — pass the result to `Process.start`/`Process.run` with
/// **`includeParentEnvironment: false`**. Dart MERGES the `environment` map over
/// the inherited parent env when `includeParentEnvironment` is true (the
/// default), so a key removed from the map silently reappears from the parent
/// side and every removal below becomes a no-op. Build the input from the FULL
/// parent env (`Platform.environment`) and pass it as the COMPLETE child env so
/// `PATH`/`HOME`/`ADF_*`/etc. are preserved while only the keys below are dropped.
///
/// `claudeBackend` must be the active backend's `buildsAppDirectly`. The scrub
/// runs ONLY for the Claude coding agent. For the custom/NVIDIA runner
/// (`agent_runner.py`), `ANTHROPIC_API_KEY` is its LEGITIMATE paid-path auth and
/// is left untouched.
///
/// Two scrubs, each a no-op when its keys aren't present:
///  - **nested-session markers** — `CLAUDE_CODE_*` (except the OAuth token),
///    `CLAUDE_AGENT_SDK*`, `CLAUDECODE`, `ANTHROPIC_BASE_URL`. Inherited from a
///    parent Claude Code session, they make a nested `claude` return a
///    `<synthetic>` error and exit 1.
///  - **`ANTHROPIC_API_KEY`** — removed ONLY when `CLAUDE_CODE_OAUTH_TOKEN` is
///    present and non-empty, so a build never loses its only auth. Otherwise the
///    paid key outranks the subscription token (first-match-wins precedence) and
///    silently bills the API. Empty-string OAuth counts as absent; the key is
///    fully `remove`d (never set to `''`, which would still authenticate — with
///    an empty, failing key).
Map<String, String> claudeChildEnv(Map<String, String> env,
    {required bool claudeBackend}) {
  if (!claudeBackend) return env;
  env.removeWhere((k, _) =>
      (k.startsWith('CLAUDE_CODE_') && k != 'CLAUDE_CODE_OAUTH_TOKEN') ||
      k.startsWith('CLAUDE_AGENT_SDK') ||
      k == 'CLAUDECODE' ||
      k == 'ANTHROPIC_BASE_URL');
  final oauth = env['CLAUDE_CODE_OAUTH_TOKEN'];
  if (oauth != null && oauth.isNotEmpty) {
    env.remove('ANTHROPIC_API_KEY');
  }
  return env;
}

/// Convenience: a complete, subscription-safe copy of the current process env for
/// the claude-CLI spawn sites that don't go through `PhaseRunner.childEnvFor`
/// (the verification gate, the dashboard-chat agent, the readiness probe). Pair
/// with `includeParentEnvironment: false`.
Map<String, String> claudeChildEnvFromParent({required bool claudeBackend}) =>
    claudeChildEnv(Map<String, String>.of(Platform.environment),
        claudeBackend: claudeBackend);
