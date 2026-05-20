import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Probes cursor-agent availability and authentication.
class RunnerHealth {
  RunnerHealth({this.repoRoot});

  final String? repoRoot;

  DateTime? _headlessProbeAt;
  bool? _headlessOk;
  static const Duration _headlessProbeTtl = Duration(minutes: 5);

  static const recoverySteps = [
    'Kill stuck headless agents: pkill -f "cursor-agent.*--print" (macOS/Linux)',
    'Restart Cursor app, run: cursor-agent login',
    'Or set CURSOR_API_KEY in your environment',
    'Restart the orchestration API server',
    'Until headless works: resume in Cursor IDE, then Sync',
    'Tap Verify in the dashboard for a fresh headless probe',
  ];

  String? resolveCursorAgent() {
    final env = Platform.environment['CURSOR_AGENT_PATH'];
    if (env != null && env.isNotEmpty && File(env).existsSync()) return env;

    final home = Platform.environment['HOME'] ?? '';
    final candidates = [
      '$home/.local/bin/cursor-agent',
      '$home/.local/bin/agent',
      '/Applications/Cursor.app/Contents/Resources/app/bin/cursor',
    ];
    for (final path in candidates) {
      if (File(path).existsSync()) return path;
    }
    try {
      final which = Process.runSync('which', ['cursor-agent']);
      if (which.exitCode == 0) {
        final p = (which.stdout as String).trim();
        if (p.isNotEmpty && File(p).existsSync()) return p;
      }
    } catch (_) {}
    return null;
  }

  Future<Map<String, dynamic>> probe({bool useCache = true}) async {
    final apiKeySet =
        Platform.environment['CURSOR_API_KEY']?.isNotEmpty == true;
    final agentPath = resolveCursorAgent();

    if (agentPath == null) {
      return {
        'agent_path': null,
        'authenticated': false,
        'api_key_set': apiKeySet,
        'ready': apiKeySet,
        'hint': apiKeySet
            ? null
            : 'cursor-agent not found. Install via: curl -fsSL https://cursor.com/install | bash',
        'error_code': 'agent_not_found',
        'recovery_steps': [
          'Install cursor-agent: curl -fsSL https://cursor.com/install | bash',
          ...recoverySteps,
        ],
      };
    }

    if (apiKeySet) {
      return {
        'agent_path': agentPath,
        'authenticated': true,
        'api_key_set': true,
        'ready': true,
        'hint': null,
        'error_code': null,
        'recovery_steps': recoverySteps,
      };
    }

    try {
      final result = await Process.run(
        agentPath,
        ['status'],
        workingDirectory: repoRoot,
      );
      final out =
          '${result.stdout}${result.stderr}'.toLowerCase();
      final notLoggedIn = out.contains('not logged in') ||
          out.contains('not authenticated') ||
          result.exitCode != 0 && out.contains('login');
      final authenticated = !notLoggedIn && result.exitCode == 0;

      return {
        'agent_path': agentPath,
        'authenticated': authenticated,
        'api_key_set': false,
        'ready': authenticated,
        'hint': authenticated
            ? null
            : 'Run cursor-agent login or set CURSOR_API_KEY',
        'error_code': authenticated ? null : 'needs_login',
        'recovery_steps': recoverySteps,
        'status_output': '${result.stdout}'.trim(),
      };
    } catch (e) {
      return {
        'agent_path': agentPath,
        'authenticated': false,
        'api_key_set': apiKeySet,
        'ready': false,
        'hint': 'Failed to probe cursor-agent: $e',
        'error_code': 'probe_failed',
        'recovery_steps': recoverySteps,
      };
    }
  }

  Future<void> killStalePrintAgents() async {
    if (!Platform.isMacOS && !Platform.isLinux) return;
    try {
      await Process.run(
        'pkill',
        ['-f', r'cursor-agent.*--print'],
      );
    } catch (_) {}
    await Future<void>.delayed(const Duration(milliseconds: 300));
  }

  /// Quick check: agent binary responds to `--version` (no network).
  Future<bool> versionProbe() async {
    final agentPath = resolveCursorAgent();
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

  /// True if `--print` returns any stdout/stderr within [timeout] (cached [ttl]).
  /// Set `ORCH_HEADLESS_ASSUME_READY=1` when agent is installed but `--print` is slow.
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

    final agentPath = resolveCursorAgent();
    if (agentPath == null) {
      _headlessOk = false;
      _headlessProbeAt = DateTime.now();
      return false;
    }

    await killStalePrintAgents();

    final cwd = repoRoot ?? Directory.current.path;
    final args = <String>[
      '--print',
      '--trust',
      '--force',
      '--approve-mcps',
      '--workspace',
      cwd,
      '--output-format',
      'text',
      'Reply with exactly: OK',
    ];
    final apiKey = Platform.environment['CURSOR_API_KEY'];
    if (apiKey != null && apiKey.isNotEmpty) {
      args.insertAll(0, ['--api-key', apiKey]);
    }

    Process? proc;
    try {
      proc = await Process.start(agentPath, args, workingDirectory: cwd);

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
