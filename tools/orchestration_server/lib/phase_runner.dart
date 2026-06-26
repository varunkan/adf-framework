import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'code_heuristics.dart';
import 'cost_meter.dart';
import 'feature_store.dart';
import 'runner_health.dart';
import 'run_post_sync.dart';
import 'trace_writer.dart';

enum CancelReason { user, replaced }

/// B3: the human-readable phase-completion line shown in the durable chat. It must
/// NEVER claim "tests passed" unless the tests_green gate is actually set — the
/// runner can exit 0 with tests still red (it self-heals but may not converge), and
/// the old code keyed only on `awaiting`, so a failed phase-7 build read as success.
/// Pure + unit-testable.
String phaseOutcomeLine(int phase,
    {required bool awaiting, required bool testsGreen}) {
  if (awaiting) {
    return 'Build complete — Phase $phase is ready for your review and approval.';
  }
  if (phase >= 7 && !testsGreen) {
    return 'Build ran, but tests are NOT green yet — Phase $phase is not '
        'complete. See run-log.jsonl for the failing tests.';
  }
  return 'Build complete — Phase $phase finished; the build ran and tests passed.';
}

/// Runs orchestration phases via the active headless runner CLI (claude /
/// custom), selected through the [RunnerBackend] abstraction.
class PhaseRunner {
  PhaseRunner(
    this.store, {
    this.pollInterval = const Duration(seconds: 2),
    Map<String, String>? env,
  })  : _health = RunnerHealth(repoRoot: store.repoRoot),
        _costs = CostMeter(store),
        _env = env ?? Platform.environment {
    _traces = TraceWriter(store.repoRoot);
  }

  /// Max CONSECUTIVE no-progress self-heal attempts before the build is handed to
  /// a human. RELENTLESS by design — the north star is "embrace failure and keep
  /// fighting until the app is actually green". This is NOT a cap on the total
  /// number of fixes: _reconcileDirectBuild resets heal_attempts to 0 every cycle
  /// the defect count DROPS, so the loop fixes defects one-by-one without limit as
  /// long as it keeps making progress. The cap only fires after this many cycles
  /// in a row that remove no defects (genuinely stuck). Each attempt is
  /// diagnosis-driven (see [_healPrompt]); on a $0/token subscription runner the
  /// cost of fighting on is just wall-clock. Tune via ORCH_MAX_HEAL_ATTEMPTS
  /// (0 = never retry; set higher to tolerate more stuck cycles).
  int get maxHealAttempts {
    final raw = int.tryParse(_env['ORCH_MAX_HEAL_ATTEMPTS']?.trim() ?? '');
    return raw != null && raw >= 0 ? raw : 12;
  }

  /// INTERRUPTION RESILIENCE. Seconds after which a non-terminal run that this
  /// server process is NOT tracking (the orphan signature of a crash/restart) is
  /// resumed from where it left off. 0 disables the watchdog. Tune via
  /// ORCH_STALE_RUN_SEC.
  int get staleRunSec {
    final raw = int.tryParse(_env['ORCH_STALE_RUN_SEC']?.trim() ?? '');
    return raw != null && raw >= 0 ? raw : 180;
  }

  /// Cap on automatic resumes of a repeatedly-interrupted run before it is marked
  /// blocked for human attention. Generous (default 100) so transient
  /// interruptions — server restarts, sleeps, network blips — never prematurely
  /// stop a long unattended build; only a genuine tight crash-loop escalates.
  int get maxOrphanResumes {
    final raw = int.tryParse(_env['ORCH_MAX_ORPHAN_RESUMES']?.trim() ?? '');
    return raw != null && raw > 0 ? raw : 100;
  }

  /// Max features that may build CONCURRENTLY across the whole runner. `_pollQueue`
  /// fires `unawaited` every tick, so WITHOUT a cap every queued feature starts at
  /// once (the rate-limit-storm signature). Default 1 = effectively serial =
  /// today's behavior. Raise to run independent features in parallel — bounded by
  /// the subscription rate limit, not CPU. Tune via ADF_BUILD_PARALLELISM.
  int get maxBuildParallelism {
    final raw = int.tryParse(_env['ADF_BUILD_PARALLELISM']?.trim() ?? '');
    return raw != null && raw > 0 ? raw : 1;
  }

  /// Age in seconds of an ISO-8601 timestamp relative to [now], or null if absent
  /// / unparseable. Static → unit-testable without the wall clock.
  static int? ageSeconds(String? iso, DateTime now) {
    if (iso == null || iso.isEmpty) return null;
    try {
      return now.toUtc().difference(DateTime.parse(iso).toUtc()).inSeconds;
    } catch (_) {
      return null;
    }
  }

  /// The "fixing and retrying (attempt N of M)" line — or null when attempts are
  /// already exhausted and no retry will happen, so we never narrate a retry
  /// that won't occur (the "attempt 4 of 3" off-by-one).
  static String? retryNarration(int healSoFar, int maxAttempts) {
    if (healSoFar >= maxAttempts) return null;
    return 'Build hit a problem — fixing and retrying automatically '
        '(attempt ${healSoFar + 1} of $maxAttempts)…';
  }

  /// Parse `python -m unittest -v` output into (count, passed). Pure → testable.
  /// unittest prints "Ran N tests" then a trailing "OK" (success) or
  /// "FAILED (…)" / "ERROR" (failure); a run that crashes before any test has
  /// exitCode != 0 and is never "passed".
  static ({int count, bool passed}) parseUnittestResult(
      String output, int exitCode) {
    final m = RegExp(r'Ran (\d+) test').firstMatch(output);
    final count = int.tryParse(m?.group(1) ?? '') ?? 0;
    final failed = RegExp(r'^(FAILED|ERROR)', multiLine: true).hasMatch(output);
    return (count: count, passed: exitCode == 0 && count > 0 && !failed);
  }

  final FeatureStore store;
  final Duration pollInterval;
  final RunnerHealth _health;
  final CostMeter _costs;
  final Map<String, String> _env;

  /// SLIDING INACTIVITY timeout for a spawned runner-CLI agent
  /// (`ORCH_RUNNER_IDLE_TIMEOUT_SEC`, default 300s). This is NOT a fixed budget:
  /// it RESETS on every line the runner emits. While Claude is reasoning or
  /// running tools it streams stream-json events continuously, so an actively
  /// working build is never killed no matter how long it legitimately takes.
  /// Only TRUE silence — no output for this long — means the runner is stuck
  /// (a deadlock, a hung network call, a foreground command that never returns);
  /// then ADF kills it and re-invokes, so it never hangs forever. Falls back to
  /// the legacy `ORCH_RUNNER_TIMEOUT_SEC` only if it is small enough to be an
  /// idle window (≤600s); a large legacy value (the old 1800s one-shot budget)
  /// is ignored here and instead caps [maxRunDuration].
  Duration get runnerIdleTimeout {
    final raw = int.tryParse(_env['ORCH_RUNNER_IDLE_TIMEOUT_SEC']?.trim() ?? '');
    if (raw != null && raw > 0) return Duration(seconds: raw);
    final legacy = int.tryParse(_env['ORCH_RUNNER_TIMEOUT_SEC']?.trim() ?? '');
    if (legacy != null && legacy > 0 && legacy <= 600) {
      return Duration(seconds: legacy);
    }
    return const Duration(seconds: 300);
  }

  /// Absolute hard ceiling for a single runner invocation — the never-hang
  /// backstop that fires even if the runner keeps dribbling output forever.
  /// Generous by design (the sliding [runnerIdleTimeout] is the real control);
  /// a large legacy `ORCH_RUNNER_TIMEOUT_SEC` raises this rather than capping a
  /// working build. Tune via `ORCH_RUNNER_MAX_SEC` (default 7200s = 2h).
  Duration get maxRunDuration {
    final raw = int.tryParse(_env['ORCH_RUNNER_MAX_SEC']?.trim() ?? '');
    if (raw != null && raw > 0) return Duration(seconds: raw);
    final legacy = int.tryParse(_env['ORCH_RUNNER_TIMEOUT_SEC']?.trim() ?? '');
    if (legacy != null && legacy > 600) return Duration(seconds: legacy);
    return const Duration(seconds: 7200);
  }

  RunnerHealth get health => _health;

  /// The environment a runner subprocess inherits for [featureId]: the base env
  /// plus `ADF_STACK` resolved from the feature's persisted stack (contract C5),
  /// so the Python runner generates and verifies with the matching StackProfile
  /// (single-file stdlib vs. React+Vite+SQLite). Defaults to stdlib for legacy
  /// features, preserving today's behavior.
  Map<String, String> childEnvFor(String featureId) {
    // Pass the feature id EXPLICITLY — the runner must never have to guess it from
    // the prompt prose (which mis-parsed 'phase' and failed the build).
    final env = <String, String>{
      ..._env,
      ...nonInteractiveEnv,
      'ADF_STACK': store.stackFor(featureId),
      'ADF_FEATURE_ID': featureId,
    };
    // A coding-agent backend (Claude Code) must run as a FRESH top-level session.
    // When ADF was itself launched from inside a Claude Code session, the server's
    // env carries nested-session markers (CLAUDE_CODE_*, CLAUDE_AGENT_SDK_*,
    // CLAUDECODE) and a session-scoped ANTHROPIC_BASE_URL. Inherited by the spawned
    // `claude -p`, they make it behave as a nested SDK call — it returns a
    // <synthetic> error and exits 1 instead of building. Scrub them so the child
    // uses its own login/config. (Harmless to strip for argv runners too.)
    if (_health.backend.buildsAppDirectly) {
      env.removeWhere((k, _) =>
          // keep the long-lived headless auth token (`claude setup-token`)
          (k.startsWith('CLAUDE_CODE_') && k != 'CLAUDE_CODE_OAUTH_TOKEN') ||
          k.startsWith('CLAUDE_AGENT_SDK') ||
          k == 'CLAUDECODE' ||
          k == 'ANTHROPIC_BASE_URL');
    }
    return env;
  }

  /// Force every spawned tool (the runner, the real coding-agent CLIs, and any
  /// git/pip/npm they shell) into non-interactive mode so none blocks on a pager
  /// or a credential prompt and dies only at the timeout. Adopted from oh-my-pi;
  /// see docs/ADF_VS_OH_MY_PI.md §5.2.
  ///
  /// Exact mirror of Python NON_INTERACTIVE_ENV (scripts/orch/agent_runner.py).
  /// Keep in sync: add a key here whenever you add one there. Drift is caught by
  /// test/phase_runner_env_test.dart.
  static const Map<String, String> nonInteractiveEnv = {
    'CI': '1',
    'NO_COLOR': '1',
    'TERM': 'dumb',
    'PAGER': 'cat',
    'GIT_PAGER': 'cat',
    'MANPAGER': 'cat',
    'GIT_TERMINAL_PROMPT': '0',
    'GIT_EDITOR': 'true',
    'GCM_INTERACTIVE': 'never',
    'DEBIAN_FRONTEND': 'noninteractive',
    'PYTHONUNBUFFERED': '1',
    'PIP_NO_INPUT': '1',
    'PIP_DISABLE_PIP_VERSION_CHECK': '1',
    'PIP_PROGRESS_BAR': 'off',
    'npm_config_yes': 'true',
    'npm_config_audit': 'false',
    'npm_config_fund': 'false',
    'npm_config_progress': 'false',
    'npm_config_update_notifier': 'false',
    'ADBLOCK': '1',
    'HOMEBREW_NO_AUTO_UPDATE': '1',
  };

  late TraceWriter _traces;
  final Set<String> _active = {};
  final Set<String> _healing = {};
  final Set<String> _userCancelled = {};
  final Map<String, Process> _processes = {};
  final Map<String, StringBuffer> _reasoningBuffers = {};
  Timer? _timer;
  bool _started = false;
  Map<String, dynamic>? _cachedHealth;

  String get repoRoot => store.repoRoot;

  /// Whether the headless runner CLI is usable (distinct from auth [ready]).
  Future<bool> isHeadlessReady({bool refresh = false}) async {
    final h = await getHealth(refresh: refresh);
    return h['headless_ready'] == true;
  }

  /// Records prompt + idle run status when headless is unavailable.
  Map<String, dynamic> _ideOnlyResult(
    String featureId, {
    required String prompt,
    String? commandId,
    String? hint,
  }) {
    store.writeRunStatus(featureId, {
      'status': 'idle',
      'agent_active': false,
      'finished_at': DateTime.now().toUtc().toIso8601String(),
      'error': null,
      'error_code': null,
      'resume_mode': 'ide',
      'headless_unavailable': true,
      'hint': hint ??
          'Headless runner unavailable — run the prompt in your IDE, then Sync.',
    });
    if (commandId != null) {
      store.markCommandExecuted(featureId, commandId, status: 'recorded_ide');
    }
    return {
      'success': true,
      'mode': 'ide_only',
      'hint': hint,
      'run_status': store.readRunStatus(featureId),
    };
  }

  Future<Map<String, dynamic>> getHealth({bool refresh = false}) async {
    if (!refresh && _cachedHealth != null) return _cachedHealth!;
    final base = await _health.probe();
    final merged = Map<String, dynamic>.from(base);
    const headlessUnknown =
        'Not probed yet; open GET /runner/health or enqueue a phase';
    const headlessHint =
        'The headless runner produced no output within 20s — use your IDE '
        'or kill stuck agents';

    if (!refresh && _cachedHealth == null) {
      merged.addAll({'headless_ready': null, 'headless_hint': headlessUnknown});
    } else {
      final versionOk = await _health.versionProbe();
      final printOk = await _health.livenessProbe();
      merged.addAll({
        'headless_ready': printOk,
        'headless_capable': versionOk,
        'headless_hint': printOk
            ? null
            : versionOk
                ? headlessHint
                : 'Runner CLI not responding — install it or sign in',
      });
    }

    _cachedHealth = merged;
    return merged;
  }

  void startBackgroundPoller() {
    if (_started) return;
    _started = true;
    _traces = TraceWriter(repoRoot);
    _timer = Timer.periodic(pollInterval, (_) {
      unawaited(_pollQueue());
      unawaited(_pollSelfHeal());
    });
    unawaited(getHealth());
    print('Phase runner: polling every ${pollInterval.inSeconds}s');
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _started = false;
  }

  Future<Map<String, dynamic>> enqueue(
    String featureId, {
    int? phase,
    bool refreshHealth = false,
  }) async {
    _traces = TraceWriter(repoRoot);
    if (!store.featureExists(featureId)) {
      throw StateError('Feature not found: $featureId');
    }

    final health = await getHealth(refresh: refreshHealth);
    if (health['ready'] != true) {
      final runPhase = phase ?? _resolveRunPhase(featureId);
      _writeNeedsLogin(featureId, runPhase, health);
      return store.readRunStatus(featureId) ?? {'status': 'needs_login'};
    }

    if (health['headless_ready'] != true) {
      final runPhase = phase ?? _resolveRunPhase(featureId);
      store.writeRunStatus(featureId, {
        'status': 'idle',
        'phase': runPhase,
        'agent_active': false,
        'finished_at': DateTime.now().toUtc().toIso8601String(),
        'error': null,
        'error_code': null,
        'resume_mode': 'ide',
        'headless_unavailable': true,
        'hint': health['headless_hint'] as String? ??
            'Headless agent unavailable — use your IDE',
      });
      return store.readRunStatus(featureId) ?? {'status': 'idle'};
    }

    final runPhase = phase ?? _resolveRunPhase(featureId);
    store.writePhaseRequest(featureId, runPhase);
    store.writeRunStatus(featureId, {
      'status': 'queued',
      'phase': runPhase,
      'queued_at': DateTime.now().toUtc().toIso8601String(),
      'error': null,
      'error_code': null,
    });

    _traces.append(
      featureId: featureId,
      name: 'runner.phase_queued',
      event: 'runner',
      phase: runPhase,
      message: 'Phase $runPhase queued',
    );

    unawaited(_pollQueue());
    return store.readRunStatus(featureId) ?? {'status': 'queued'};
  }

  bool isActive(String featureId) => _active.contains(featureId);

  /// Queue command execution (returns immediately; agent runs in background).
  Future<Map<String, dynamic>> enqueueCommand(
    String featureId, {
    required String prompt,
    String? stepId,
    String? commandId,
    bool cancelPrevious = true,
    String? agentPrompt,
  }) async {
    _traces = TraceWriter(repoRoot);
    final health = await getHealth(refresh: true);
    if (health['ready'] != true) {
      _writeNeedsLogin(featureId, null, health, prompt: prompt);
      throw StateError(health['hint'] as String? ?? 'Runner not ready');
    }

    final busy =
        _active.contains(featureId) || _processes.containsKey(featureId);
    if (busy && cancelPrevious) {
      await cancelRun(featureId, reason: CancelReason.replaced);
      await Future<void>.delayed(const Duration(milliseconds: 800));
    } else if (busy) {
      return {
        'success': false,
        'error': 'Agent already running for this feature',
      };
    }

    store.appendClientClarification(featureId, prompt);

    if (health['headless_ready'] != true) {
      return _ideOnlyResult(
        featureId,
        prompt: prompt,
        commandId: commandId,
        hint: health['headless_hint'] as String?,
      );
    }

    _active.add(featureId);
    final resolvedPrompt = agentPrompt ?? _wrapClientInputPrompt(featureId, prompt);

    unawaited(_executeCommandWorker(
      featureId: featureId,
      prompt: resolvedPrompt,
      stepId: stepId,
      commandId: commandId,
    ));

    return {
      'success': true,
      'started': true,
      'run_status': store.readRunStatus(featureId),
    };
  }

  Future<void> _executeCommandWorker({
    required String featureId,
    required String prompt,
    String? stepId,
    String? commandId,
  }) async {
    try {
      await executeCommand(
        featureId,
        prompt: prompt,
        stepId: stepId,
        commandId: commandId,
      );
    } finally {
      _active.remove(featureId);
    }
  }

  Future<Map<String, dynamic>> executeCommand(
    String featureId, {
    required String prompt,
    String? stepId,
    String? commandId,
  }) async {
    _traces = TraceWriter(repoRoot);
    final health = await getHealth(refresh: true);
    if (health['ready'] != true) {
      _writeNeedsLogin(featureId, null, health, prompt: prompt);
      throw StateError(health['hint'] as String? ?? 'Runner not ready');
    }

    final state = store.readState(featureId);
    final phase = (state['current_phase'] as num?)?.toInt() ?? 1;
    final effectivePhase = phase > 0 ? phase : 1;

    if (commandId != null) {
      store.markCommandExecuted(featureId, commandId, status: 'running');
    }

    final awaitingUser = state['awaiting_user'] == true;
    store.writeRunStatus(featureId, {
      'status': awaitingUser ? 'awaiting_approval' : 'running',
      'agent_active': true,
      'phase': effectivePhase,
      'step_id': stepId,
      'prompt': prompt,
      'started_at': DateTime.now().toUtc().toIso8601String(),
      'error': null,
    });

    await _bootstrap(featureId, effectivePhase);

    final result = await _spawnAgent(
      featureId: featureId,
      phase: effectivePhase,
      prompt: prompt,
    );

    if (commandId != null) {
      store.markCommandExecuted(
        featureId,
        commandId,
        status: result['success'] == true ? 'executed' : 'failed',
      );
    }

    return result;
  }

  Future<bool> cancelRun(
    String featureId, {
    CancelReason reason = CancelReason.user,
  }) async {
    _traces = TraceWriter(repoRoot);
    if (reason == CancelReason.user) {
      _userCancelled.add(featureId);
    }
    _healing.remove(featureId);
    final proc = _processes.remove(featureId);
    if (proc != null) {
      try {
        proc.kill(ProcessSignal.sigterm);
        await proc.exitCode.timeout(const Duration(seconds: 5));
      } catch (_) {
        try {
          proc.kill(ProcessSignal.sigkill);
        } catch (_) {}
      }
    }
    _active.remove(featureId);
    _reasoningBuffers.remove(featureId);
    final state = store.readState(featureId);
    final awaiting = state['awaiting_user'] == true;
    final isUserCancel = reason == CancelReason.user;
    store.writeRunStatus(featureId, {
      'status': awaiting ? 'awaiting_approval' : 'idle',
      'agent_active': false,
      'finished_at': DateTime.now().toUtc().toIso8601String(),
      if (!awaiting && isUserCancel) 'error': 'Cancelled by user',
      if (!awaiting && isUserCancel) 'error_code': 'cancelled',
      if (awaiting) 'error': null,
      if (awaiting) 'error_code': null,
    });
    if (isUserCancel) {
      _traces.append(
        featureId: featureId,
        name: 'runner.cancelled',
        event: 'runner',
        message: 'Run cancelled by user',
      );
    }
    return true;
  }

  /// Clear stale `running` / `agent_active` when no live runner process.
  void reconcileStaleRunStatus(String featureId) {
    store.reconcileFeatureState(featureId);
    final run = store.readRunStatus(featureId);
    if (run == null) return;

    final status = run['status'] as String?;
    final agentActive = run['agent_active'] == true;
    final busyStatus = status == 'running' ||
        status == 'queued' ||
        status == 'healing' ||
        (status == 'awaiting_approval' && agentActive);
    if (!busyStatus) return;

    final live = _active.contains(featureId) || _processes.containsKey(featureId);
    final started = run['started_at'] as String?;
    Duration? age;
    if (started != null) {
      try {
        age = DateTime.now().toUtc().difference(DateTime.parse(started));
      } catch (_) {}
    }

    if (age != null && age > maxRunDuration) {
      final state = store.readState(featureId);
      final awaiting = state['awaiting_user'] == true;
      store.writeRunStatus(featureId, {
        'status': awaiting ? 'awaiting_approval' : 'error',
        'agent_active': false,
        'finished_at': DateTime.now().toUtc().toIso8601String(),
        'error': 'Run timed out after ${maxRunDuration.inMinutes} minutes',
        'error_code': 'timeout',
      });
      store.clearStuckCommands(featureId);
      return;
    }

    if (!live) {
      // No process in memory — clear phantom agent_active immediately.
      final state = store.readState(featureId);
      final awaiting = state['awaiting_user'] == true;
      final completed = state['status'] == 'completed';
      store.writeRunStatus(featureId, {
        'status': completed
            ? 'idle'
            : (awaiting ? 'awaiting_approval' : 'idle'),
        'agent_active': false,
        'finished_at': DateTime.now().toUtc().toIso8601String(),
        'error': completed || awaiting
            ? null
            : (run['error'] ?? 'Run ended (recovered stale status)'),
        'error_code': completed || awaiting
            ? null
            : (run['error_code'] ?? 'stale_recovered'),
      });
      store.clearStuckCommands(featureId);
    }
  }

  /// Cancel live run (if any) and reconcile stuck run-status + commands + state.
  Future<Map<String, dynamic>> unstickFeature(String featureId) async {
    if (_active.contains(featureId) || _processes.containsKey(featureId)) {
      await cancelRun(featureId, reason: CancelReason.user);
    }
    reconcileStaleRunStatus(featureId);
    store.reconcileFeatureState(featureId);
    store.clearStuckCommands(featureId);
    return store.readRunStatus(featureId) ?? {'status': 'idle'};
  }

  int _resolveRunPhase(String featureId) {
    final state = store.readState(featureId);
    final current = (state['current_phase'] as num?)?.toInt() ?? 0;
    final awaiting = state['awaiting_user'] == true;
    return awaiting
        ? (state['pending_approval_phase'] as num?)?.toInt() ?? current
        : (current > 0 ? current : 1);
  }

  void _writeNeedsLogin(
    String featureId,
    int? phase,
    Map<String, dynamic> health, {
    String? prompt,
  }) {
    store.writeRunStatus(featureId, {
      'status': 'needs_login',
      'phase': phase,
      'finished_at': DateTime.now().toUtc().toIso8601String(),
      'error': health['hint'],
      'error_code': health['error_code'] ?? 'needs_login',
      'recovery_steps': health['recovery_steps'] ?? RunnerHealth.recoverySteps,
      if (prompt != null) 'last_prompt': prompt,
    });
    store.appendRunLog(featureId, {
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'level': 'error',
      'stream': 'runner',
      'message': health['hint'] ?? 'Authentication required',
    });
    _traces.append(
      featureId: featureId,
      name: 'runner.needs_login',
      event: 'runner',
      phase: phase,
      message: health['hint'] as String? ?? 'needs_login',
    );
  }

  Future<void> _pollQueue() async {
    for (final id in store.listFeatures()) {
      if (_active.length >= maxBuildParallelism) break; // global concurrency cap
      if (_active.contains(id)) continue;
      final req = store.readPhaseRequest(id);
      final run = store.readRunStatus(id);
      final queued = req != null && req['consumed'] != true;
      final status = run?['status'] as String?;
      if (queued || status == 'queued') {
        await _runFeature(id);
      }
    }
  }

  Future<void> _runFeature(String featureId) async {
    if (_active.contains(featureId)) return;
    // Global concurrency cap. Atomic on Dart's single event loop — there is NO
    // await between this check and `_active.add` below, so two overlapping poll
    // ticks can't both slip past it. Default cap 1 → unchanged serial behavior.
    if (_active.length >= maxBuildParallelism) return;
    final req = store.readPhaseRequest(featureId);
    if (req == null || req['consumed'] == true) return;

    _active.add(featureId);
    final phase = (req['phase'] as num?)?.toInt() ?? 1;

    try {
      final health = await getHealth(refresh: true);
      if (health['ready'] != true) {
        store.consumePhaseRequest(featureId);
        _writeNeedsLogin(featureId, phase, health);
        return;
      }

      if (health['headless_ready'] != true) {
        store.consumePhaseRequest(featureId);
        store.writeRunStatus(featureId, {
          'status': 'idle',
          'phase': phase,
          'agent_active': false,
          'finished_at': DateTime.now().toUtc().toIso8601String(),
          'error': null,
          'error_code': null,
          'resume_mode': 'ide',
          'headless_unavailable': true,
          'hint': health['headless_hint'] as String?,
        });
        return;
      }

      store.consumePhaseRequest(featureId);
      store.writeRunStatus(featureId, {
        'status': 'running',
        'phase': phase,
        'started_at': DateTime.now().toUtc().toIso8601String(),
        'error': null,
        'error_code': null,
      });

      await _bootstrap(featureId, phase);

      _traces.append(
        featureId: featureId,
        name: 'runner.phase_start',
        event: 'runner',
        phase: phase,
        message: 'Starting runner for phase $phase',
      );

      final state = store.readState(featureId);
      final awaiting = state['awaiting_user'] == true;
      // A general coding agent (Claude Code) does not understand the
      // `@orch-orchestrator` control command — it needs a real build prompt that
      // points it at the spec and tells it to write + test the app. An ADF-protocol
      // runner (agent_runner.py) gets the resume/sync command as before.
      final prompt = _health.backend.buildsAppDirectly
          ? _buildAgentBuildPrompt(featureId)
          : (awaiting
              ? '@orch-orchestrator sync $featureId'
              : '@orch-orchestrator resume $featureId');

      await _spawnAgent(
        featureId: featureId,
        phase: phase,
        prompt: prompt,
      );
    } catch (e, st) {
      final msg = e.toString();
      store.writeRunStatus(featureId, {
        'status': 'error',
        'phase': phase,
        'finished_at': DateTime.now().toUtc().toIso8601String(),
        'error': msg,
        'error_code': 'exception',
        'recovery_steps': RunnerHealth.recoverySteps,
      });
      store.appendRunLog(featureId, {
        'timestamp': DateTime.now().toUtc().toIso8601String(),
        'level': 'error',
        'stream': 'exception',
        'message': '$e\n$st',
      });
      _traces.append(
        featureId: featureId,
        name: 'runner.phase_error',
        event: 'runner',
        phase: phase,
        message: msg,
      );
      unawaited(_scheduleSelfHeal(featureId, phase, msg));
    } finally {
      _active.remove(featureId);
    }
  }

  RunPostSync get _postSync => RunPostSync(store);

  static const int contextBudgetWarnTokens = 400;
  static const int contextBudgetHardCapTokens = 800;

  /// Run the built app's unit tests OURSELVES (stdlib/python stack) and return
  /// (count, passed) — or null when there are no tests to run. ADF verifying the
  /// tests is what lets the pipeline advance honestly (never the agent's claim).
  Future<({int count, bool passed})?> _runAppTests(String appDir) async {
    final dir = Directory(appDir);
    if (!dir.existsSync()) return null;
    final hasPyTests = dir.listSync().any((e) {
      final n = e.uri.pathSegments.where((s) => s.isNotEmpty).last;
      return n.startsWith('test_') && n.endsWith('.py');
    });
    if (!hasPyTests) return null;
    try {
      final r = await Process.run('python3', const ['-m', 'unittest', '-v'],
              workingDirectory: appDir)
          .timeout(const Duration(seconds: 180));
      return parseUnittestResult('${r.stdout}\n${r.stderr}', r.exitCode);
    } catch (_) {
      return (count: 0, passed: false);
    }
  }

  /// After a one-shot agentic build (buildsAppDirectly), advance the gated
  /// pipeline to match the VERIFIED app: ADF runs the tests; on green it marks
  /// the implementation gates the agentic build subsumed (plan→tests_green) and
  /// moves to phase 7, so the pipeline stops contradicting the working app. A
  /// `build_mode: agentic_direct` marker records that those phases were done
  /// holistically by the agent rather than as separate artifacts.
  ///
  /// Runtime UI/route verification of the BUILT app via scripts/orch/app_verify.py
  /// — boots the app and checks the routes the UI calls AND (headless Chrome) the
  /// browser console/network, the defects unit tests and the reviewer never saw.
  /// Returns the defect list ([] = clean), or null when verification can't run.
  Future<List<String>?> _runUiVerify(String featureId) async {
    if ((_env['ADF_UI_VERIFY'] ?? '1') == '0') return null;
    // Run the whole TEST-AGENT ECOSYSTEM (registry-driven: ui-visual, accessibility,
    // duplicate-components, security, functional, e2e, integration, black/white-box).
    // Falls back to the standalone UI gate if the orchestrator isn't present.
    final orchestrator = '$repoRoot/scripts/orch/run_test_agents.py';
    final script = File(orchestrator).existsSync()
        ? orchestrator
        : '$repoRoot/scripts/orch/app_verify.py';
    if (!File(script).existsSync()) return null;
    try {
      final r = await Process.run(
              'python3', [script, '$repoRoot/apps/$featureId'],
              workingDirectory: repoRoot)
          .timeout(const Duration(seconds: 1200)); // ecosystem of agents takes minutes
      final out = (r.stdout as String).trim();
      if (out.isEmpty) return ['test-agent gate produced no output'];
      final parsed =
          jsonDecode(out.substring(out.indexOf('{'), out.lastIndexOf('}') + 1))
              as Map<String, dynamic>;
      if (parsed['ok'] == true) return const [];
      return ((parsed['defects'] as List?) ?? const [])
          .map((e) => e.toString())
          .toList();
    } catch (e) {
      // A harness failure must not be a silent pass — surface it as a defect.
      return ['test-agent verification could not run: $e'];
    }
  }

  /// Returns true only when ADF itself verified the app is green AND the RUNNING
  /// app is defect-free (HTTP routes + headless-browser console/network). A false
  /// return means the caller must engage the relentless heal loop instead of
  /// going quietly idle on a build whose tests pass but whose UI is broken.
  Future<bool> _reconcileDirectBuild(String featureId) async {
    final res = await _runAppTests('${store.repoRoot}/apps/$featureId');
    final state = store.readState(featureId);
    final testsOk = res != null && res.passed;
    // Unit tests are necessary but NOT sufficient — the running app must verify.
    final uiDefects = testsOk ? await _runUiVerify(featureId) : null;
    final uiClean = uiDefects == null || uiDefects.isEmpty;

    if (testsOk && uiClean) {
      for (final p in const [3, 4, 5, 6, 7]) {
        store.setGateForPhase(state, p, true);
      }
      final cur = (state['current_phase'] as num?)?.toInt() ?? 0;
      if (cur < 7) state['current_phase'] = 7;
      state['build_mode'] = 'agentic_direct';
      state.remove('ui_defects');
      state.remove('heal_defect_count'); // zero defects — clear the progress meter
      store.writeState(featureId, state);
      store.appendSystemMessage(
        featureId,
        'ADF verified the build end-to-end: ${res.count} tests pass AND the '
        'running app is clean (routes + browser console/network). Implementation '
        'complete — pipeline advanced to phase 7.',
      );
      return true;
    }

    // Any failed verification: clear tests_green so the gate reflects THIS build,
    // never a stale green carried over from an earlier slice.
    store.setGateForPhase(state, 7, false);

    // RELENTLESS, ONE-BY-ONE: count the defects that remain and compare to the
    // previous cycle. While the count is DROPPING the loop is fixing defects one
    // at a time and IS making progress — so reset heal_attempts to 0 so the flat
    // attempt cap never halts a build that is steadily getting cleaner. The cap
    // then fires ONLY after maxHealAttempts CONSECUTIVE no-progress cycles
    // (genuinely stuck → hand to a human), not after a fixed number of fixes.
    final curDefectCount =
        testsOk ? (uiDefects?.length ?? 0) : 1000; // tests-red is one big wall
    final prevDefectCount = (state['heal_defect_count'] as num?)?.toInt();
    final progressed =
        prevDefectCount == null || curDefectCount < prevDefectCount;
    state['heal_defect_count'] = curDefectCount;
    if (progressed && curDefectCount > 0) {
      state['heal_attempts'] = 0; // still removing defects — keep fighting
    }

    if (testsOk && !uiClean) {
      // The blind spot the reviewer missed: tests green but the live UI errors.
      state['ui_defects'] = uiDefects;
      store.writeState(featureId, state);
      final shown = uiDefects.take(6).join('; ');
      final delta = prevDefectCount == null
          ? ''
          : progressed
              ? ' (down from $prevDefectCount — making progress, attempt counter reset)'
              : ' (was $prevDefectCount — no net progress this cycle)';
      store.appendSystemMessage(
        featureId,
        'Tests pass (${res.count}) but the RUNNING APP has ${uiDefects.length} '
        'defect(s)$delta — not complete. Self-healing the top one first: $shown'
        '${uiDefects.length > 6 ? ' …' : ''}',
      );
      return false;
    }

    state.remove('ui_defects');
    store.writeState(featureId, state);
    final detail = res == null
        ? 'no runnable tests found in the app'
        : '${res.count} tests ran, not all green';
    store.appendSystemMessage(
      featureId,
      'ADF ran the build’s tests itself — NOT green ($detail). '
      'Self-healing: diagnosing the failure and driving it to green…',
    );
    return false;
  }

  /// The build instruction handed to a coding-agent backend (Claude Code), which
  /// builds files via its own tools. Points it at the verified spec and tells it to
  /// write + self-test a runnable app under apps/<id>/. (agent_runner.py instead
  /// gets the `@orch-orchestrator` command, which only it understands.)
  String _buildAgentBuildPrompt(String featureId) {
    final specDir = 'specs/$featureId';
    // A focused MVP scope file BOUNDS the build: when present it is authoritative
    // and the agent must build ONLY that slice (the full spec is reference for
    // detail). Without it, a large spec makes a single build pass run past the
    // timeout — exactly what happened on the 91-requirement ANDS spec.
    final hasMvp = File('$repoRoot/$specDir/mvp-scope.md').existsSync();
    final scopeBlock = hasMvp
        ? '0. SCOPE — AUTHORITATIVE. Build EXACTLY this slice and nothing beyond it; '
            'treat the full spec below as reference detail only:\n'
            '   - $specDir/mvp-scope.md\n\n'
        : '';

    // ADDITIVE EXPANSION: when an app already exists we are GROWING coverage
    // slice-by-slice toward the full spec — never rebuilding from scratch, which
    // shrinks coverage (the domain.py 40KB->128 lines regression). Coverage may
    // only grow; every existing test must keep passing.
    final appDir = Directory('$repoRoot/apps/$featureId');
    final appExists = appDir.existsSync() &&
        appDir.listSync().any((e) => e.path.endsWith('.py'));
    if (appExists) {
      return 'You are the ADF build agent. An application ALREADY EXISTS at '
          'apps/$featureId/ and passes its current tests. EXTEND it to cover the '
          'scope below — do NOT start over and do NOT rewrite it from scratch.\n\n'
          '$scopeBlock'
          '1. READ what already exists in apps/$featureId/ (server.py, domain.py, '
          'test_app.py, README.md) and the spec in $specDir/ (requirements.md, '
          'problem-statement.md, spec.md). Understand the current surface before changing it.\n\n'
          '2. EXTEND ADDITIVELY — Python 3 standard library ONLY, must still run with `python3 server.py`:\n'
          '   - ADD the new domain logic, API endpoints, UI, and tests required by the scope above, '
          'implemented for REAL (no stubs).\n'
          '   - KEEP every existing file, feature, endpoint, and test. NEVER delete, weaken, skip, or '
          'shrink existing functionality or tests — coverage must only GROW.\n\n'
          '3. VERIFY YOURSELF — the FULL suite (old + new) must be green:\n'
          '   - Run: cd apps/$featureId && python3 -m unittest -v\n'
          '   - Fix until ALL tests pass; confirm `python3 server.py` still boots and serves, then stop it.\n\n'
          '4. FINISH with a short summary: what you ADDED and the final test count '
          '(e.g. "grew from 30 to 47 tests, all passing").';
    }

    final implLine = hasMvp
        ? '   - Implement the CORE DOMAIN LOGIC named in mvp-scope.md for real, not stubs '
            '(use the full spec for the exact rule details). Do NOT expand beyond the MVP scope.\n'
        : '   - Implement the CORE DOMAIN LOGIC for real, not stubs — especially the rules in the spec '
            '(for this ANDS/eCTD portal: dossier-ID validation, the eCTD validation rules, sequence/lifecycle, '
            'REP identifiers, CESG packaging model). Prioritize MUST requirements; COULD items may be scoped down.\n';
    return 'You are the ADF build agent. Build a complete, runnable, well-tested '
        'application for the feature "$featureId" in THIS repository.\n\n'
        '$scopeBlock'
        '1. READ THE SPEC FIRST (authoritative):\n'
        '   - $specDir/requirements.md      (verified EARS requirements — implement the MUST items)\n'
        '   - $specDir/problem-statement.md (vision, screens, workflows, integration design)\n'
        '   - $specDir/spec.md              (combined specification)\n'
        '   Also read requirement.md if present.\n\n'
        '2. BUILD (write all files under apps/$featureId/ — create the directory):\n'
        '   - Python 3 standard library ONLY (http.server, json, sqlite3, unittest, html). '
        'No pip installs, no external packages, no outbound network — it must run with `python3 server.py`.\n'
        '   - server.py: an HTTP server exposing a JSON API and serving a single-page HTML/JS UI.\n'
        '$implLine'
        '   - test_app.py: a unittest suite covering the core domain logic AND the API endpoints.\n'
        '   - README.md: how to run it.\n\n'
        '3. VERIFY YOURSELF — do NOT finish with failing tests:\n'
        '   - Run: cd apps/$featureId && python3 -m unittest -v\n'
        '   - Fix until ALL tests pass; confirm `python3 server.py` boots and serves, then stop it.\n\n'
        '4. FINISH with a short summary: files created, what domain logic is implemented, and the final '
        'test result (e.g. "14 tests, all passing").';
  }

  Future<String> _resolveWorkingDirectory(String featureId, int phase) async {
    if (phase != 7) return repoRoot;
    final run = store.readRunStatus(featureId);
    final taskId = run?['micro_task_id'] as String?;
    if (taskId == null || taskId.isEmpty) return repoRoot;

    final script = '$repoRoot/scripts/orch/adf_worktree.sh';
    if (!File(script).existsSync()) return repoRoot;

    final result = await Process.run(
      'bash',
      [script, 'path', featureId, taskId],
      workingDirectory: repoRoot,
    );
    if (result.exitCode != 0) return repoRoot;
    final path = (result.stdout as String).trim();
    if (path.isEmpty || !Directory(path).existsSync()) return repoRoot;
    return path;
  }

  void _logContextBudget(String featureId, int phase, String prompt) {
    final estimated = prompt.length ~/ 4;
    if (estimated <= contextBudgetWarnTokens) return;
    store.appendRunLog(featureId, {
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'level': 'warn',
      'stream': 'context_budget',
      'message':
          'context_budget_warn: ~$estimated tokens (target $contextBudgetWarnTokens)',
    });
    _traces.append(
      featureId: featureId,
      name: 'runner.context_budget_warn',
      event: 'runner',
      phase: phase,
      message: '~$estimated tokens',
    );
  }

  /// Per-turn model tiering (Phase 1 of the runner-efficiency plan). OFF unless
  /// `ADF_TIER_BUILD=1`. When on, mechanical heal work runs on the cheaper/faster
  /// Sonnet and critical / stuck work stays on the default (Opus). Returns a model
  /// id to override the backend default for this spawn, or null to use the default.
  ///
  /// STALL-AWARE: [healAttempt] is the CONSECUTIVE-no-progress streak — heal_attempts
  /// is reset to 0 by _reconcileDirectBuild every cycle the defect count drops. So
  /// while the loop is making progress the streak stays low and Sonnet drives the
  /// cheap one-by-one fixes; once it's genuinely STALLED (streak exceeds
  /// ADF_TIER_SONNET_MAX_NOPROGRESS, default 1) it escalates to Opus for the hard
  /// defect. Initial build + spec/plan/test phases always stay on the default model.
  String? _modelForTurn({required bool isHeal, int healAttempt = 0}) {
    if ((Platform.environment['ADF_TIER_BUILD']?.trim() ?? '0') != '1') {
      return null; // tiering off → backend default (behavior unchanged)
    }
    if (!isHeal || !_health.backend.buildsAppDirectly) {
      return null; // initial build / non-agentic → critical default (Opus)
    }
    final maxSonnet =
        int.tryParse(Platform.environment['ADF_TIER_SONNET_MAX_NOPROGRESS'] ?? '') ?? 1;
    if (healAttempt <= maxSonnet) {
      final s = Platform.environment['ADF_RUNNER_SONNET_MODEL']?.trim();
      return (s == null || s.isEmpty) ? 'sonnet' : s; // cheap while progressing
    }
    return null; // stalled → escalate to default (Opus)
  }

  /// RFC-4122 v4 UUID — the `--session-id` flag requires a valid UUID.
  String _uuidV4() {
    final r = Random.secure();
    final b = List<int>.generate(16, (_) => r.nextInt(256));
    b[6] = (b[6] & 0x0f) | 0x40; // version 4
    b[8] = (b[8] & 0x3f) | 0x80; // variant 10
    String h(int i) => b[i].toRadixString(16).padLeft(2, '0');
    return '${h(0)}${h(1)}${h(2)}${h(3)}-${h(4)}${h(5)}-${h(6)}${h(7)}'
        '-${h(8)}${h(9)}-${h(10)}${h(11)}${h(12)}${h(13)}${h(14)}${h(15)}';
  }

  Future<Map<String, dynamic>> _spawnAgent({
    required String featureId,
    required int phase,
    required String prompt,
    String? model,
  }) async {
    if (!await isHeadlessReady(refresh: true)) {
      final h = await getHealth(refresh: false);
      return {
        'success': false,
        'headless_unavailable': true,
        'hint': h['headless_hint'],
      };
    }

    _logContextBudget(featureId, phase, prompt);
    final hardCap = Platform.environment['ORCH_CONTEXT_HARD_CAP'] == 'true';
    if (hardCap && prompt.length ~/ 4 > contextBudgetHardCapTokens) {
      return {
        'success': false,
        'exit_code': -1,
        'error': 'context budget hard cap exceeded',
      };
    }

    final agent = _health.backend.resolveExecutable();
    if (agent == null) {
      final health = await getHealth(refresh: true);
      _writeNeedsLogin(featureId, phase, health);
      return {'success': false, 'exit_code': -1};
    }

    // Warm-session continuity (Phase 1, lever 1). OFF unless ADF_RUNNER_RESUME=1.
    // First turn for a feature passes --session-id <uuid> (stored in state); later
    // turns pass --resume <uuid>, which reuses the prompt cache (spike: ~9× cheaper).
    String? sessionId;
    var resumeSession = false;
    if ((Platform.environment['ADF_RUNNER_RESUME']?.trim() ?? '0') == '1' &&
        _health.backend.buildsAppDirectly) {
      final st = store.readState(featureId);
      final existing = (st['runner_session_id'] as String?)?.trim();
      if (existing != null && existing.isNotEmpty) {
        sessionId = existing;
        resumeSession = true;
      } else {
        sessionId = _uuidV4();
        st['runner_session_id'] = sessionId;
        store.writeState(featureId, st);
      }
    }

    final args = _health.backend.streamArgs(prompt, repoRoot,
        partial: true,
        model: model,
        sessionId: sessionId,
        resumeSession: resumeSession);

    store.appendRunLog(featureId, {
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'level': 'info',
      'stream': 'command',
      'message': prompt,
      'model': model ?? '(default)',
    });

    final cwd = await _resolveWorkingDirectory(featureId, phase);
    if (cwd != repoRoot) {
      store.appendRunLog(featureId, {
        'timestamp': DateTime.now().toUtc().toIso8601String(),
        'level': 'info',
        'stream': 'worktree',
        'message': 'phase $phase using worktree cwd: $cwd',
      });
    }

    final proc = await Process.start(agent, args,
        workingDirectory: cwd, environment: childEnvFor(featureId));
    _processes[featureId] = proc;
    // Headless agents (`claude -p`) take the prompt from argv and otherwise block
    // ~3s waiting on piped stdin ("no stdin data received in 3s"). Close it so they
    // start immediately. Harmless for argv-driven runners (agent_runner.py).
    try {
      unawaited(proc.stdin.close());
    } catch (_) {}
    final killTimer = Timer(maxRunDuration, () {
      if (_processes[featureId] == proc) {
        try {
          proc.kill(ProcessSignal.sigterm);
        } catch (_) {}
      }
    });
    // SLIDING INACTIVITY watchdog: instead of a fixed budget that kills a build
    // mid-work, this timer is RE-ARMED on every line the runner emits. While
    // Claude reasons or runs tools it streams events continuously, so it is never
    // killed for being slow — only for going truly SILENT (stuck/deadlocked) for
    // [runnerIdleTimeout]. On a stall we kill the group and fail with a clear
    // reason; the poller then re-invokes (the build is additive, so on-disk
    // progress is kept) — it never hangs.
    final idle = runnerIdleTimeout;
    var timedOut = false;
    Timer? idleTimer;
    void armIdle() {
      idleTimer?.cancel();
      idleTimer = Timer(idle, () {
        if (_processes[featureId] != proc) return;
        timedOut = true;
        store.appendRunLog(featureId, {
          'timestamp': DateTime.now().toUtc().toIso8601String(),
          'level': 'error',
          'stream': 'runner',
          'phase': phase,
          'message': 'no output for ${idle.inSeconds}s — runner appears stuck; '
              'killing and re-invoking (ORCH_RUNNER_IDLE_TIMEOUT_SEC)',
        });
        _killProcessGroup(proc);
      });
    }

    armIdle(); // start the clock; first output must arrive within the idle window
    final stdoutLines = <String>[];
    final stderrLines = <String>[];

    String? fullResultText;
    try {
      await for (final line
          in proc.stdout.transform(utf8.decoder).transform(const LineSplitter())) {
        armIdle(); // progress — the runner is alive; extend the deadline
        stdoutLines.add(line);
        _logLine(featureId, phase, 'stdout', line);
        _ingestAgentLine(featureId, phase, line);
        try {
          final obj = jsonDecode(line) as Map<String, dynamic>;
          if (obj['type'] == 'result') {
            _costs.recordFromResultEvent(featureId, obj, phase: phase);
            final t = obj['result'] as String?;
            if (t != null && t.trim().isNotEmpty) fullResultText = t.trim();
          }
        } catch (_) {}
      }
      await for (final line
          in proc.stderr.transform(utf8.decoder).transform(const LineSplitter())) {
        armIdle(); // stderr output is also progress — extend the deadline
        stderrLines.add(line);
        _logLine(featureId, phase, 'stderr', line);
      }
      idleTimer?.cancel(); // streams closed — runner is done, stop the watchdog

      final code = await proc.exitCode;
      final errText = stderrLines.join('\n').trim();
      final needsLogin = errText.toLowerCase().contains('authentication') ||
          errText.toLowerCase().contains('not logged in') ||
          errText.toLowerCase().contains('login');

      if (timedOut) {
        final reason =
            'runner stuck — no output for ${idle.inSeconds}s; killed and '
            're-invoking (ORCH_RUNNER_IDLE_TIMEOUT_SEC)';
        store.writeRunStatus(featureId, {
          'status': 'error',
          'agent_active': false,
          'phase': phase,
          'finished_at': DateTime.now().toUtc().toIso8601String(),
          'exit_code': code,
          'error': reason,
          'error_code': 'timed_out',
          'recovery_steps': RunnerHealth.recoverySteps,
        });
        _traces.append(
          featureId: featureId,
          name: 'runner.phase_timeout',
          event: 'runner',
          phase: phase,
          message: reason,
        );
        store.appendSystemMessage(
          featureId,
          'The builder went silent for ${idle.inSeconds}s and looked stuck, so '
          'ADF stopped it and will re-invoke to continue — work written so far '
          'is kept. Open Review to see progress.',
        );
        return {
          'success': false,
          'exit_code': code,
          'error': reason,
          'timed_out': true,
        };
      }

      if (code != 0) {
        final wasCancelled = _userCancelled.remove(featureId) ||
            code == 143 ||
            code == -15;
        if (wasCancelled) {
          return {'success': false, 'exit_code': code, 'cancelled': true};
        }
        if (needsLogin) _cachedHealth = null;
        final errorMsg = errText.isNotEmpty ? errText : 'exit $code';
        store.writeRunStatus(featureId, {
          'status': needsLogin ? 'needs_login' : 'error',
          'phase': phase,
          'finished_at': DateTime.now().toUtc().toIso8601String(),
          'exit_code': code,
          'error': errorMsg,
          'error_code': needsLogin ? 'needs_login' : 'agent_exit_$code',
          'recovery_steps': RunnerHealth.recoverySteps,
        });
        _traces.append(
          featureId: featureId,
          name: 'runner.phase_failed',
          event: 'runner',
          phase: phase,
          message: errorMsg,
        );
        if (needsLogin) {
          store.appendSystemMessage(
            featureId,
            'Sign-in required — the builder needs you to sign in before it can '
            'run. Complete the runner sign-in, then send your message again.',
          );
        } else {
          final healSoFar =
              (store.readState(featureId)['heal_attempts'] as num?)?.toInt() ??
                  0;
          // Only narrate a retry that will ACTUALLY happen. Once attempts are
          // exhausted, _scheduleSelfHeal emits the terminal "stopped after N
          // attempts" message instead — narrating "attempt 4 of 3" here was the
          // off-by-one the user saw.
          final msg = retryNarration(healSoFar, maxHealAttempts);
          if (msg != null) store.appendSystemMessage(featureId, msg);
          unawaited(_scheduleSelfHeal(featureId, phase, errorMsg, lastPrompt: prompt));
        }
        return {'success': false, 'exit_code': code, 'error': errText};
      }

      if (fullResultText != null) {
        store.writeLastAgentResponse(featureId, fullResultText);
      }

      _postSync.syncAfterRun(featureId, phase);

      // buildsAppDirectly (Claude/Opus one-shot): the agent wrote the entire app,
      // but the gated pipeline does not advance on its own — leaving it frozen at
      // the kickoff phase while a working app exists. Reconcile against the BUILT
      // APP, verifying the tests OURSELVES (never trust the agent's "tests pass",
      // per B2/B3) before advancing.
      var directBuildGreen = false;
      if (_health.backend.buildsAppDirectly && code == 0) {
        directBuildGreen = await _reconcileDirectBuild(featureId);
      }

      final after = store.readState(featureId);
      final nowAwaiting = after['awaiting_user'] == true;
      final verdict = after['last_judge_verdict'] as String?;
      // B2/B3: a phase-7 build that exits 0 but leaves tests_green=false is NOT a
      // success — it must read as blocked (with a cause), not idle, so the banner
      // and the chat stop contradicting reality ("tests passed" while blocked).
      final gatesAfter = after['gates'] as Map<String, dynamic>? ?? {};
      final testsGreen = gatesAfter['tests_green'] == true;
      // RELENTLESS: a direct (Claude/Opus) build that finished but whose tests
      // ADF could not verify green must ENGAGE the heal loop (status=error →
      // poller heals), not go idle/blocked on a half-built app. This holds even
      // when the agent exited non-zero (crash/kill): a crashed direct build still
      // needs healing, never a terminal 'blocked' — that's what stopped builds.
      final directBuildNeedsHeal =
          _health.backend.buildsAppDirectly && !directBuildGreen && !nowAwaiting;
      // 'blocked' is reserved for the @orch-protocol runner; a direct builder is
      // NEVER blocked on tests-not-green — it always re-enters the heal loop.
      final testsFailedAtImpl = !_health.backend.buildsAppDirectly &&
          phase >= 7 &&
          !nowAwaiting &&
          !testsGreen;
      store.writeRunStatus(featureId, {
        'status': nowAwaiting
            ? 'awaiting_approval'
            : directBuildNeedsHeal
                ? 'error' // engage the relentless heal loop, keep fighting to green
                : (testsFailedAtImpl ? 'blocked' : 'idle'),
        'agent_active': false,
        'phase': phase,
        'finished_at': DateTime.now().toUtc().toIso8601String(),
        'exit_code': code,
        'error': directBuildNeedsHeal
            ? 'Built app tests are not green yet — self-healing'
            : (testsFailedAtImpl
                ? 'Build ran but tests are not green at phase $phase'
                : null),
        'error_code': (directBuildNeedsHeal || testsFailedAtImpl)
            ? 'tests_not_green'
            : null,
        if (verdict != null) 'last_judge_verdict': verdict,
      });
      _traces.append(
        featureId: featureId,
        name: 'runner.phase_complete',
        event: 'runner',
        phase: phase,
        message: nowAwaiting
            ? 'Phase $phase complete — awaiting your approval (verdict: $verdict)'
            : 'Phase $phase finished',
      );
      // Durable, scrollable record of the outcome — so the chat doesn't go blank
      // when the live trace ends. (The user: "looks like nothing was built.")
      final outcomeHead =
          phaseOutcomeLine(phase, awaiting: nowAwaiting, testsGreen: testsGreen);
      // Strip emoji from the agent's verbatim tail — the dashboard's CanvasKit
      // build has no emoji font, so they render as tofu boxes (▯).
      final emoji = RegExp(
        r'[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2300}-\u{23FF}\u{2B00}-\u{2BFF}\uFE0F]',
        unicode: true,
      );
      final resultTail = (fullResultText ?? '')
          .replaceAll(emoji, '')
          .replaceAll(RegExp(r'  +'), ' ')
          .trim();
      store.appendSystemMessage(
        featureId,
        resultTail.isEmpty
            ? outcomeHead
            : '$outcomeHead\n\n${resultTail.length > 600 ? resultTail.substring(resultTail.length - 600) : resultTail}',
      );
      // A clean finish clears the interruption counters AND ends the warm runner
      // session, so the next build/edit starts fresh rather than resuming a
      // completed (and ever-growing) conversation.
      final hadChurn = ((after['heal_attempts'] as num?)?.toInt() ?? 0) > 0 ||
          ((after['orphan_resumes'] as num?)?.toInt() ?? 0) > 0;
      if (hadChurn || after.containsKey('runner_session_id')) {
        after['heal_attempts'] = 0;
        after['orphan_resumes'] = 0;
        after.remove('runner_session_id');
        store.writeState(featureId, after);
      }
      return {
        'success': true,
        'exit_code': code,
        'awaiting_approval': nowAwaiting,
        'verdict': verdict,
      };
    } finally {
      killTimer.cancel();
      idleTimer?.cancel();
      _processes.remove(featureId);
    }
  }

  /// Kills a spawned runner and everything it forked. The negative-pid form
  /// signals the whole process group when the runner is a group leader
  /// (runner scripts that setsid); the direct kill is the fallback.
  void _killProcessGroup(Process proc) {
    try {
      Process.killPid(-proc.pid, ProcessSignal.sigkill);
    } catch (_) {}
    try {
      proc.kill(ProcessSignal.sigkill);
    } catch (_) {}
  }

  String _wrapClientInputPrompt(String featureId, String userText) {
    final t = userText.trim();
    if (t.startsWith('@orch-orchestrator')) return t;
    return '''@orch-orchestrator sync $featureId

## Client input (must apply now)

$userText

Instructions:
1. Update `${store.paths.featureRel(featureId, 'requirement.md')}` with this clarification immediately.
2. If the client states this is a **standalone product** (not the POS app), document that explicitly in requirement and intake — do not assume POS scope.
3. Re-run intake/spec for the current phase and stop when awaiting user approval.''';
  }

  Future<void> _pollSelfHeal() async {
    for (final id in store.listFeatures()) {
      if (_active.contains(id) || _healing.contains(id)) continue;
      // A feature can be deleted or become corrupt (missing state.json) while
      // this background poll runs. Isolate each feature so one bad/vanished
      // directory can never throw out of the timer and crash the server.
      try {
        if (!store.featureExists(id)) continue;
        final run = store.readRunStatus(id);
        final status = run?['status'] as String?;
        if (status == 'error') {
          final phase =
              (run?['phase'] as num?)?.toInt() ?? _resolveRunPhase(id);
          final err = run?['error'] as String? ?? 'unknown error';
          await _scheduleSelfHeal(id, phase, err);
        } else if (status == 'idle' && _health.backend.buildsAppDirectly) {
          // RELENTLESS SAFETY NET (storm-proof, budget-safe): a direct build that
          // went 'idle' but is NOT actually complete must not sit forever. Re-route
          // it into the PROVEN, progress-based error->heal loop by simply marking
          // run-status 'error' — a single idempotent status write (NO spawn here,
          // so it can't storm; NOT orphan_resumes, so it never exhausts that cap).
          // The next poll's 'error' branch then heals it, and the heal budget
          // resets every cycle the defect count drops (relentless while improving).
          // Skip approval gates, cancellation, and genuinely-complete builds.
          if (_userCancelled.contains(id)) continue;
          final st = store.readState(id);
          if (st['awaiting_user'] == true) continue;
          final gates = (st['gates'] as Map<String, dynamic>?) ?? const {};
          final phase = (st['current_phase'] as num?)?.toInt() ??
              (run?['phase'] as num?)?.toInt() ?? 0;
          final complete = gates['review_approved'] == true ||
              (gates['tests_green'] == true && phase >= 7);
          if (!complete && phase >= 5) {
            store.writeRunStatus(id, {
              'status': 'error',
              'phase': phase,
              'finished_at': DateTime.now().toUtc().toIso8601String(),
              'error': 'build is idle but not complete — re-engaging the heal loop',
              'error_code': 'idle_incomplete',
              'recovery_steps': RunnerHealth.recoverySteps,
            });
          }
        } else if (status == 'needs_login') {
          final h = await getHealth(refresh: true);
          if (h['ready'] == true) {
            unawaited(enqueue(id, phase: (run?['phase'] as num?)?.toInt()));
          }
        } else if (staleRunSec > 0 &&
            (status == 'running' || status == 'queued' || status == 'healing')) {
          // Reaching here means run-status is non-terminal but this server is NOT
          // tracking the run (it passed the _active/_healing guard above) — the
          // orphan signature of a crash/restart that cut a build off mid-flight.
          // Resume it from where it left off instead of leaving it stuck forever.
          await _resumeOrphanedRun(id, run);
        }
      } catch (e) {
        stderr.writeln('self-heal: skipping feature $id — $e');
        continue;
      }
    }
  }

  /// Resume a run orphaned by an interruption (server crash/restart/kill). Only
  /// acts once the run is genuinely STALE (so we never fight a run mid-handoff),
  /// and escalates to blocked after [maxOrphanResumes] so a crash-looping run
  /// gets human attention rather than spinning forever.
  Future<void> _resumeOrphanedRun(String featureId, Map<String, dynamic>? run) async {
    if (_userCancelled.contains(featureId)) return;
    final ts = (run?['started_at'] ?? run?['queued_at'] ?? run?['finished_at'])
        as String?;
    final age = ageSeconds(ts, DateTime.now().toUtc());
    if (age != null && age < staleRunSec) return; // not stale yet — leave it be

    final phase = (run?['phase'] as num?)?.toInt() ?? _resolveRunPhase(featureId);
    final state = store.readState(featureId);
    final resumes = ((state['orphan_resumes'] as num?)?.toInt() ?? 0) + 1;
    if (resumes > maxOrphanResumes) {
      store.writeRunStatus(featureId, {
        'status': 'blocked',
        'phase': phase,
        'error': 'Run was interrupted and resumed $maxOrphanResumes times without '
            'completing — needs attention',
        'error_code': 'orphan_resume_exhausted',
        'recovery_steps': const [
          'Check the server/runner logs for why the run keeps dying',
          'Reset orphan_resumes in state.json and Retry',
        ],
      });
      return;
    }
    state['orphan_resumes'] = resumes;
    store.writeState(featureId, state);
    store.appendSystemMessage(
      featureId,
      'Resuming an interrupted build — the previous run was cut off mid-flight '
      '(resume #$resumes). Picking up from phase $phase; no progress is lost.',
    );
    _traces.append(
      featureId: featureId,
      name: 'runner.resume_orphan',
      event: 'runner',
      phase: phase,
      message: 'Resuming interrupted run (#$resumes) from phase $phase',
    );
    unawaited(enqueue(featureId, phase: phase));
  }

  Future<void> _scheduleSelfHeal(
    String featureId,
    int phase,
    String error, {
    String? lastPrompt,
  }) async {
    if (_userCancelled.contains(featureId)) return;
    if (_healing.contains(featureId)) return;
    final state = store.readState(featureId);
    final attempts = (state['heal_attempts'] as num?)?.toInt() ?? 0;
    if (attempts >= maxHealAttempts) {
      // NEVER STOP UNTIL BUILT. For a direct builder, hitting maxHealAttempts
      // no-progress attempts does NOT terminate the build — reset the streak and
      // keep fighting from a fresh progress baseline (the next attempt escalates
      // its strategy). Bounded only by a very high absolute backstop
      // (ORCH_MAX_HEAL_CYCLES, default 300 ≈ days of fighting) so a truly
      // pathological loop eventually surfaces to a human instead of burning
      // forever. The @orch-protocol runner keeps the original 'blocked' behavior.
      if (_health.backend.buildsAppDirectly) {
        final cycles = ((state['heal_cycles'] as num?)?.toInt() ?? 0) + 1;
        final maxCycles =
            int.tryParse(_env['ORCH_MAX_HEAL_CYCLES']?.trim() ?? '') ?? 300;
        if (cycles <= maxCycles) {
          state['heal_attempts'] = 0; // reset the no-progress streak
          state['heal_cycles'] = cycles;
          state.remove('heal_defect_count'); // fresh baseline for the new streak
          store.writeState(featureId, state);
          store.appendSystemMessage(
            featureId,
            'Self-heal hit $maxHealAttempts no-progress attempts, but the app is '
            'not a finished product yet — NOT stopping. Resetting and continuing '
            'to fight (cycle $cycles/$maxCycles).',
          );
          // fall through with heal_attempts reset to 0 → schedules another heal
        } else {
          state['status'] = 'blocked';
          store.writeState(featureId, state);
          store.writeRunStatus(featureId, {
            'status': 'blocked',
            'phase': phase,
            'error': 'Heal ran $maxCycles full cycles without reaching a finished '
                'product — surfacing to a human (likely a false positive or a '
                'genuinely hard blocker)',
            'error_code': 'heal_cycles_exhausted',
            'recovery_steps': const [
              'Review run-log.jsonl + the open defect worklist',
              'The top defect may be a false positive or need a human decision',
              'Raise ORCH_MAX_HEAL_CYCLES and Retry to keep fighting',
            ],
          });
          store.appendSystemMessage(
            featureId,
            'Self-heal fought $maxCycles full cycles and still cannot reach green '
            '— pausing for a human. Open Review to see the remaining worklist.',
          );
          return;
        }
      } else {
        state['status'] = 'blocked';
        store.writeState(featureId, state);
        store.writeRunStatus(featureId, {
          'status': 'blocked',
          'phase': phase,
          'error': '$maxHealAttempts consecutive heal attempts made no progress '
              '(defect count did not drop) — stuck',
          'error_code': 'heal_exhausted',
          'recovery_steps': [
            'Review run-log.jsonl for this feature',
            'Look at the top defect on the worklist — it may be a false positive or need a human',
            'Fix manually in your editor',
            'Reset heal_attempts in state.json and Retry',
          ],
        });
        store.appendSystemMessage(
          featureId,
          'Self-heal made no progress for $maxHealAttempts attempts in a row — the '
          'remaining defect(s) appear stuck. Open Review to see the worklist, or '
          'fix the top item and tap Retry to resume the loop.',
        );
        return;
      }
    }

    _healing.add(featureId);
    await Future<void>.delayed(const Duration(seconds: 2));

    try {
      final healed = await triggerSelfHeal(featureId, phase: phase, error: error);
      if (!healed['success'] && healed['heal_scheduled'] != true) {
        // Will be picked up by poller again if still error
      }
    } finally {
      _healing.remove(featureId);
    }
  }

  /// Runs orch-self-healer via the active runner. Returns result map.
  Future<Map<String, dynamic>> triggerSelfHeal(
    String featureId, {
    int? phase,
    required String error,
  }) async {
    final health = await getHealth(refresh: true);
    if (health['ready'] != true) {
      _writeNeedsLogin(featureId, phase, health);
      return {'success': false, 'heal_scheduled': false};
    }

    final state = store.readState(featureId);
    final attempts = (state['heal_attempts'] as num?)?.toInt() ?? 0;
    if (attempts >= maxHealAttempts) {
      return {'success': false, 'heal_scheduled': false, 'reason': 'max_attempts'};
    }

    final effectivePhase = phase ?? _resolveRunPhase(featureId);
    final nextAttempt = attempts + 1;
    state['heal_attempts'] = nextAttempt;
    store.writeState(featureId, state);

    final healPrompt = _healPrompt(featureId, effectivePhase, error, nextAttempt);

    store.writeRunStatus(featureId, {
      'status': 'healing',
      'phase': effectivePhase,
      'heal_attempt': nextAttempt,
      'started_at': DateTime.now().toUtc().toIso8601String(),
      'error': error,
      'error_code': 'self_heal',
    });

    store.appendRunLog(featureId, {
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'level': 'warn',
      'stream': 'self_heal',
      'message': 'Heal attempt $nextAttempt/$maxHealAttempts: $error',
    });

    _traces.append(
      featureId: featureId,
      name: 'runner.self_heal_start',
      event: 'runner',
      phase: effectivePhase,
      message: 'Self-heal $nextAttempt/$maxHealAttempts',
    );

    _active.add(featureId);
    try {
      return await _spawnAgent(
        featureId: featureId,
        phase: effectivePhase,
        prompt: healPrompt,
        model: _modelForTurn(isHeal: true, healAttempt: nextAttempt),
      );
    } finally {
      _active.remove(featureId);
    }
  }

  /// A rich failure diagnosis for the heal prompt: the caller's error PLUS the
  /// tail of the last build output (where the traceback / failing assertions
  /// live), so the agent root-causes instead of blind-regenerating.
  /// Severity rank parsed from a defect line like `[security-pentest/high] …`.
  /// Higher = fix first. Unlabeled defects are treated as high.
  static int _defectSeverity(String d) {
    final m = RegExp(r'\[[^/\]]+/(\w+)\]').firstMatch(d);
    switch (m?.group(1)?.toLowerCase()) {
      case 'critical':
        return 4;
      case 'high':
        return 3;
      case 'medium':
        return 2;
      case 'low':
        return 1;
      default:
        return 3;
    }
  }

  String _healDiagnosis(String featureId, String error) {
    final b = StringBuffer()..writeln(error.trim());
    // The RUNNING-APP defects (every test agent: UI, a11y, security, dup, e2e…)
    // the verification gate found — the exact things to fix that unit tests never
    // surface. Sorted hardest-first and presented as a NUMBERED worklist so the
    // heal agent fixes them ONE BY ONE, top to bottom, until the list is empty.
    final ui = [
      ...((store.readState(featureId)['ui_defects'] as List?) ?? const [])
          .map((e) => e.toString())
    ]..sort((a, z) => _defectSeverity(z).compareTo(_defectSeverity(a)));
    if (ui.isNotEmpty) {
      b.writeln('\n--- DEFECT WORKLIST (${ui.length} open; fix in this order, '
          'highest severity first) ---');
      var i = 1;
      for (final d in ui.take(25)) {
        b.writeln('$i. $d');
        i++;
      }
      if (ui.length > 25) b.writeln('…and ${ui.length - 25} more after these.');
    }
    final last = store.readLastAgentResponse(featureId);
    if (last != null && last.trim().isNotEmpty) {
      final tail =
          last.length > 1800 ? last.substring(last.length - 1800) : last;
      b
        ..writeln('\n--- tail of the last build output ---')
        ..writeln(tail.trim());
    }
    return b.toString().trim();
  }

  String _healPrompt(String featureId, int phase, String error, int attempt) {
    final diagnosis = _healDiagnosis(featureId, error);
    // CRITICAL: a buildsAppDirectly backend (Claude/Opus) CANNOT parse
    // `@orch-orchestrator` — feeding it that control command was a no-op that
    // burned a heal attempt. Hand it a real fix prompt with the actual failure
    // and a concrete verify command so each attempt is diagnosis-driven.
    if (_health.backend.buildsAppDirectly) {
      return '''
SELF-HEAL attempt $attempt — the build of `apps/$featureId` still has open defects. This loop is RELENTLESS: it keeps running as long as the defect count drops, so your job is to KILL DEFECTS, not to start over. Do NOT regenerate the app, do NOT weaken/skip/delete tests, do NOT shrink existing coverage.

Current state and the open defects:
$diagnosis

Work the DEFECT WORKLIST above ONE BY ONE, from the top (highest severity) down:
1. Take the FIRST defect on the list. Read the relevant code in `apps/$featureId/` (server.py, domain.py, the feature modules, test_app.py) and the spec in `specs/$featureId/`. Find its ROOT CAUSE — do not guess.
2. Apply the smallest correct fix for THAT defect. If it is a duplicate-code / repeated-UI-component finding, extract ONE shared helper/component and reuse it in every place (do not copy-paste); if it is an accessibility barrier, add the missing label/alt/name/lang; if it is a security finding, remediate it properly (parameterize SQL, escape output, remove the hardcoded secret); if it is a broken route / 5xx / console error / blank view, fix the handler or the JS.
3. Re-verify just that fix, then move to the NEXT defect. Repeat until you have addressed every item on the worklist.
4. Keep every existing test passing and ADD a test that locks in each fix where it makes sense.
5. Then run the FULL gate exactly as ADF will: `python3 -m unittest -v` in `apps/$featureId/` must print OK with 0 failures/0 errors, AND boot `python3 server.py` and exercise every view + every `/api/...` route the page calls — no 5xx, no traceback, no JS console error, no blank render, no accessibility barrier, no duplicated component.
Finish with one line: the final test count, how many defects you fixed, and "running app verified clean" once the worklist is empty.

If a specific defect proves a false positive, say so explicitly with the evidence — do not silently ignore it.
''';
    }
    return '''
@orch-orchestrator resume $featureId

AUTOMATED SELF-HEAL ($attempt/$maxHealAttempts): Orchestration runner failed on phase $phase.

Error:
$diagnosis

Instructions:
1. Diagnose root cause (do not weaken tests or gates)
2. Apply minimal fix and continue the current phase
3. Update state.json when phase can proceed
''';
  }

  void _logLine(String featureId, int phase, String stream, String line) {
    if (line.trim().isEmpty) return;
    final isResult = line.contains('"type":"result"') || line.contains('"type": "result"');
    store.appendRunLog(featureId, {
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'level': stream == 'stderr' ? 'error' : 'info',
      'stream': stream,
      'phase': phase,
      'message': isResult
          ? '[result event — see last-agent-response.md]'
          : (line.length > 500 ? '${line.substring(0, 500)}…' : line),
    });
  }

  Future<void> _bootstrap(String featureId, int phase) async {
    await Process.run(
      'python3',
      [
        'tools/orchestration_telemetry/bin/set_session.py',
        featureId,
        '--phase',
        '$phase',
        '--new-trace',
      ],
      workingDirectory: repoRoot,
    );

    final state = store.readState(featureId);
    if ((state['current_phase'] as num?)?.toInt() == 0 || phase == 1) {
      await Process.run(
        'bash',
        ['scripts/orch/sync_speckit_feature.sh', featureId],
        workingDirectory: repoRoot,
      );
    }
  }

  void _flushReasoningBuffer(String featureId, int phase) {
    final buf = _reasoningBuffers[featureId];
    if (buf == null || buf.isEmpty) return;
    final text = buf.toString().trim();
    buf.clear();
    if (text.isEmpty) return;
    // NL-narration: never surface a raw code/SQL/<<<FILE>>> dump as a "thought" —
    // the typed runner events already narrate the build in plain English, and the
    // full code persists to last-agent-response.md + the file viewer.
    if (isCodeDump(text)) return;
    _traces.append(
      featureId: featureId,
      name: 'agent.stream',
      event: 'afterAgentResponse',
      phase: phase,
      reasoning: text.length > 4000 ? '${text.substring(0, 4000)}…' : text,
    );
  }

  /// True when [text] is overwhelmingly code / SQL / a runner `<<<FILE>>>` block
  /// rather than natural-language narration — the server-side floor for the "no
  /// machine code in the live stream" rule. The per-line code/prose decision
  /// delegates to the shared, golden-pinned [CodeHeuristics] so the server and the
  /// client classifier never disagree (D3 SSOT); here we add only the multi-line
  /// `<<<FILE>>>` / fenced-block check.
  static bool isCodeDump(String text) {
    if (text.contains('<<<FILE:') || text.contains('```')) return true;
    return CodeHeuristics.isCodeLike(text);
  }

  /// Narration for a runner `file_write` progress event: `Writing <path> (i/n)`.
  static String fileWriteNarration(Map<String, dynamic> obj) {
    final path = obj['path'] ?? '?';
    final idx = obj['index'];
    final total = obj['total'];
    return (idx != null && total != null)
        ? 'Writing $path ($idx/$total)'
        : 'Writing $path';
  }

  /// Human-readable narration for the ADF runner's phase events. agent_runner.py
  /// emits these typed progress lines ('every action in words') so the Studio can
  /// show running commentary instead of a dark multi-minute pause. Returns null for
  /// an unrecognized type (the caller leaves the line for other handlers). Pure +
  /// static so it is unit-testable. HONESTY: verdict events (verify_stage_result /
  /// verify_result / policy_gate / policy_blocked / sealed / build_complete) carry
  /// the runner's REAL outcome — this only FORMATS what the runner reported; it
  /// never infers or asserts success on its own.
  static String? runnerNarration(Map<String, dynamic> obj, String type) {
    String s(Object? v) => '$v';
    final attempt = obj['attempt'];
    final stage = obj['stage'];
    switch (type) {
      case 'feature_resolved':
        return 'Resolved ${s(obj['fid'])} — ${s(obj['mode'])} mode '
            '(${s(obj['stack'])})';
      case 'reading_files':
        return 'Reading the current files to apply your edit…';
      case 'files_read':
        return 'Read ${s(obj['count'])} file(s)';
      case 'planning':
        return 'Planning the ${s(obj['mode'])}…';
      case 'scaffolding':
        return 'Scaffolding the ${s(obj['stack'])} template…';
      case 'scaffolded':
        return 'Scaffold ready (${s(obj['stack'])})';
      case 'warming_deps':
        return 'Installing dependencies (one-time)…';
      case 'deps_warm':
        return 'Dependencies ready (${s(obj['method'])})';
      case 'recall_injected':
        return 'Recalled past-failure guidance from the learning store';
      case 'generating':
        return 'Generating code (attempt ${s(attempt)})…';
      case 'generating_progress':
        // 'lines' from the streaming path; 'elapsed' (seconds) from the blocking
        // watchdog — either way a content-free liveness pulse.
        if (obj['lines'] != null) {
          return 'Generating code… (~${s(obj['lines'])} lines so far)';
        }
        if (obj['elapsed'] != null) {
          return 'Generating code… (${s(obj['elapsed'])}s)';
        }
        return 'Generating code…';
      case 'generated':
        return 'Generated ${s(obj['files'])} file(s) (attempt ${s(attempt)})';
      case 'writing_files':
        return 'Writing ${s(obj['total'])} file(s)…';
      case 'files_written':
        return 'Wrote ${s(obj['count'])} file(s)';
      case 'verifying':
        return 'Verifying the ${s(obj['stack'])} app (attempt ${s(attempt)})…';
      case 'verify_stage':
        return 'Running ${s(stage)}…';
      case 'verify_stage_result':
        return obj['ok'] == true ? '${s(stage)} passed ✓' : '${s(stage)} failed ✗';
      case 'verify_result':
        return obj['ok'] == true
            ? 'Verification passed ✓'
            : 'Verification failed — self-healing…';
      case 'completion_audit':
        return 'Completion audit: closing test-coverage gaps…';
      case 'self_heal':
        return 'Self-healing (attempt ${s(attempt)}): ${s(obj['reason'])}';
      case 'component_manifest':
        return 'Cataloged ${s(obj['count'])} reusable component(s)';
      case 'policy_gate':
        return obj['ok'] == true
            ? 'Policy gate passed ✓'
            : 'Policy gate: ${s(obj['n_violations'])} violation(s)';
      case 'policy_blocked':
        return '🚫 Blocked by policy: '
            '${(obj['rules'] as List?)?.join(', ') ?? ''}';
      case 'sealing':
        return 'Sealing the Proof of Build…';
      case 'sealed':
        return '🔏 Sealed Proof of Build ${s(obj['seal'])} over '
            '${s(obj['files'])} file(s)';
      case 'build_complete':
        return s(obj['status']);
      case 'building_apk':
        return 'Building the Android app (APK)…';
      case 'apk_built':
        return 'APK built ✓ — ${s(obj['detail'])}';
      case 'apk_failed':
        return 'APK skipped: ${s(obj['reason'])}';
      case 'emulator_preview':
        return 'Launching on a clean emulator…';
      case 'emulator_running':
        return 'Running in the emulator ✓';
      case 'tdd_red_check':
        return 'TDD: running tests against the scaffold (RED baseline)…';
      case 'tdd_red':
        return obj['ok'] == true
            ? 'TDD: tests fail before implementation ✓ (RED)'
            : 'TDD: tests pass with no implementation ⚠ (vacuous)';
      case 'process_blocked':
        return '🚫 Process gate BLOCKED: '
            '${(obj['disciplines'] as List?)?.join(', ') ?? ''} not attested';
      default:
        return null;
    }
  }

  /// Exposed for tests: feed one runner-stdout line through the live-narration
  /// path (in production this is driven by the spawned runner's stdout stream).
  void ingestAgentLine(String featureId, int phase, String line) =>
      _ingestAgentLine(featureId, phase, line);

  void _ingestAgentLine(String featureId, int phase, String line) {
    if (line.trim().isEmpty) return;
    try {
      final obj = jsonDecode(line) as Map<String, dynamic>;
      final type = obj['type'] as String? ?? obj['event'] as String?;

      if (type == 'tool_call' || type == 'tool_result') {
        _flushReasoningBuffer(featureId, phase);
        final extra = <String, dynamic>{};
        final toolName = obj['tool_name'] ?? obj['name'];
        if (toolName != null) extra['tool.name'] = '$toolName';
        final input = obj['input'] ?? obj['arguments'];
        if (input != null) {
          // Serialize as JSON, not Dart Map.toString() — `{file_path: x}` (no
          // quotes) is what the client's key parser could not read, degrading every
          // tool to "Reading a file" (D9). jsonEncode → `{"file_path":"x"}`.
          final s = input is String ? input : jsonEncode(input);
          extra['tool.input'] = s.length > 2000 ? '${s.substring(0, 2000)}…' : s;
        }
        final output = obj['output'] ?? obj['result'];
        if (output != null && type == 'tool_result') {
          final s = output is String ? output : jsonEncode(output);
          extra['tool.output'] = s.length > 2000 ? '${s.substring(0, 2000)}…' : s;
        }
        _traces.append(
          featureId: featureId,
          name: 'tool.$type',
          event: 'tool',
          phase: phase,
          extra: extra,
        );
        return;
      }

      if (type == 'file_write') {
        // The runner narrates each file as it writes it, so a 1-3 min build
        // doesn't go dark. Surface it as a live span.
        _flushReasoningBuffer(featureId, phase);
        final fw = <String, dynamic>{};
        if (obj['path'] != null) fw['runner.path'] = '${obj['path']}';
        if (obj['index'] != null) fw['runner.index'] = obj['index'];
        if (obj['total'] != null) fw['runner.total'] = obj['total'];
        _traces.append(
          featureId: featureId,
          name: 'file.write',
          event: 'runner',
          phase: phase,
          message: fileWriteNarration(obj),
          extra: fw.isEmpty ? null : fw,
        );
        return;
      }

      // ADF runner phase narration — 'every action in words'. agent_runner.py emits
      // typed progress events (feature_resolved, scaffolding, generating, verifying,
      // verify_stage(_result), policy_gate, sealing/sealed, build_complete, …); each
      // becomes a live span so the Studio shows running commentary, not dead air.
      // Without this branch these valid-JSON lines fall through and are dropped.
      final narration = type == null ? null : runnerNarration(obj, type);
      if (narration != null) {
        _flushReasoningBuffer(featureId, phase);
        // Carry the runner's STRUCTURED truth alongside the prose so the Studio's
        // verdict pills bind to the real ok flag / seal — never a string match on
        // the message. This is the honesty seam: a green pill requires runner.ok==true.
        final extra = <String, dynamic>{};
        if (obj['ok'] is bool) extra['runner.ok'] = obj['ok'];
        if (obj['stage'] != null) extra['runner.stage'] = '${obj['stage']}';
        if (obj['seal'] != null) extra['runner.seal'] = '${obj['seal']}';
        if (obj['status'] != null) extra['runner.status'] = '${obj['status']}';
        _traces.append(
          featureId: featureId,
          name: 'runner.$type',
          event: 'runner',
          phase: phase,
          message: narration,
          extra: extra.isEmpty ? null : extra,
        );
        return;
      }

      if (type == 'result') {
        _flushReasoningBuffer(featureId, phase);
        final resultText = obj['result'] as String? ?? '';
        // The full result (often large <<<FILE>>> code blocks) already persists to
        // last-agent-response.md + the file viewer. Surface a NL summary, never the
        // code dump. A genuine prose result (e.g. a chat answer) is kept, trimmed.
        final fileCount = RegExp(r'<<<FILE:').allMatches(resultText).length;
        if (fileCount > 0) {
          _traces.append(
            featureId: featureId,
            name: 'runner.build_summary',
            event: 'runner',
            phase: phase,
            message: 'Build complete — wrote $fileCount file(s)',
          );
        } else if (resultText.trim().isNotEmpty && !isCodeDump(resultText)) {
          // A genuine prose answer (chat result, no <<<FILE>>>): keep it nearly
          // whole — the 2000 cap was for code dumps, which the isCodeDump guard
          // above already excludes here.
          _traces.append(
            featureId: featureId,
            name: 'agent.result',
            event: 'afterAgentResponse',
            phase: phase,
            reasoning: resultText.length > 8000
                ? '${resultText.substring(0, 8000)}…'
                : resultText,
          );
        }
        _reasoningBuffers.remove(featureId);
        return;
      }

      if (type == 'thinking' ||
          obj['subtype'] == 'thinking' ||
          obj['subtype'] == 'thought') {
        final text = (_extractText(obj) ?? obj['text'] as String?)?.trim();
        if (text != null && text.isNotEmpty) {
          _flushReasoningBuffer(featureId, phase);
          _traces.append(
            featureId: featureId,
            name: 'agent.thought',
            event: 'afterAgentThought',
            phase: phase,
            reasoning: text.length > 4000 ? '${text.substring(0, 4000)}…' : text,
          );
        }
        return;
      }

      if (type == 'text') {
        // Raw per-token _stream_delta path — this is where the model emits the
        // <<<FILE>>> code / SQL / TSX token-by-token. We do NOT surface the raw
        // code stream; the live commentary comes from the typed runner events
        // (generating / writing_files / verifying …) and completed assistant turns.
        return;
      }

      if (type == 'assistant' || type == 'message') {
        // NOTE: the default Python runner (agent_runner.py) emits neither
        // 'assistant' nor 'message' — its live narration comes from the typed
        // narrate() events + the result summary. This reasoning-buffer path is
        // LIVE only for a custom runner CLI that streams assistant/message
        // chunks (D11).
        final text = _extractText(obj);
        if (text == null || text.isEmpty) return;
        _reasoningBuffers.putIfAbsent(featureId, () => StringBuffer());
        _reasoningBuffers[featureId]!.write(text);
        if (_reasoningBuffers[featureId]!.length >= 60) {
          _flushReasoningBuffer(featureId, phase);
        }
        return;
      }
    } catch (_) {
      if (line.length > 4) {
        // Non-JSON runner stdout (tracebacks, npm/tsc logs). Route to a typed STEP
        // card (runner.* → isRunnerControlEvent) so it stays OUT of the NL prose
        // stream but remains visible. Strip ANSI + collapse whitespace.
        final clean = line
            .replaceAll(RegExp(r'\x1b\[[0-9;]*m'), '')
            .replaceAll(RegExp(r'\s+'), ' ')
            .trim();
        if (clean.isNotEmpty) {
          _traces.append(
            featureId: featureId,
            name: 'runner.stdout',
            event: 'runner',
            phase: phase,
            message:
                'Runner: ${clean.length > 120 ? '${clean.substring(0, 120)}…' : clean}',
          );
        }
      }
    }
  }

  String? _extractText(Map<String, dynamic> obj) {
    if (obj['text'] is String) return obj['text'] as String;
    final msg = obj['message'];
    if (msg is Map) {
      final content = msg['content'];
      if (content is List) {
        final buf = StringBuffer();
        for (final block in content) {
          if (block is Map &&
              block['type'] == 'text' &&
              block['text'] is String) {
            buf.write(block['text']);
          }
        }
        if (buf.isNotEmpty) return buf.toString();
      }
    }
    final delta = obj['delta'];
    if (delta is Map && delta['text'] is String) return delta['text'] as String;
    return null;
  }
}
