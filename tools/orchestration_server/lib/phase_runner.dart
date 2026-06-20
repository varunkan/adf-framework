import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'code_heuristics.dart';
import 'cost_meter.dart';
import 'feature_store.dart';
import 'runner_health.dart';
import 'run_post_sync.dart';
import 'trace_writer.dart';

enum CancelReason { user, replaced }

/// Runs orchestration phases via headless `cursor-agent` (or CURSOR_API_KEY).
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

  /// Outer self-heal attempts the Dart layer makes after a runner failure. The
  /// file-writing runner ALREADY self-heals internally (ADF_RUNNER_FIX_ITERS,
  /// default 3), so a hardcoded 3 here meant up to ~9 cold rebuilds per phase.
  /// Configurable via ORCH_MAX_HEAL_ATTEMPTS; the local-LLM launcher now defaults
  /// it to 3 (matching the hardcoded fallback) so a transient runner failure
  /// retries instead of giving up after one attempt — see the "build stopped
  /// after 1 attempt" fix in run_server_local_llm.sh.
  int get maxHealAttempts {
    final raw = int.tryParse(_env['ORCH_MAX_HEAL_ATTEMPTS']?.trim() ?? '');
    return raw != null && raw >= 0 ? raw : 3;
  }

  final FeatureStore store;
  final Duration pollInterval;
  final RunnerHealth _health;
  final CostMeter _costs;
  final Map<String, String> _env;

  /// Wall-clock budget for one spawned runner-CLI agent
  /// (`ORCH_RUNNER_TIMEOUT_SEC`, default 30s). Breach kills the process
  /// group and fails the run instead of letting it hang. Invalid or
  /// non-positive values fall back to the default.
  Duration get runnerTimeout {
    final raw = int.tryParse(_env['ORCH_RUNNER_TIMEOUT_SEC']?.trim() ?? '');
    return Duration(seconds: raw == null || raw <= 0 ? 30 : raw);
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
    return {
      ..._env,
      ...nonInteractiveEnv,
      'ADF_STACK': store.stackFor(featureId),
      'ADF_FEATURE_ID': featureId,
    };
  }

  /// Force every spawned tool (the runner, the real coding-agent CLIs, and any
  /// git/pip/npm they shell) into non-interactive mode so none blocks on a pager
  /// or a credential prompt and dies only at the timeout. Mirrors the Python
  /// runner's NON_INTERACTIVE_ENV (scripts/orch/agent_runner.py) — adopted from
  /// oh-my-pi; see docs/ADF_VS_OH_MY_PI.md §5.2.
  static const Map<String, String> nonInteractiveEnv = {
    'CI': '1',
    'NO_COLOR': '1',
    'PAGER': 'cat',
    'GIT_PAGER': 'cat',
    'MANPAGER': 'cat',
    'GIT_TERMINAL_PROMPT': '0',
    'GIT_EDITOR': 'true',
    'GCM_INTERACTIVE': 'never',
    'DEBIAN_FRONTEND': 'noninteractive',
    'PYTHONUNBUFFERED': '1',
    'PIP_NO_INPUT': '1',
    'npm_config_yes': 'true',
    'npm_config_audit': 'false',
    'npm_config_fund': 'false',
    'npm_config_progress': 'false',
  };

  late TraceWriter _traces;
  final Set<String> _active = {};
  final Set<String> _healing = {};
  final Set<String> _userCancelled = {};
  final Map<String, Process> _processes = {};
  final Map<String, StringBuffer> _reasoningBuffers = {};
  static const Duration maxRunDuration = Duration(minutes: 90);
  Timer? _timer;
  bool _started = false;
  Map<String, dynamic>? _cachedHealth;

  String get repoRoot => store.repoRoot;

  /// Whether headless `cursor-agent --print` is usable (distinct from auth [ready]).
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
      'resume_mode': 'cursor_ide',
      'headless_unavailable': true,
      'hint': hint ??
          'Headless cursor-agent unavailable — paste the prompt in Cursor IDE, then Sync.',
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
        'cursor-agent --print produced no output within 20s — use Cursor IDE '
        'or kill stuck agents (pkill -f "cursor-agent.*--print")';

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
                : 'cursor-agent not responding — install or run cursor-agent login',
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
        'resume_mode': 'cursor_ide',
        'headless_unavailable': true,
        'hint': health['headless_hint'] as String? ??
            'Headless agent unavailable — use Cursor IDE',
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

  /// Clear stale `running` / `agent_active` when no live cursor-agent process.
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
          'resume_mode': 'cursor_ide',
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
        message: 'Starting cursor-agent for phase $phase',
      );

      final state = store.readState(featureId);
      final awaiting = state['awaiting_user'] == true;
      final prompt = awaiting
          ? '@orch-orchestrator sync $featureId'
          : '@orch-orchestrator resume $featureId';

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

  Future<Map<String, dynamic>> _spawnAgent({
    required String featureId,
    required int phase,
    required String prompt,
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

    final args = _health.backend.streamArgs(prompt, repoRoot, partial: true);

    store.appendRunLog(featureId, {
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'level': 'info',
      'stream': 'command',
      'message': prompt,
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
    final killTimer = Timer(maxRunDuration, () {
      if (_processes[featureId] == proc) {
        try {
          proc.kill(ProcessSignal.sigterm);
        } catch (_) {}
      }
    });
    // Hard per-run budget: a runner that produces nothing within the budget
    // is killed (whole process group) and the run fails with a clear reason.
    final budget = runnerTimeout;
    var timedOut = false;
    final timeoutTimer = Timer(budget, () {
      if (_processes[featureId] != proc) return;
      timedOut = true;
      store.appendRunLog(featureId, {
        'timestamp': DateTime.now().toUtc().toIso8601String(),
        'level': 'error',
        'stream': 'runner',
        'phase': phase,
        'message': 'timed_out after ${budget.inSeconds}s '
            '(ORCH_RUNNER_TIMEOUT_SEC)',
      });
      _killProcessGroup(proc);
    });
    final stdoutLines = <String>[];
    final stderrLines = <String>[];

    String? fullResultText;
    try {
      await for (final line
          in proc.stdout.transform(utf8.decoder).transform(const LineSplitter())) {
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
        stderrLines.add(line);
        _logLine(featureId, phase, 'stderr', line);
      }

      final code = await proc.exitCode;
      final errText = stderrLines.join('\n').trim();
      final needsLogin = errText.toLowerCase().contains('authentication') ||
          errText.toLowerCase().contains('not logged in') ||
          errText.toLowerCase().contains('login');

      if (timedOut) {
        final reason =
            'timed_out after ${budget.inSeconds}s (ORCH_RUNNER_TIMEOUT_SEC)';
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
          'Build timed out after ${budget.inSeconds}s. '
          'Tap "Reset & retry" to run again, or open Review to see what was '
          'written so far.',
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
          final attempt =
              ((store.readState(featureId)['heal_attempts'] as num?)?.toInt() ??
                      0) +
                  1;
          store.appendSystemMessage(
            featureId,
            'Build hit a problem — fixing and retrying automatically '
            '(attempt $attempt of $maxHealAttempts)…',
          );
          unawaited(_scheduleSelfHeal(featureId, phase, errorMsg, lastPrompt: prompt));
        }
        return {'success': false, 'exit_code': code, 'error': errText};
      }

      if (fullResultText != null) {
        store.writeLastAgentResponse(featureId, fullResultText);
      }

      _postSync.syncAfterRun(featureId, phase);

      final after = store.readState(featureId);
      final nowAwaiting = after['awaiting_user'] == true;
      final verdict = after['last_judge_verdict'] as String?;
      store.writeRunStatus(featureId, {
        'status': nowAwaiting ? 'awaiting_approval' : 'idle',
        'agent_active': false,
        'phase': phase,
        'finished_at': DateTime.now().toUtc().toIso8601String(),
        'exit_code': code,
        'error': null,
        'error_code': null,
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
      final outcomeHead = nowAwaiting
          ? 'Build complete — Phase $phase is ready for your review and approval.'
          : 'Build complete — Phase $phase finished; the build ran and tests passed.';
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
      if (((after['heal_attempts'] as num?)?.toInt() ?? 0) > 0) {
        after['heal_attempts'] = 0;
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
      timeoutTimer.cancel();
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
        } else if (status == 'needs_login') {
          final h = await getHealth(refresh: true);
          if (h['ready'] == true) {
            unawaited(enqueue(id, phase: (run?['phase'] as num?)?.toInt()));
          }
        }
      } catch (e) {
        stderr.writeln('self-heal: skipping feature $id — $e');
        continue;
      }
    }
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
      state['status'] = 'blocked';
      store.writeState(featureId, state);
      store.writeRunStatus(featureId, {
        'status': 'blocked',
        'phase': phase,
        'error': 'Max heal attempts ($maxHealAttempts) reached',
        'error_code': 'heal_exhausted',
        'recovery_steps': [
          'Review run-log.jsonl for this feature',
          'Fix manually in Cursor',
          'Reset heal_attempts in state.json and Retry',
        ],
      });
      store.appendSystemMessage(
        featureId,
        'Build stopped after $maxHealAttempts attempts. '
        'Tap "Reset & retry" to start the build over, or open Review to read '
        'the build log and see where it got stuck.',
      );
      return;
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

  /// Runs orch-self-healer via cursor-agent. Returns result map.
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
      );
    } finally {
      _active.remove(featureId);
    }
  }

  String _healPrompt(String featureId, int phase, String error, int attempt) {
    return '''
@orch-orchestrator resume $featureId

AUTOMATED SELF-HEAL ($attempt/$maxHealAttempts): Orchestration runner failed on phase $phase.

Error:
$error

Instructions:
1. Read .cursor/skills/orch-self-healer/SKILL.md
2. Diagnose root cause (do not weaken tests or gates)
3. Apply minimal fix and continue the current phase
4. Update state.json when phase can proceed
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
        return 'Generating code… (~${s(obj['lines'])} lines so far)';
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
          extra['tool.input'] = '$input'.length > 2000
              ? '${'$input'.substring(0, 2000)}…'
              : '$input';
        }
        final output = obj['output'] ?? obj['result'];
        if (output != null && type == 'tool_result') {
          extra['tool.output'] = '$output'.length > 2000
              ? '${'$output'.substring(0, 2000)}…'
              : '$output';
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
