import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'feature_store.dart';
import 'runner_health.dart';
import 'run_post_sync.dart';
import 'trace_writer.dart';

enum CancelReason { user, replaced }

/// Runs orchestration phases via headless `cursor-agent` (or CURSOR_API_KEY).
class PhaseRunner {
  PhaseRunner(this.store, {this.pollInterval = const Duration(seconds: 2)})
      : _health = RunnerHealth(repoRoot: store.repoRoot);

  static const int maxHealAttempts = 3;

  final FeatureStore store;
  final Duration pollInterval;
  final RunnerHealth _health;

  RunnerHealth get health => _health;

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

    final agent = _health.resolveCursorAgent();
    if (agent == null) {
      final health = await getHealth(refresh: true);
      _writeNeedsLogin(featureId, phase, health);
      return {'success': false, 'exit_code': -1};
    }

    final args = <String>[
      '--print',
      '--trust',
      '--workspace',
      repoRoot,
      '--output-format',
      'stream-json',
      '--stream-partial-output',
      prompt,
    ];

    if (Platform.environment['CURSOR_API_KEY']?.isNotEmpty == true) {
      args.insert(0, '--api-key');
      args.insert(1, Platform.environment['CURSOR_API_KEY']!);
    }

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

    final proc = await Process.start(agent, args, workingDirectory: cwd);
    _processes[featureId] = proc;
    final killTimer = Timer(maxRunDuration, () {
      if (_processes[featureId] == proc) {
        try {
          proc.kill(ProcessSignal.sigterm);
        } catch (_) {}
      }
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
        if (!needsLogin) {
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
      _processes.remove(featureId);
    }
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
      final run = store.readRunStatus(id);
      final status = run?['status'] as String?;
      if (status == 'error') {
        final phase = (run?['phase'] as num?)?.toInt() ?? _resolveRunPhase(id);
        final err = run?['error'] as String? ?? 'unknown error';
        await _scheduleSelfHeal(id, phase, err);
      } else if (status == 'needs_login') {
        final h = await getHealth(refresh: true);
        if (h['ready'] == true) {
          unawaited(enqueue(id, phase: (run?['phase'] as num?)?.toInt()));
        }
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
    _traces.append(
      featureId: featureId,
      name: 'agent.stream',
      event: 'afterAgentResponse',
      phase: phase,
      reasoning: text.length > 4000 ? '${text.substring(0, 4000)}…' : text,
    );
  }

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

      if (type == 'result') {
        _flushReasoningBuffer(featureId, phase);
        final resultText = obj['result'] as String? ?? '';
        if (resultText.trim().isNotEmpty) {
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

      if (type == 'assistant' || type == 'text' || type == 'message') {
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
        _traces.append(
          featureId: featureId,
          name: 'agent.stdout',
          event: 'runner',
          phase: phase,
          message: line.length > 500 ? '${line.substring(0, 500)}…' : line,
        );
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
