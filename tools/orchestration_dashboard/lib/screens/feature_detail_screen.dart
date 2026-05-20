import 'dart:async';

import 'package:flutter/material.dart';

import '../main.dart';
import '../services/api_client.dart';
import '../theme/orchestration_colors.dart';
import '../widgets/agent_conversation_view.dart';
import '../widgets/approval_action_bar.dart';
import '../widgets/chat_composer.dart';
import '../widgets/feature_inspector.dart';
import '../widgets/orchestration_shell.dart';
import '../widgets/pipeline_rail.dart';

class FeatureDetailScreen extends StatefulWidget {
  const FeatureDetailScreen({
    super.key,
    required this.api,
    required this.featureId,
  });

  final ApiClient api;
  final String featureId;

  @override
  State<FeatureDetailScreen> createState() => _FeatureDetailScreenState();
}

class _FeatureDetailScreenState extends State<FeatureDetailScreen> {
  Map<String, dynamic>? _detail;
  Map<String, dynamic>? _runnerHealth;
  bool _loading = true;
  bool _starting = false;
  int _viewPhase = 0;
  Timer? _poll;
  bool _loadInFlight = false;
  int _pollTick = 0;
  bool _autoSynced = false;
  bool _autoUnstuck = false;
  final ScrollController _chatScroll = ScrollController();
  final List<Map<String, dynamic>> _optimisticMessages = [];
  Map<String, dynamic>? _artifactChecklist;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) {
      _pollTick++;
      _load(silent: true, refreshRunner: _pollTick % 15 == 0);
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _chatScroll.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false, bool refreshRunner = true}) async {
    if (_loadInFlight) return;
    _loadInFlight = true;
    if (!silent) setState(() => _loading = true);
    try {
      var d = await widget.api.getFeature(widget.featureId);
      final run0 = d['run_status'] as Map<String, dynamic>?;
      final state0 = d['state'] as Map<String, dynamic>? ?? {};
      final stuck = run0?['agent_active'] == true &&
          (state0['awaiting_user'] == true ||
              run0?['status'] == 'awaiting_approval');
      if (!_autoUnstuck && stuck) {
        _autoUnstuck = true;
        try {
          final unstuck = await widget.api.unstickFeature(widget.featureId);
          final feature = unstuck['feature'] as Map<String, dynamic>?;
          if (feature != null) d = feature;
        } catch (_) {}
      }
      Map<String, dynamic>? h = _runnerHealth;
      if (refreshRunner || h == null) {
        try {
          h = await widget.api.getRunnerHealth(refresh: refreshRunner);
        } catch (_) {
          h ??= _runnerHealth;
        }
      }
      Map<String, dynamic>? checklist;
      final state = d['state'] as Map<String, dynamic>? ?? {};
      final awaiting = state['awaiting_user'] == true;
      final phase = (state['pending_approval_phase'] as num?)?.toInt() ??
          (state['current_phase'] as num?)?.toInt() ??
          0;
      if (awaiting && phase >= 2 && phase <= 4) {
        try {
          checklist = await widget.api.getArtifactChecklist(
            widget.featureId,
            phase: phase,
          );
        } catch (_) {}
      }
      if (!mounted) return;
      final verdict = d['judge_verdict'] as String?;
      if (!_autoSynced && verdict != null && verdict.isNotEmpty && !awaiting) {
        _autoSynced = true;
        try {
          final synced = await widget.api.syncState(widget.featureId);
          final feature = synced['feature'] as Map<String, dynamic>?;
          if (feature != null && mounted) {
            _applyDetail(feature, h);
            return;
          }
        } catch (_) {}
      }
      if (!mounted) return;
      setState(() => _artifactChecklist = checklist);
      _applyDetail(d, h);
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      if (!silent) showMessage(context, e.toString());
    } finally {
      _loadInFlight = false;
    }
  }

  void _applyDetail(Map<String, dynamic> d, Map<String, dynamic>? h) {
    final phase = ((d['state'] as Map<String, dynamic>?)?['current_phase']
            as num?)
        ?.toInt() ??
        0;
    final serverConv =
        (d['conversation'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ??
            [];
    if (_optimisticMessages.isNotEmpty && serverConv.isNotEmpty) {
      final lastServer = serverConv.last['text'] as String?;
      _optimisticMessages.removeWhere(
        (m) => m['text'] == lastServer || serverConv.any((s) => s['text'] == m['text']),
      );
    }
    setState(() {
      _detail = d;
      _runnerHealth = h;
      _loading = false;
      if (_viewPhase == 0 && phase > 0) _viewPhase = phase;
    });
  }

  int get _phase {
    final state = _detail?['state'] as Map<String, dynamic>?;
    return (state?['current_phase'] as num?)?.toInt() ?? 0;
  }

  int get _pendingPhase {
    final state = _detail?['state'] as Map<String, dynamic>?;
    return (state?['pending_approval_phase'] as num?)?.toInt() ?? _phase;
  }

  String? get _runStatus {
    final run = _detail?['run_status'] as Map<String, dynamic>?;
    return run?['status'] as String?;
  }

  /// True while cursor-agent is working (including background revise during approval).
  bool get _agentActive {
    final run = _detail?['run_status'] as Map<String, dynamic>?;
    if (run?['agent_active'] == true) return true;
    final s = _runStatus;
    return s == 'queued' || s == 'running' || s == 'healing';
  }

  bool get _awaitingRevision {
    final state = _detail?['state'] as Map<String, dynamic>? ?? {};
    return state['awaiting_user'] == true && !_verdictPassed;
  }

  /// Approval gate — includes recovery when revise was recorded but awaiting_user was cleared.
  bool get _showApprovalGate {
    final state = _detail?['state'] as Map<String, dynamic>? ?? {};
    if (state['awaiting_user'] == true) return true;
    final pending = state['pending_approval_phase'] as num?;
    final verdict = _judgeVerdict;
    return pending != null && verdict != 'pass' && state['status'] == 'active';
  }

  /// Cancel / busy — agent may still be running in the background.
  bool get _isRunning => _agentActive;

  /// Live trace polling + pulsing UI — off during revision gate to avoid endless spinner.
  bool get _showAgentActivityUi => _agentActive && !_awaitingRevision;

  bool get _runnerReady => _runnerHealth?['ready'] == true;

  bool get _headlessReady => _runnerHealth?['headless_ready'] == true;

  Map<String, dynamic>? get _pipeline =>
      _detail?['pipeline'] as Map<String, dynamic>?;

  List<Map<String, dynamic>> get _phases =>
      (_pipeline?['phases'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ??
      [];

  String? get _currentStepId => _pipeline?['current_step_id'] as String?;

  String get _judgeVerdict {
    final state = _detail?['state'] as Map<String, dynamic>? ?? {};
    return (state['last_judge_verdict'] as String? ?? 'revise').toLowerCase();
  }

  bool get _verdictPassed => _judgeVerdict == 'pass';

  bool get _artifactPassed => _artifactChecklist?['pass'] != false;

  List<Map<String, String>> _quickActions() {
    final state = _detail?['state'] as Map<String, dynamic>? ?? {};
    final awaiting = state['awaiting_user'] == true;
    final phase = _pendingPhase > 0 ? _pendingPhase : _phase;

    return [
      if (awaiting && !_verdictPassed)
        {
          'label': 'Redo w/ feedback',
          'prompt': _clarifyPrompt(
            phase,
            _judgeVerdict,
            '',
            clientConfirmed: false,
          ),
        },
      {
        'label': 'Resume',
        'prompt': '@orch-orchestrator resume ${widget.featureId}',
      },
      {
        'label': 'Sync',
        'prompt': '@orch-orchestrator sync ${widget.featureId}',
      },
      if (_promptForCurrentStep() != null)
        {
          'label': 'Current step',
          'prompt': _promptForCurrentStep()!,
        },
    ];
  }

  String? get _combinedRecommendation =>
      _detail?['combined_recommendation'] as String?;

  String _clarifyPrompt(
    int phase,
    String verdict,
    String notes, {
    required bool clientConfirmed,
  }) {
    final combined = _combinedRecommendation?.trim() ?? '';
    final clarification = notes.trim().isEmpty
        ? '(No extra client notes — combined recommendation is the primary feedback.)'
        : notes.trim();
    final combinedBlock = combined.isNotEmpty
        ? '''

## Combined recommendation (authoritative feedback loop)
$combined'''
        : '\n(Read judge-verdicts/phase-$phase.md for combined recommendation.)';

    return '''@orch-orchestrator revise ${widget.featureId}

Phase $phase — judge verdict: ${verdict.toUpperCase()}
Client confirmed: ${clientConfirmed ? 'YES' : 'NO'} — proceed only with confirmed direction.
$combinedBlock

## Additional client notes
$clarification

## Required actions
1. Treat the **combined recommendation** as the feedback loop — do not advance gates until addressed.
2. Update `requirement.md`, Spec Kit `specs/${widget.featureId}/plan.md` (and spec/tasks as needed), and phase artifacts (`00-intake.md`, etc.).
3. Ask the client any remaining clarifying questions in chat before large scope changes.
4. Re-run phase $phase builders and BMAD review until judge verdict is **PASS**.''';
  }

  String? _promptForCurrentStep() {
    if (_currentStepId == null) return null;
    for (final ph in _phases) {
      final steps =
          (ph['steps'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ?? [];
      for (final s in steps) {
        if (s['id'] == _currentStepId) {
          return s['cursor_command'] as String?;
        }
      }
    }
    return '@orch-orchestrator resume ${widget.featureId}';
  }

  List<Map<String, dynamic>> _mergedConversation() {
    final server =
        (_detail?['conversation'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ??
            [];
    if (_optimisticMessages.isEmpty) return server;
    return [...server, ..._optimisticMessages];
  }

  Future<void> _startPhase() async {
    if (!_runnerReady) {
      showMessage(context, 'Complete Cursor agent setup first');
      return;
    }
    if (!_headlessReady) {
      showMessage(
        context,
        'Headless agent unavailable on this machine. '
        'Run `@orch-orchestrator resume ${widget.featureId}` in Cursor IDE, then Sync.',
      );
      return;
    }
    setState(() => _starting = true);
    try {
      await widget.api.runFeature(
        widget.featureId,
        phase: _phase > 0 ? _phase : 1,
      );
      if (mounted) {
        showMessage(context, 'Phase started');
        await _load(silent: true);
      }
    } catch (e) {
      if (mounted) showMessage(context, e.toString());
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  Future<void> _cancelRun() async {
    try {
      final res = await widget.api.cancelRun(widget.featureId);
      if (!mounted) return;
      final feature = res['feature'] as Map<String, dynamic>?;
      if (feature != null) {
        _applyDetail(feature, _runnerHealth);
      } else {
        await _load(silent: true);
      }
      if (mounted) showMessage(context, 'Run cancelled');
    } catch (e) {
      if (mounted) showMessage(context, e.toString());
    }
  }

  Future<void> _retry() async {
    setState(() => _starting = true);
    try {
      await widget.api.retryRun(widget.featureId);
      if (mounted) {
        showMessage(context, 'Retry queued');
        await _load(silent: true);
      }
    } catch (e) {
      if (mounted) showMessage(context, e.toString());
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  Future<void> _sendMessage(String prompt) async {
    setState(() {
      _optimisticMessages.add({
        'role': 'user',
        'type': 'command',
        'text': prompt,
        'timestamp': DateTime.now().toUtc().toIso8601String(),
      });
    });
    try {
      final res = await widget.api.sendCommand(
        widget.featureId,
        prompt: prompt,
        execute: true,
      );
      if (mounted) {
        final mode = res['mode'] as String?;
        final msg = mode == 'ide_only' || mode == 'feature_complete'
            ? (res['message'] as String? ??
                'Saved to requirement.md — run `@orch-orchestrator sync ${widget.featureId}` in Cursor IDE (headless agent unavailable).')
            : 'Message queued — previous run was replaced with your latest note';
        showMessage(context, msg);
        await _load(silent: true);
      }
    } catch (e) {
      if (mounted) {
        _optimisticMessages.removeLast();
        setState(() {});
        showMessage(context, e.toString());
      }
    }
  }

  Future<void> _approve(String decision, {String notes = ''}) async {
    if (decision == 'approved' && !_verdictPassed) {
      showMessage(
        context,
        'Cannot approve: judge verdict is $_judgeVerdict. Clarify and redo until PASS.',
      );
      return;
    }
    final approvePhase = _pendingPhase > 0 ? _pendingPhase : _phase;
    if (decision == 'approved' &&
        approvePhase >= 2 &&
        approvePhase <= 4 &&
        _artifactChecklist != null &&
        _artifactChecklist!['pass'] != true) {
      showMessage(
        context,
        'Cannot approve: ADF artifact validator failed. Fix blockers in the inspector.',
      );
      return;
    }
    try {
      final updated = await widget.api.approve(
        id: widget.featureId,
        phase: _pendingPhase > 0 ? _pendingPhase : _phase,
        decision: decision,
        notes: notes,
      );
      if (!mounted) return;
      showMessage(context, 'Recorded: $decision');
      setState(() => _detail = updated);
      await _load(silent: true);
    } catch (e) {
      if (!mounted) return;
      showMessage(context, e.toString());
    }
  }

  Future<void> _clarifyAndRedo(
    String notes, {
    required bool clientConfirmed,
  }) async {
    if (!clientConfirmed) {
      showMessage(
        context,
        'Check the confirmation box after reviewing the combined recommendation.',
      );
      return;
    }
    final phase = _pendingPhase > 0 ? _pendingPhase : _phase;
    final verdict = _judgeVerdict;
    try {
      await widget.api.approve(
        id: widget.featureId,
        phase: phase,
        decision: 'revise',
        notes: notes,
        clientConfirmed: true,
      );
      final prompt = _clarifyPrompt(
        phase,
        verdict,
        notes,
        clientConfirmed: clientConfirmed,
      );
      setState(() {
        _optimisticMessages.add({
          'role': 'user',
          'type': 'command',
          'text': prompt,
          'timestamp': DateTime.now().toUtc().toIso8601String(),
        });
      });
      await widget.api.sendCommand(
        widget.featureId,
        prompt: prompt,
        execute: true,
      );
      if (!mounted) return;
      showMessage(
        context,
        'Client confirmed — orchestrator applying combined recommendation',
      );
      await _load(silent: true);
    } catch (e) {
      if (!mounted) return;
      showMessage(context, e.toString());
    }
  }

  Future<void> _syncState() async {
    try {
      final r = await widget.api.syncState(widget.featureId);
      final f = r['feature'] as Map<String, dynamic>?;
      if (mounted && f != null) {
        setState(() => _detail = f);
        showMessage(context, 'State synced');
      }
    } catch (e) {
      if (mounted) showMessage(context, e.toString());
    }
  }

  Widget _statusBar(BuildContext context) {
    final status = context.orchStatus;
    final run = _detail?['run_status'] as Map<String, dynamic>?;
    final runSt = run?['status'] as String? ?? 'idle';
    final state = _detail?['state'] as Map<String, dynamic>? ?? {};
    final awaiting = _showApprovalGate;
    final error = run?['error'] as String?;

    Color bg;
    String title;
    String body;

    if (awaiting && _agentActive) {
      bg = status.runningBg;
      title = 'Applying your message';
      body =
          'Your note is saved in requirement.md. Agent is updating specs — send again to replace, or Cancel run.';
    } else if (_isRunning) {
      bg = status.runningBg;
      title = 'Running';
      body = 'Step: ${run?['step_id'] ?? _currentStepId ?? 'phase ${run?['phase']}'}';
    } else if (awaiting) {
      final v = (state['last_judge_verdict'] as String? ?? 'revise').toLowerCase();
      if (v == 'pass') {
        bg = status.awaitingBg;
        title = 'Ready to approve';
        body = 'Judge verdict: PASS — review and approve to continue';
      } else {
        bg = status.errorBg;
        title = 'Revision required';
        body = 'Verdict: ${v.toUpperCase()} — clarify requirement and redo specs';
      }
    } else if (runSt == 'needs_login' || runSt == 'error') {
      bg = status.errorBg;
      title = runSt == 'needs_login' ? 'Login required' : 'Error';
      body = error ?? 'Check runner setup';
    } else if (runSt == 'blocked') {
      bg = status.errorBg;
      title = 'Blocked';
      body = error ?? 'Max heal attempts reached';
    } else if (run?['resume_mode'] == 'cursor_ide' ||
        run?['headless_unavailable'] == true) {
      bg = status.awaitingBg;
      title = 'IDE mode';
      body = (run?['hint'] as String?) ??
          'Run `@orch-orchestrator resume ${widget.featureId}` in Cursor IDE, then Sync.';
    } else if (_phase == 0) {
      bg = status.runningBg;
      title = 'Ready';
      body = 'Start the pipeline when agent is ready';
    } else {
      return const SizedBox.shrink();
    }

    return Material(
      color: bg,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            if (_isRunning && !awaiting)
              Padding(
                padding: const EdgeInsets.only(right: 10),
                child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: status.running,
                  ),
                ),
              ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
                  Text(body, style: const TextStyle(fontSize: 13)),
                ],
              ),
            ),
            if (_isRunning)
              TextButton(
                onPressed: _cancelRun,
                child: const Text('Cancel run'),
              ),
            if (canRun && !_isRunning)
              FilledButton.tonalIcon(
                onPressed: _starting ? null : _startPhase,
                icon: _starting
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.play_arrow, size: 18),
                label: Text(_phase == 0 ? 'Start' : 'Run phase'),
              ),
            if (runSt == 'needs_login' || runSt == 'error')
              TextButton(onPressed: _retry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }

  bool get canRun {
    final state = _detail?['state'] as Map<String, dynamic>? ?? {};
    return _runnerReady &&
        !_isRunning &&
        state['awaiting_user'] != true &&
        state['status'] == 'active';
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _detail == null) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.featureId)),
        body: const Center(child: CircularProgressIndicator()),
      );
    }
    if (_detail == null) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.featureId)),
        body: const Center(child: Text('Failed to load')),
      );
    }

    final state = _detail!['state'] as Map<String, dynamic>;
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    final requirement = _detail!['requirement'] as String? ?? '';
    final verdict = _detail!['judge_verdict'] as String?;
    final traceCount = (_detail!['trace_count'] as num?)?.toInt() ?? 0;
    final awaiting = _showApprovalGate;
    final status = state['status'] as String? ?? 'active';
    final pipelineComplete = _pipeline?['pipeline_complete'] == true ||
        status == 'completed' ||
        (_detail?['summary'] as Map<String, dynamic>?)?['pipeline_complete'] ==
            true;
    final phase = pipelineComplete
        ? 9
        : ((_pipeline?['current_phase'] as num?)?.toInt() ?? _phase).clamp(0, 9);
    final summary = _pipeline?['summary'] as Map<String, dynamic>?;
    final conversation = _mergedConversation();
    final runStatus = _detail!['run_status'] as Map<String, dynamic>?;
    final sessionEnded = !_isRunning &&
        (runStatus?['status'] == 'idle' ||
            runStatus?['status'] == 'awaiting_approval');

    final phaseLabel = pipelineComplete
        ? 'Complete · ${state['track']}'
        : 'Phase $phase · ${state['track']} · $status';

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.featureId),
            Text(
              phaseLabel,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ),
        actions: [
          if (summary != null)
            Center(
              child: Padding(
                padding: const EdgeInsets.only(right: 8),
                child: Chip(
                  label: Text(
                    '${(summary['phases_complete'] as num?)?.toInt().clamp(0, 9) ?? 0}/9',
                  ),
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: OrchestrationShellBody(
        featureId: widget.featureId,
        isRunning: _showAgentActivityUi,
        onRefresh: _load,
        phaseSummary: phaseLabel,
        statusBar: _statusBar(context),
        chatContent: AgentConversationView(
          api: widget.api,
          featureId: widget.featureId,
          messages: conversation,
          scrollController: _chatScroll,
          isRunning: _showAgentActivityUi,
          liveTraceSince: runStatus?['started_at'] as String?,
          sessionEnded: sessionEnded,
          awaitingApproval: awaiting,
          needsRevision: awaiting && !_verdictPassed,
          canStartPipeline: canRun,
          onStartPipeline: _startPhase,
        ),
        approvalBar: _showApprovalGate
            ? ApprovalActionBar(
                phase: _pendingPhase > 0 ? _pendingPhase : phase,
                verdict: state['last_judge_verdict'] as String? ?? 'revise',
                artifactPass: _artifactPassed,
                combinedRecommendation:
                    _detail!['combined_recommendation'] as String?,
                onApprove: _approve,
                onClarifyAndRedo: _clarifyAndRedo,
                onReject: _approve,
              )
            : null,
        composer: ChatComposer(
          runnerReady: _runnerReady,
          enabled: _runnerReady,
          hintText: _agentActive
              ? 'Send a message (cancels current run)…'
              : 'Message the orchestrator…',
          initialPrompt: _promptForCurrentStep(),
          quickActions: _quickActions(),
          onSend: _sendMessage,
        ),
        pipelineRail: _phases.isNotEmpty
            ? PipelineRail(
                phases: _phases,
                currentPhase: phase > 0 ? phase : 1,
                selectedPhase: _viewPhase > 0 ? _viewPhase : (phase > 0 ? phase : 1),
                currentStepId: _currentStepId,
                onPhaseTap: (p) => setState(() => _viewPhase = p),
              )
            : null,
        inspector: FeatureInspector(
          api: widget.api,
          featureId: widget.featureId,
          requirement: requirement,
          gates: gates,
          verdict: verdict,
          combinedRecommendation:
              _detail!['combined_recommendation'] as String?,
          runnerHealth: _runnerHealth,
          phases: _phases,
          expandedPhase: _viewPhase > 0 ? _viewPhase : (phase > 0 ? phase : 1),
          currentStepId: _currentStepId,
          traceCount: traceCount,
          isRunning: _showAgentActivityUi,
          onVerifyRunner: () => _load(refreshRunner: true),
          onRetryRunner: (_runStatus == 'needs_login' || _runStatus == 'error')
              ? _retry
              : null,
          onStepCommand: (stepId, cmd) async => _sendMessage(cmd),
          onSyncState: _syncState,
          artifactChecklist: _artifactChecklist,
        ),
      ),
    );
  }
}
