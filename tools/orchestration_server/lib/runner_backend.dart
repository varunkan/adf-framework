import 'dart:io';

/// Identifies which headless agent CLI drives the orchestration runner.
enum RunnerKind { cursor, claude, custom }

extension RunnerKindName on RunnerKind {
  String get id => switch (this) {
        RunnerKind.cursor => 'cursor',
        RunnerKind.claude => 'claude',
        RunnerKind.custom => 'custom',
      };

  String get label => switch (this) {
        RunnerKind.cursor => 'Cursor CLI (cursor-agent)',
        RunnerKind.claude => 'Claude Code CLI (claude)',
        RunnerKind.custom => 'Custom agent CLI',
      };
}

/// Abstraction over a headless agent CLI so the orchestration server can drive
/// Cursor, Claude Code, or any other agent runner without code changes.
///
/// Selection is controlled by the `ADF_RUNNER` environment variable:
///   - `cursor`  → [CursorBackend]
///   - `claude`  → [ClaudeBackend]
///   - `custom`  → [CustomBackend] (driven by ADF_RUNNER_BIN / ADF_RUNNER_ARGS)
///   - unset/`auto` → pick the first backend whose binary resolves
///     (custom if configured, else cursor, else claude, else cursor default).
///
/// All supported runners emit a JSON-lines ("stream-json") protocol with a
/// terminal `{"type":"result","result":"…"}` event, which the existing parsers
/// already understand, so only executable + argv differ per backend.
abstract class RunnerBackend {
  RunnerKind get kind;

  /// Absolute path to the runner binary, or null if not installed.
  String? resolveExecutable();

  /// Argv for a streaming (stream-json) run of [prompt] scoped to [workspace].
  List<String> streamArgs(String prompt, String workspace,
      {bool partial = true});

  /// Argv for a plain-text run (used by liveness probes).
  List<String> textArgs(String prompt, String workspace);

  /// Argv that reports auth/login status, or null if the CLI has no such verb.
  List<String>? statusArgs();

  /// `pkill -f` pattern that matches an in-flight headless run for this backend.
  String get killPattern;

  /// Name of the env var that holds an API key for unattended auth, if any.
  String? get apiKeyEnvVar;

  /// True when [apiKeyEnvVar] is set and non-empty.
  bool get apiKeyConfigured {
    final name = apiKeyEnvVar;
    if (name == null) return false;
    return Platform.environment[name]?.isNotEmpty == true;
  }

  /// One-line install hint shown when the binary is missing.
  String get installHint;

  /// Interactive login command for this CLI, or null if it has none.
  String? get loginCommand => null;

  /// Operator-facing recovery steps surfaced in the dashboard.
  List<String> get recoverySteps;

  /// Resolve the active backend from the environment.
  static RunnerBackend active() {
    final raw =
        (Platform.environment['ADF_RUNNER'] ?? 'auto').trim().toLowerCase();
    switch (raw) {
      case 'cursor':
      case 'cursor-agent':
        return CursorBackend();
      case 'claude':
      case 'claude-code':
        return ClaudeBackend();
      case 'custom':
        return CustomBackend();
      case '':
      case 'auto':
        return _autoSelect();
      default:
        // Unknown value → behave like auto so a typo never bricks the runner.
        return _autoSelect();
    }
  }

  static RunnerBackend _autoSelect() {
    // An explicitly configured custom runner wins.
    if (Platform.environment['ADF_RUNNER_BIN']?.isNotEmpty == true) {
      return CustomBackend();
    }
    final cursor = CursorBackend();
    if (cursor.resolveExecutable() != null) return cursor;
    final claude = ClaudeBackend();
    if (claude.resolveExecutable() != null) return claude;
    // Nothing installed: default to cursor so existing error/hint UX is intact.
    return cursor;
  }

  /// Search PATH and a list of well-known absolute candidates for [names].
  static String? firstExisting(List<String> candidates, List<String> onPath) {
    for (final c in candidates) {
      if (c.isNotEmpty && File(c).existsSync()) return c;
    }
    for (final name in onPath) {
      try {
        final which = Process.runSync('which', [name]);
        if (which.exitCode == 0) {
          final p = (which.stdout as String).trim();
          if (p.isNotEmpty && File(p).existsSync()) return p;
        }
      } catch (_) {}
    }
    return null;
  }
}

/// Cursor's headless `cursor-agent --print` runner (the original ADF backend).
class CursorBackend extends RunnerBackend {
  @override
  RunnerKind get kind => RunnerKind.cursor;

  @override
  String? resolveExecutable() {
    final env = Platform.environment['CURSOR_AGENT_PATH'];
    if (env != null && env.isNotEmpty && File(env).existsSync()) return env;
    final home = Platform.environment['HOME'] ?? '';
    return RunnerBackend.firstExisting(
      [
        '$home/.local/bin/cursor-agent',
        '$home/.local/bin/agent',
        '/Applications/Cursor.app/Contents/Resources/app/bin/cursor',
      ],
      ['cursor-agent'],
    );
  }

  @override
  List<String> streamArgs(String prompt, String workspace,
      {bool partial = true}) {
    final args = <String>[
      '--print',
      '--trust',
      '--force',
      '--approve-mcps',
      '--workspace',
      workspace,
      '--output-format',
      'stream-json',
      if (partial) '--stream-partial-output',
      prompt,
    ];
    return _withApiKey(args);
  }

  @override
  List<String> textArgs(String prompt, String workspace) {
    final args = <String>[
      '--print',
      '--trust',
      '--force',
      '--approve-mcps',
      '--workspace',
      workspace,
      '--output-format',
      'text',
      prompt,
    ];
    return _withApiKey(args);
  }

  List<String> _withApiKey(List<String> args) {
    final apiKey = Platform.environment['CURSOR_API_KEY'];
    if (apiKey != null && apiKey.isNotEmpty) {
      return ['--api-key', apiKey, ...args];
    }
    return args;
  }

  @override
  List<String>? statusArgs() => ['status'];

  @override
  String get killPattern => r'cursor-agent.*--print';

  @override
  String? get apiKeyEnvVar => 'CURSOR_API_KEY';

  @override
  String get installHint =>
      'cursor-agent not found. Install via: curl -fsSL https://cursor.com/install | bash';

  @override
  String get loginCommand => 'cursor-agent login';

  @override
  List<String> get recoverySteps => const [
        'Kill stuck headless agents: pkill -f "cursor-agent.*--print"',
        'Restart Cursor app, run: cursor-agent login',
        'Or set CURSOR_API_KEY in your environment',
        'Restart the orchestration API server',
        'Until headless works: resume in Cursor IDE, then Sync',
        'Tap Verify in the dashboard for a fresh headless probe',
      ];
}

/// Anthropic's Claude Code headless `claude -p` runner.
///
/// Claude Code runs in its working directory (no `--workspace` flag), emits
/// `stream-json` with `--verbose`, and skips interactive permission prompts via
/// `--dangerously-skip-permissions`. Auth comes from a prior `claude login`
/// session or the `ANTHROPIC_API_KEY` environment variable.
class ClaudeBackend extends RunnerBackend {
  @override
  RunnerKind get kind => RunnerKind.claude;

  @override
  String? resolveExecutable() {
    final env = Platform.environment['ADF_CLAUDE_PATH'] ??
        Platform.environment['CLAUDE_PATH'];
    if (env != null && env.isNotEmpty && File(env).existsSync()) return env;
    final home = Platform.environment['HOME'] ?? '';
    return RunnerBackend.firstExisting(
      [
        '$home/.local/bin/claude',
        '$home/.claude/local/claude',
        '/opt/homebrew/bin/claude',
        '/usr/local/bin/claude',
      ],
      ['claude'],
    );
  }

  @override
  List<String> streamArgs(String prompt, String workspace,
      {bool partial = true}) {
    // `--add-dir` grants tool access to the repo; cwd is set by the caller.
    return [
      '-p',
      '--output-format',
      'stream-json',
      '--verbose',
      '--dangerously-skip-permissions',
      '--add-dir',
      workspace,
      prompt,
    ];
  }

  @override
  List<String> textArgs(String prompt, String workspace) {
    return [
      '-p',
      '--output-format',
      'text',
      '--dangerously-skip-permissions',
      '--add-dir',
      workspace,
      prompt,
    ];
  }

  @override
  List<String>? statusArgs() => null; // Claude Code has no `status` verb.

  @override
  String get killPattern => r'claude.*--output-format';

  @override
  String? get apiKeyEnvVar => 'ANTHROPIC_API_KEY';

  @override
  String get installHint =>
      'claude not found. Install via: npm install -g @anthropic-ai/claude-code, then run: claude login';

  @override
  String get loginCommand => 'claude login';

  @override
  List<String> get recoverySteps => const [
        'Kill stuck headless agents: pkill -f "claude.*--output-format"',
        'Authenticate once: claude login',
        'Or set ANTHROPIC_API_KEY in your environment',
        'Restart the orchestration API server',
        'Until headless works: run the printed prompt in Claude Code, then Sync',
        'Tap Verify in the dashboard for a fresh headless probe',
      ];
}

/// Fully generic backend driven entirely by environment variables, so ADF can
/// drive any agent CLI (Windsurf, Aider, Gemini CLI, a corporate wrapper, …).
///
///   ADF_RUNNER_BIN            absolute path or PATH name of the CLI (required)
///   ADF_RUNNER_ARGS           space-separated argv template. Placeholders:
///                               {prompt}     → the full prompt (single arg)
///                               {workspace}  → the repo/worktree path
///                             Defaults to "{prompt}" when unset.
///   ADF_RUNNER_API_KEY_ENV    name of the env var holding the API key (opt.)
///   ADF_RUNNER_KILL_PATTERN   pkill -f pattern (defaults to the binary name)
class CustomBackend extends RunnerBackend {
  @override
  RunnerKind get kind => RunnerKind.custom;

  @override
  String? resolveExecutable() {
    final bin = Platform.environment['ADF_RUNNER_BIN'];
    if (bin == null || bin.isEmpty) return null;
    if (bin.contains('/')) return File(bin).existsSync() ? bin : null;
    return RunnerBackend.firstExisting([], [bin]);
  }

  List<String> _template() {
    final raw = Platform.environment['ADF_RUNNER_ARGS'];
    if (raw == null || raw.trim().isEmpty) return ['{prompt}'];
    return raw.trim().split(RegExp(r'\s+'));
  }

  List<String> _expand(String prompt, String workspace) {
    final out = <String>[];
    for (final tok in _template()) {
      if (tok == '{prompt}') {
        out.add(prompt);
      } else {
        out.add(tok.replaceAll('{workspace}', workspace));
      }
    }
    return out;
  }

  @override
  List<String> streamArgs(String prompt, String workspace,
          {bool partial = true}) =>
      _expand(prompt, workspace);

  @override
  List<String> textArgs(String prompt, String workspace) =>
      _expand(prompt, workspace);

  @override
  List<String>? statusArgs() => null;

  @override
  String get killPattern {
    final p = Platform.environment['ADF_RUNNER_KILL_PATTERN'];
    if (p != null && p.isNotEmpty) return p;
    final bin = Platform.environment['ADF_RUNNER_BIN'] ?? 'agent';
    return bin.split('/').last;
  }

  @override
  String? get apiKeyEnvVar => Platform.environment['ADF_RUNNER_API_KEY_ENV'];

  @override
  String get installHint =>
      'Custom runner not found. Set ADF_RUNNER_BIN to an installed agent CLI.';

  @override
  List<String> get recoverySteps => const [
        'Set ADF_RUNNER_BIN to your agent CLI path',
        'Set ADF_RUNNER_ARGS (use {prompt} and {workspace} placeholders)',
        'Optionally set ADF_RUNNER_API_KEY_ENV for unattended auth',
        'Restart the orchestration API server',
      ];
}
