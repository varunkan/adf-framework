import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'claude_child_env.dart';
import 'runner_backend.dart';

/// Probes the active agent runner (Claude or a custom CLI) for availability and
/// authentication.
///
/// Executable resolution and argv construction are delegated to the
/// [RunnerBackend] selected via the `ADF_RUNNER` environment variable. The
/// method names (`probe`, `livenessProbe`, `killStalePrintAgents`) are stable
/// so existing callers and tests keep working regardless of backend.
class RunnerHealth {
  RunnerHealth({this.repoRoot, RunnerBackend? backend})
      : backend = backend ?? RunnerBackend.active();

  final String? repoRoot;

  /// The active runner backend (claude / custom).
  final RunnerBackend backend;

  DateTime? _headlessProbeAt;
  bool? _headlessOk;
  static const Duration _headlessProbeTtl = Duration(minutes: 5);

  /// Generic fallback recovery steps. Prefer [activeRecoverySteps], which
  /// reflects the selected backend.
  static const recoverySteps = [
    'Kill stuck headless agents (macOS/Linux)',
    'Sign in to the runner CLI, or set its API key in your environment',
    'Restart the orchestration API server',
    'Tap Verify in the dashboard for a fresh headless probe',
  ];

  List<String> get activeRecoverySteps => backend.recoverySteps;

  RunnerKind get runnerKind => backend.kind;

  /// Resolve the active runner binary (any backend).
  String? resolveRunner() => backend.resolveExecutable();

  /// Back-compat alias — resolves the active runner binary.
  String? resolveAgent() => backend.resolveExecutable();

  Future<Map<String, dynamic>> probe({bool useCache = true}) async {
    final apiKeySet = backend.apiKeyConfigured;
    final agentPath = backend.resolveExecutable();
    final runnerInfo = <String, dynamic>{
      'runner': backend.kind.id,
      'runner_label': backend.kind.label,
      'login_command': backend.loginCommand,
    };
    final steps = [
      if (agentPath == null) backend.installHint,
      ...backend.recoverySteps,
    ];

    if (agentPath == null) {
      return {
        ...runnerInfo,
        'agent_path': null,
        'authenticated': false,
        'api_key_set': apiKeySet,
        'ready': apiKeySet,
        'hint': apiKeySet ? null : backend.installHint,
        'error_code': 'agent_not_found',
        'recovery_steps': steps,
      };
    }

    if (apiKeySet) {
      return {
        ...runnerInfo,
        'agent_path': agentPath,
        'authenticated': true,
        'api_key_set': true,
        'ready': true,
        'hint': null,
        'error_code': null,
        'recovery_steps': backend.recoverySteps,
      };
    }

    // Backends without a cheap `status` verb (Claude, custom) are treated as
    // ready when the binary resolves; a missing login surfaces on first run and
    // routes through the needs-login / self-heal path.
    final statusArgs = backend.statusArgs();
    if (statusArgs == null) {
      return {
        ...runnerInfo,
        'agent_path': agentPath,
        'authenticated': true,
        'api_key_set': false,
        'ready': true,
        'hint': backend.kind == RunnerKind.claude
            ? 'Using existing Claude login. Set ANTHROPIC_API_KEY for unattended auth.'
            : null,
        'error_code': null,
        'recovery_steps': backend.recoverySteps,
      };
    }

    try {
      final result = await Process.run(
        agentPath,
        statusArgs,
        workingDirectory: repoRoot,
      );
      final out = '${result.stdout}${result.stderr}'.toLowerCase();
      final notLoggedIn = out.contains('not logged in') ||
          out.contains('not authenticated') ||
          result.exitCode != 0 && out.contains('login');
      final authenticated = !notLoggedIn && result.exitCode == 0;

      return {
        ...runnerInfo,
        'agent_path': agentPath,
        'authenticated': authenticated,
        'api_key_set': false,
        'ready': authenticated,
        'hint': authenticated ? null : 'Run login or set ${backend.apiKeyEnvVar ?? 'an API key'}',
        'error_code': authenticated ? null : 'needs_login',
        'recovery_steps': backend.recoverySteps,
        'status_output': '${result.stdout}'.trim(),
      };
    } catch (e) {
      return {
        ...runnerInfo,
        'agent_path': agentPath,
        'authenticated': false,
        'api_key_set': apiKeySet,
        'ready': false,
        'hint': 'Failed to probe ${backend.kind.id} runner: $e',
        'error_code': 'probe_failed',
        'recovery_steps': backend.recoverySteps,
      };
    }
  }

  Future<void> killStalePrintAgents() async {
    if (!Platform.isMacOS && !Platform.isLinux) return;
    try {
      await Process.run('pkill', ['-f', backend.killPattern]);
    } catch (_) {}
    await Future<void>.delayed(const Duration(milliseconds: 300));
  }

  /// Quick check: agent binary responds to `--version` (no network).
  Future<bool> versionProbe() async {
    final agentPath = backend.resolveExecutable();
    if (agentPath == null) return false;
    try {
      final result = await Process.run(
        agentPath,
        ['--version'],
        workingDirectory: repoRoot,
      ).timeout(const Duration(seconds: 5));
      return result.exitCode == 0 &&
          '${result.stdout}${result.stderr}'.trim().isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  /// True if a streaming run returns any stdout/stderr within [timeout]
  /// (cached [ttl]). Set `ORCH_HEADLESS_ASSUME_READY=1` when the agent is
  /// installed but the print/stream probe is slow.
  Future<bool> livenessProbe({
    Duration timeout = const Duration(seconds: 25),
    Duration ttl = _headlessProbeTtl,
  }) async {
    if (Platform.environment['ORCH_SKIP_HEADLESS_PROBE'] == '1' ||
        Platform.environment['ORCH_SKIP_HEADLESS_PROBE'] == 'true') {
      return false;
    }
    if (Platform.environment['ORCH_HEADLESS_ASSUME_READY'] == '1' ||
        Platform.environment['ORCH_HEADLESS_ASSUME_READY'] == 'true') {
      final v = await versionProbe();
      _headlessOk = v;
      _headlessProbeAt = DateTime.now();
      return v;
    }
    if (_headlessProbeAt != null &&
        DateTime.now().difference(_headlessProbeAt!) < ttl &&
        _headlessOk != null) {
      return _headlessOk!;
    }

    final agentPath = backend.resolveExecutable();
    if (agentPath == null) {
      _headlessOk = false;
      _headlessProbeAt = DateTime.now();
      return false;
    }

    await killStalePrintAgents();

    final cwd = repoRoot ?? Directory.current.path;
    final args = backend.textArgs('Reply with exactly: OK', cwd);

    Process? proc;
    try {
      proc = await Process.start(agentPath, args,
          workingDirectory: cwd,
          // Bill the readiness probe on the $0 subscription too. Guarded on the
          // backend: a custom/NVIDIA runner keeps its paid ANTHROPIC_API_KEY.
          // When OAuth is absent the key is left in place so the probe still
          // reports needs-login rather than failing to auth silently.
          environment:
              claudeChildEnvFromParent(claudeBackend: backend.buildsAppDirectly),
          includeParentEnvironment: false);

      var sawOutput = false;
      void chunk(String chunk) {
        if (chunk.trim().isEmpty) return;
        sawOutput = true;
      }

      final stdoutSub = proc.stdout.transform(utf8.decoder).listen(chunk);
      final stderrSub = proc.stderr.transform(utf8.decoder).listen(chunk);

      await proc.exitCode.timeout(timeout, onTimeout: () {
        try {
          proc?.kill(ProcessSignal.sigkill);
        } catch (_) {}
        return -1;
      });

      await stdoutSub.cancel();
      await stderrSub.cancel();

      final ok = sawOutput;
      _headlessOk = ok;
      _headlessProbeAt = DateTime.now();
      return ok;
    } catch (_) {
      try {
        proc?.kill(ProcessSignal.sigkill);
      } catch (_) {}
      _headlessOk = false;
      _headlessProbeAt = DateTime.now();
      return false;
    }
  }
}
