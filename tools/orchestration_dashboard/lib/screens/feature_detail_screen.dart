import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../main.dart';
import '../services/api_client.dart';
import '../theme/orchestration_colors.dart';
import '../utils/auto_unstick.dart';
import '../utils/phase_selection.dart';
import '../utils/step_label.dart';
import '../widgets/agent_conversation_view.dart';
import '../widgets/revision_dialog.dart';
import '../widgets/approval_action_bar.dart';
import '../widgets/chat_composer.dart';
import '../widgets/live_preview_panel.dart';
import '../widgets/studio_shell.dart';
import '../theme/studio_theme.dart';
import '../utils/message_classifier.dart';
import '../utils/status_banner.dart';
import '../widgets/pipeline_rail.dart';

class FeatureDetailScreen extends StatefulWidget {
  const FeatureDetailScreen({
    super.key,
    required this.api,
    required this.featureId,
    this.justCreated = false,
  });

  final ApiClient api;
  final String featureId;
  final bool justCreated;

  @override
  State<FeatureDetailScreen> createState() => _FeatureDetailScreenState();
}

class _FeatureDetailScreenState extends State<FeatureDetailScreen> {
  Map<String, dynamic>? _detail;
  Map<String, dynamic>? _runnerHealth;
  bool _loading = true;
  bool _starting = false;
  int _viewPhase = 0;
  // True only after the user EXPLICITLY taps a phase in the rail (vs the default
  // highlight of the current phase) — gates the jump-to-artifacts behaviour.
  bool _phaseClicked = false;
  // True while an approve/revise request is outstanding — disables both the banner
  // and the bar so the two surfaces can't double-submit (D10).
  bool _approvalInFlight = false;
  Timer? _poll;
  bool _loadInFlight = false;
  int _pollTick = 0;
  bool _autoSynced = false;
  bool _autoUnstuck = false;
  // When we first observed the run as "stuck" (client-side), for the race guard.
  DateTime? _stuckSince;
  bool _autoAutopilotOnEnter = false;
  final Set<String> _shownMilestones = {};
  int _lastMilestonePhase = 0;
  final ScrollController _chatScroll = ScrollController();
  final List<Map<String, dynamic>> _optimisticMessages = [];
  Map<String, dynamic>? _artifactChecklist;
  bool? _chatLlmConfigured;
  bool? _chatPreferCursor;

  @override
  void initState() {
    super.initState();
    _load();
    _loadChatHealth();
    _schedulePoll();
    _maybeAutoAutopilot();
    if (widget.justCreated) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          showMessage(context, 'Feature created — crew is building artifacts…');
        }
      });
    }
  }

  // Adaptive polling: 2s while things change, backing off to 10s when idle.
  int _pollMs = 2000;

  void _schedulePoll() {
    _poll?.cancel();
    _poll = Timer(Duration(milliseconds: _pollMs), () async {
      _pollTick++;
      await _load(silent: true, refreshRunner: _pollTick % 15 == 0);
      final unchanged = widget.api.wasNotModified(widget.featureId);
      _pollMs = unchanged ? (_pollMs * 2).clamp(2000, 10000) : 2000;
      if (mounted) _schedulePoll();
    });
  }

  /// Snap back to fast polling after any user action.
  void _wakePolling() {
    _pollMs = 2000;
    if (mounted) _schedulePoll();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _chatScroll.dispose();
    super.dispose();
  }



  Future<void> _maybeAutoAutopilot() async {
    if (_autoAutopilotOnEnter) return;
    bool shouldRun;
    try {
      final d = await widget.api.getFeature(widget.featureId);
      final state = d['state'] as Map<String, dynamic>? ?? {};
      final phase = (state['current_phase'] as num?)?.toInt() ?? 0;
      final crew = await widget.api.getCrewLog(widget.featureId);
      shouldRun = phase <= 1 && crew.isEmpty && state['status'] == 'active';
    } catch (_) {
      // Couldn't read state — stay quiet; the status bar reflects reality on load.
      return;
    }
    if (!shouldRun) return;
    _autoAutopilotOnEnter = true;
    _autopilotStartedAt = DateTime.now().toUtc();
    _wakePolling();
    try {
      final summary = await widget.api.runAutopilot(widget.featureId);
      final blockers = blockersOf(summary);
      if (mounted && blockers.isNotEmpty) {
        // Don't let an auto-started run fail invisibly.
        showMessage(context, 'Autopilot blocked: ${blockers.first}');
      }
      if (mounted) await _load(silent: true);
    } catch (e) {
      if (mounted) showMessage(context, 'Auto-start failed: $e');
    }
  }

  Future<void> _loadChatHealth() async {
    try {
      final health = await widget.api.fetchHealth();
      if (mounted) {
        setState(() {
          _chatLlmConfigured = health['chat_llm_configured'] as bool?;
          _chatPreferCursor = health['chat_prefer_cursor'] as bool?;
        });
      }
    } catch (_) {}
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
      // Race guard (D16): anchor to how long WE'VE observed the stuck state, not a
      // server timestamp that ages independently. A phase that just set
      // awaiting_user must not be cancelled before the human sees its gate — only
      // unstick once the stuck state has PERSISTED across polls. Resetting
      // _stuckSince / _autoUnstuck when not stuck re-arms the valve per run (D15).
      if (stuck) {
        _stuckSince ??= DateTime.now();
      } else {
        _stuckSince = null;
        _autoUnstuck = false;
      }
      final stuckFor =
          _stuckSince == null ? null : DateTime.now().difference(_stuckSince!);
      if (!_autoUnstuck && shouldAutoUnstick(stuck: stuck, stuckFor: stuckFor)) {
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


  void _checkMilestones(Map<String, dynamic> d) {
    final state = d['state'] as Map<String, dynamic>? ?? {};
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    final phase = (state['current_phase'] as num?)?.toInt() ?? 0;
    if (phase > _lastMilestonePhase) {
      _lastMilestonePhase = phase;
      if (phase >= 2 && !_shownMilestones.contains('spec')) {
        _shownMilestones.add('spec');
        showMessage(context, 'Spec ready — review in the preview panel');
      }
      if (phase >= 6 && !_shownMilestones.contains('tests')) {
        _shownMilestones.add('tests');
        showMessage(context, 'Tests written — red phase locked in');
      }
    }
    if (gates['tests_red'] == true && !_shownMilestones.contains('tests_red')) {
      _shownMilestones.add('tests_red');
      showMessage(context, 'Tests written — ready for implementation');
    }
    if (gates['spec_ready'] == true && !_shownMilestones.contains('spec_gate')) {
      _shownMilestones.add('spec_gate');
      showMessage(context, 'Spec ready');
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
    // Prune optimistic bubbles once the durable server log represents them —
    // by command_id (a real reply has landed) OR by role+text (the message the
    // server persisted under its own id). This is housekeeping only; the merge
    // already de-dupes, so a momentary miss can never drop a visible bubble.
    if (_optimisticMessages.isNotEmpty && serverConv.isNotEmpty) {
      final serverKeys = serverConv
          .map((s) => '${s['role']}|${(s['text'] as String? ?? '').trim()}')
          .toSet();
      _optimisticMessages.removeWhere((om) {
        final cid = om['command_id'] as String?;
        if (cid != null) {
          final hasReply = serverConv.any(
            (s) =>
                s['role'] == 'assistant' &&
                s['command_id'] == cid &&
                s['llm_source'] != 'pending' &&
                s['llm_source'] != null,
          );
          if (hasReply) return true;
        }
        final key = '${om['role']}|${(om['text'] as String? ?? '').trim()}';
        return serverKeys.contains(key);
      });
    }
    final complete = (d['summary'] as Map<String, dynamic>?)?['pipeline_complete'] ==
            true ||
        (d['state'] as Map<String, dynamic>?)?['status'] == 'completed';
    setState(() {
      _detail = d;
      _runnerHealth = h;
      _loading = false;
      if (_viewPhase == 0 && phase > 0) _viewPhase = phase;
      // D6: release a manual phase selection once the build COMPLETES (the dot
      // shouldn't linger past the run). Mid-build look-back is intentionally kept.
      if (clearSelectionOnComplete(phaseClicked: _phaseClicked, complete: complete)) {
        _phaseClicked = false;
      }
    });
    _checkMilestones(d);
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

  /// Whether the server is auto-flowing approvals (no human pause). When on, the
  /// dashboard must NOT render an approval gate — the server never waits on it, so
  /// showing it was the "confirm/revise again and again" nag.
  bool get _autoApprove =>
      _detail?['auto_approve'] == true ||
      (_detail?['state'] as Map<String, dynamic>?)?['auto_approve'] == true;

  /// Approval gate — includes recovery when revise was recorded but awaiting_user was cleared.
  bool get _showApprovalGate {
    if (_autoApprove) return false; // auto-flow: never nag
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

  /// A human-friendly label for an internal step id (e.g. 'bmad-review-phase-3'
  /// → 'Reviewing with the AI panel'). Prefers the pipeline's own label, then a
  /// keyword map, then a prettified id — never the raw machine id.
  String _humanStepLabel(String? id, int? phase) {
    // Prefer the pipeline's own human label if present…
    if (id != null && id.trim().isNotEmpty) {
      for (final ph in _phases) {
        for (final s
            in ((ph['steps'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ??
                const [])) {
          if (s['id'] == id) {
            final label = (s['label'] ?? s['title'] ?? s['name']) as String?;
            if (label != null && label.trim().isNotEmpty) return label.trim();
          }
        }
      }
    }
    // …else the pure keyword mapping (test before plan — see stepLabelFromId).
    return stepLabelFromId(id, phase);
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

  /// The rendered conversation = the durable server log + any optimistic bubble
  /// not yet represented server-side. An optimistic message is hidden once the
  /// server has it (matched by command_id, or — for a just-typed message the
  /// server persisted under its own id — by role+text). This is a strict,
  /// de-duplicated SUPERSET: nothing the user sent or received ever vanishes,
  /// and nothing is shown twice.
  List<Map<String, dynamic>> _mergedConversation() {
    final server =
        (_detail?['conversation'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ??
            [];
    if (_optimisticMessages.isEmpty) return server;
    final serverIds = server
        .map((m) => m['command_id'])
        .whereType<String>()
        .toSet();
    final serverKeys = server
        .map((m) => '${m['role']}|${(m['text'] as String? ?? '').trim()}')
        .toSet();
    final extra = _optimisticMessages.where((m) {
      final cid = m['command_id'] as String?;
      if (cid != null && serverIds.contains(cid)) return false;
      final key = '${m['role']}|${(m['text'] as String? ?? '').trim()}';
      if (serverKeys.contains(key)) return false;
      return true;
    });
    return [...server, ...extra];
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



  Widget? _chatSetupBanner() {
    if (_chatLlmConfigured != false && _chatPreferCursor != true) return null;
    return MaterialBanner(
      backgroundColor: Theme.of(context).colorScheme.tertiaryContainer,
      content: Text(
        _chatPreferCursor == true
            ? 'Chat is using your Cursor CLI (cursor-agent). Replies may take 30–120 seconds; the panel refreshes automatically.'
            : 'Chat uses static fallbacks until you set GROQ_API_KEY on the API server, '
                'or start the API with scripts/orch/run_server_cursor_cli.sh for Cursor CLI chat.',
      ),
      actions: [
        TextButton(
          onPressed: () => setState(() {
            _chatLlmConfigured = null;
            _chatPreferCursor = null;
          }),
          child: const Text('Dismiss'),
        ),
      ],
    );
  }

  Future<void> _pollForChatReply() async {
    final pendingCmd = _optimisticMessages.lastWhere(
      (m) => m['role'] == 'user',
      orElse: () => <String, dynamic>{},
    );
    final commandId = pendingCmd['command_id'] as String?;
    for (var i = 0; i < 120; i++) {
      await Future.delayed(const Duration(seconds: 1));
      if (!mounted) return;
      await _load(silent: true);
      final conv =
          (_detail?['conversation'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ??
              [];
      Map<String, dynamic>? reply;
      for (final m in conv.reversed) {
        if (m['role'] != 'assistant') continue;
        final src = m['llm_source'] as String?;
        if (src == null || src == 'pending' || src == 'streaming') continue;
        if (commandId != null && m['command_id'] != commandId) continue;
        final text = (m['text'] as String? ?? '').trim();
        if (text.isEmpty || text.startsWith('Thinking')) continue;
        reply = m;
        break;
      }
      if (reply != null) {
        if (!mounted) return;
        // Do NOT clear optimistic messages wholesale — that was the flash-then-
        // gone bug. _applyDetail() (run by _load above) has already pruned the
        // entries the server now holds; _mergedConversation() de-dupes the rest.
        showMessage(
          context,
          reply['llm_source'] == 'cursor_agent'
              ? 'Cursor CLI reply ready.'
              : 'Reply ready.',
        );
        return;
      }
    }
    if (mounted) {
      showMessage(
        context,
        'Cursor CLI is still working — wait a bit longer or check API logs.',
      );
    }
  }

  Future<void> _sendMessage(String prompt) async {
    final ts = DateTime.now().toUtc().toIso8601String();
    setState(() {
      _optimisticMessages.add({
        'role': 'user',
        'type': 'command',
        'text': prompt,
        'timestamp': ts,
      });
    });
    _wakePolling();

    final p = prompt.trim();

    // `/compact` is a direct command: fold the app's accumulated context (the
    // same /compact discipline Claude Code uses) and surface the result inline.
    if (isCompactCommand(p)) {
      try {
        final res = await widget.api.compact(widget.featureId);
        if (mounted) {
          final did = res['did_compact'] == true;
          showMessage(
            context,
            did
                ? 'Compacted context (${res['tokens']} → ${res['tokens_after']} tokens).'
                : 'Context already within budget — nothing to compact.',
          );
          await _load(silent: true);
        }
      } catch (_) {
        if (mounted) showMessage(context, 'Could not compact context right now.');
      }
      return;
    }

    // One-box iteration: once the app is built, a plain (non-question, non-@command)
    // message edits the app and re-renders the live preview — the Lovable loop.
    if (_phase >= 7 && !p.startsWith('@') && !looksLikeQuestion(p)) {
      try {
        await widget.api.editApp(widget.featureId, prompt);
        if (mounted) {
          showMessage(
            context,
            'Applying your change — the preview refreshes when it\'s ready.',
          );
          await _load(silent: true);
        }
        return;
      } on ApiException catch (e) {
        // 409 = no built app yet → treat the message as chat (fall through).
        // Any other status is a real failure: surface it instead of silently
        // turning the user's edit into a chat message.
        if (e.statusCode != 409) {
          if (mounted) {
            _dropOptimisticUser();
            showMessage(context, 'Could not apply your change: ${e.message}');
          }
          return;
        }
      } catch (e) {
        // Network/timeout — also a real failure, not a reason to fall through.
        if (mounted) {
          _dropOptimisticUser();
          showMessage(context, 'Could not apply your change: $e');
        }
        return;
      }
    }
    try {
      final res = await widget.api.sendCommand(
        widget.featureId,
        prompt: prompt,
        execute: true,
      );
      if (mounted) {
        final cmd = res['command'] as Map<String, dynamic>?;
        final commandId = cmd?['id'] as String?;
        final assistant = res['assistant_message'] as String?;
        if (assistant != null && assistant.trim().isNotEmpty) {
          setState(() {
            if (commandId != null) {
              final lastUser =
                  _optimisticMessages.lastIndexWhere((m) => m['role'] == 'user');
              if (lastUser >= 0) {
                _optimisticMessages[lastUser]['command_id'] = commandId;
              }
            }
            _optimisticMessages.add({
              'role': 'assistant',
              'type': 'orchestrator',
              'text': assistant.trim(),
              'timestamp': DateTime.now().toUtc().toIso8601String(),
              'llm_source': res['llm_source'],
              'command_id': commandId,
            });
          });
        }
        final mode = res['mode'] as String?;
        final orch = res['orchestrator_command'] as String?;
        String msg;
        if (mode == 'llm_answer') {
          msg = 'Orchestrator replied (no agent run needed).';
        } else if (mode == 'llm_ide' || mode == 'ide_only') {
          msg = orch != null
              ? 'LLM processed your message. Run in Cursor: $orch'
              : (res['message'] as String? ??
                  'Saved — run `@orch-orchestrator sync ${widget.featureId}` in Cursor IDE.');
        } else if (mode == 'feature_complete') {
          msg = res['message'] as String? ?? 'Notes saved (feature completed).';
        } else if (mode == 'chat_pending') {
          msg = 'Cursor CLI is thinking — chat will update automatically.';
        } else {
          msg = 'Orchestrator is executing your request via the agent.';
        }
        showMessage(context, msg);
        if (mode == 'chat_pending') {
          await _pollForChatReply();
        } else {
          await _load(silent: true);
        }
      }
    } catch (e) {
      if (mounted) {
        _dropOptimisticUser();
        showMessage(context, e.toString());
      }
    }
  }

  /// Remove the optimistic user bubble added before a send that then failed, so a
  /// failed action never leaves a phantom message in the transcript.
  void _dropOptimisticUser() {
    setState(() {
      if (_optimisticMessages.isNotEmpty &&
          _optimisticMessages.last['role'] == 'user') {
        _optimisticMessages.removeLast();
      }
    });
  }


  // Review dialog: list the spec/plan/tests and built code (tap to read), plus
  // the live build log — so the user can see what was created and what the
  // agent is doing before approving.
  Future<void> _openReviewDialog() async {
    Map<String, dynamic> artifacts = {};
    List<Map<String, dynamic>> log = const [];
    try {
      artifacts = await widget.api.listArtifacts(widget.featureId);
      log = await widget.api.getRunLog(widget.featureId, limit: 40);
    } catch (e) {
      if (mounted) showMessage(context, 'Could not load artifacts: $e');
    }
    if (!mounted) return;
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Review artifacts & build log'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (artifacts.isEmpty)
                  const Text('No artifacts yet — the crew is still working.'),
                for (final group in artifacts.entries) ...[
                  Padding(
                    padding: const EdgeInsets.only(top: 8, bottom: 2),
                    child: Text(
                      group.key == 'code'
                          ? 'Built code'
                          : 'Spec · plan · tasks · tests',
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    ),
                  ),
                  for (final f in (group.value as List).cast<Map<String, dynamic>>())
                    ListTile(
                      dense: true,
                      leading: const Icon(Icons.description_outlined, size: 18),
                      title: Text(f['name'] as String? ?? '?'),
                      subtitle: Text('${f['bytes'] ?? 0} bytes'),
                      onTap: () => _viewArtifact(
                          f['path'] as String? ?? '', f['name'] as String? ?? ''),
                    ),
                ],
                if (log.isNotEmpty) ...[
                  const Divider(height: 20),
                  const Text('Build log (live)',
                      style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(8),
                    color: Colors.black.withValues(alpha: 0.05),
                    child: SelectableText(
                      log
                          .map((e) => (e['message'] ?? '').toString())
                          .where((m) => m.isNotEmpty)
                          .join('\n'),
                      style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
        ],
      ),
    );
  }

  Future<void> _viewArtifact(String path, String name) async {
    String content;
    try {
      content = await widget.api.getArtifact(widget.featureId, path);
    } catch (e) {
      content = 'Could not load: $e';
    }
    if (!mounted) return;
    // Spec/plan/tasks/test docs are markdown — render them formatted, not as a
    // monospace dump. Code/other files keep the monospace view.
    final isMarkdown = name.toLowerCase().endsWith('.md');
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(name),
        content: SizedBox(
          width: 660,
          height: 460,
          child: SingleChildScrollView(
            child: isMarkdown
                ? MarkdownBody(data: content, selectable: true)
                : SelectableText(
                    content,
                    style:
                        const TextStyle(fontFamily: 'monospace', fontSize: 12),
                  ),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
        ],
      ),
    );
  }

  Future<void> _approve(String decision, {String notes = ''}) async {
    if (_approvalInFlight) return; // D10: no concurrent submit
    final approvePhase = _pendingPhase > 0 ? _pendingPhase : _phase;
    // The crew's spec phases (1-6) are deterministic — there is no judge verdict
    // — so the human's review of the spec/plan/tests IS the approval. Detect
    // "no real PASS verdict" from the RAW state: the _judgeVerdict getter
    // defaults to 'revise', which would otherwise mask the absent-verdict case
    // and wrongly block the spec-gate approval. Other phases still require PASS.
    final rawVerdict =
        (_detail?['state'] as Map<String, dynamic>?)?['last_judge_verdict']
            as String?;
    final isSpecGate = approvePhase <= 6 &&
        (rawVerdict == null ||
            rawVerdict.trim().isEmpty ||
            rawVerdict.toLowerCase() != 'pass');
    if (decision == 'approved' && !_verdictPassed && !isSpecGate) {
      showMessage(
        context,
        'Cannot approve: judge verdict is $_judgeVerdict. Clarify and redo until PASS.',
      );
      return;
    }
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
    setState(() => _approvalInFlight = true);
    try {
      final updated = await widget.api.approve(
        id: widget.featureId,
        phase: approvePhase,
        decision: decision,
        notes: notes,
        judgeWaiver: isSpecGate,
      );
      if (!mounted) return;
      showMessage(context, 'Recorded: $decision');
      setState(() => _detail = updated);
      await _load(silent: true);
    } catch (e) {
      if (!mounted) return;
      showMessage(context, e.toString());
    } finally {
      if (mounted) setState(() => _approvalInFlight = false);
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
    if (_approvalInFlight) return; // D10: no concurrent submit
    final phase = _pendingPhase > 0 ? _pendingPhase : _phase;
    final verdict = _judgeVerdict;
    setState(() => _approvalInFlight = true);
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
    } finally {
      if (mounted) setState(() => _approvalInFlight = false);
    }
  }

  /// D5: the in-panel "Request changes" captures WHAT to change (and never blind-
  /// submits / bypasses the confirm gate). Prompt for a note, then run the same
  /// confirmed-revise path the detailed bar uses. (Dialog extracted + tested.)
  Future<void> _promptRevise() async {
    final note = await promptRevisionNote(context);
    if (note == null) return; // cancelled or empty
    await _clarifyAndRedo(note, clientConfirmed: true);
  }

  bool _autopilotRunning = false;
  DateTime? _autopilotStartedAt;

  Future<void> _runAutopilot() async {
    if (_autopilotRunning) return;
    setState(() {
      _autopilotRunning = true;
      _autopilotStartedAt = DateTime.now().toUtc();
    });
    _wakePolling();
    try {
      final summary = await widget.api.runAutopilot(widget.featureId);
      if (!mounted) return;
      // A blocked run is NOT a success — autopilotOutcomeMessage names the blocker.
      showMessage(context, autopilotOutcomeMessage(summary));
      await _load(silent: true);
    } catch (e) {
      if (mounted) showMessage(context, 'Autopilot failed: $e');
    } finally {
      if (mounted) setState(() => _autopilotRunning = false);
    }
  }

  /// Seconds since an ISO-8601 (UTC) timestamp, or null if unparseable.
  int? _elapsedSeconds(String? iso) {
    if (iso == null || iso.isEmpty) return null;
    final t = DateTime.tryParse(iso);
    if (t == null) return null;
    final secs = DateTime.now().toUtc().difference(t.toUtc()).inSeconds;
    return secs < 0 ? 0 : secs;
  }

  Widget _statusBar(BuildContext context) {
    final status = context.orchStatus;
    final run = _detail?['run_status'] as Map<String, dynamic>?;
    final runSt = run?['status'] as String? ?? 'idle';
    final state = _detail?['state'] as Map<String, dynamic>? ?? {};
    final awaiting = _showApprovalGate;
    final error = run?['error'] as String?;
    final done = _pipeline?['pipeline_complete'] == true ||
        (state['status'] as String?) == 'completed' ||
        (_detail?['summary'] as Map<String, dynamic>?)?['pipeline_complete'] ==
            true;
    // A run that has been going >45s gets a "still building" treatment so the
    // user isn't staring at a dead spinner — with Cancel + Reset & retry.
    final elapsed = _elapsedSeconds(run?['started_at'] as String?);
    final longRun = _isRunning && !awaiting && elapsed != null && elapsed >= 45;

    // Delegate the decision to the pure, unit-tested statusBanner(): it
    // guarantees a blocked/failed run never reads as success and that there is
    // never a blank bar. The widget only maps the semantic kind to a colour.
    final banner = statusBanner(
      runSt: runSt,
      awaiting: awaiting,
      agentActive: _agentActive,
      isRunning: _isRunning,
      done: done,
      longRun: longRun,
      phase: _phase,
      elapsed: elapsed,
      error: error,
      judgeVerdict: state['last_judge_verdict'] as String? ?? 'revise',
      stepLabel: _humanStepLabel(
          (run?['step_id'] as String?) ?? _currentStepId,
          (run?['phase'] as num?)?.toInt()),
      ideMode: run?['resume_mode'] == 'cursor_ide' ||
          run?['headless_unavailable'] == true,
      ideHint: run?['hint'] as String?,
      featureId: widget.featureId,
    );
    final bg = switch (banner.kind) {
      BannerKind.running => status.runningBg,
      BannerKind.awaiting => status.awaitingBg,
      BannerKind.error => status.errorBg,
      BannerKind.success => status.successBg,
    };
    final title = banner.title;
    final body = banner.body;

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
            if (runSt == 'needs_login' ||
                runSt == 'error' ||
                runSt == 'blocked' ||
                longRun)
              TextButton(
                onPressed: _retry,
                child: Text(
                  runSt == 'blocked' || longRun ? 'Reset & retry' : 'Retry',
                ),
              ),
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
        leading: BackButton(onPressed: () => Navigator.of(context).pop()),
        title: Text(phaseLabel),
      ),
      body: StudioShell(
        featureId: widget.featureId,
        header: Container(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: StudioTheme.panelBorder)),
          ),
          child: Row(
            children: [
              Icon(Icons.auto_awesome, color: StudioTheme.accent, size: 22),
              const SizedBox(width: 10),
              Text(
                'ADF Studio',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
              ),
              const SizedBox(width: 8),
              Text(
                widget.featureId,
                style: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
              ),
              const Spacer(),
              if (summary != null)
                Chip(
                  label: Text(
                    '${(summary['phases_complete'] as num?)?.toInt().clamp(0, 9) ?? 0}/9 phases',
                  ),
                  visualDensity: VisualDensity.compact,
                ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 6),
                child: FilledButton.tonalIcon(
                  onPressed: _autopilotRunning ? null : _runAutopilot,
                  icon: _autopilotRunning
                      ? const SizedBox(
                          height: 14,
                          width: 14,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.rocket_launch, size: 16),
                  label: Text(_autopilotRunning ? 'Autopilot…' : 'Autopilot'),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.fact_check_outlined),
                tooltip: 'Review artifacts & build log',
                onPressed: _openReviewDialog,
              ),
              IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
            ],
          ),
        ),
        statusBar: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_chatSetupBanner() case final banner?) banner,
            _statusBar(context),
          ],
        ),
        chatContent: AgentConversationView(
          api: widget.api,
          featureId: widget.featureId,
          messages: conversation,
          scrollController: _chatScroll,
          // Autopilot (the zero-token crew) also streams live trace spans now,
          // so treat it as a running session for the live-trace panel.
          isRunning: _showAgentActivityUi || _autopilotRunning,
          liveTraceSince: runStatus?['started_at'] as String? ??
              _autopilotStartedAt?.toIso8601String(),
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
          enabled: true,
          hintText: _agentActive
              ? 'Send a message (cancels current run)…'
              : 'Ask ADF to build, review, or sync this feature…',
          initialPrompt: _promptForCurrentStep(),
          quickActions: _quickActions(),
          onSend: _sendMessage,
        ),
        pipelineRail: _phases.isNotEmpty
            ? PipelineRail(
                phases: _phases,
                currentPhase: phase > 0 ? phase : 1,
                selectedPhase: railHighlight(
                    phaseClicked: _phaseClicked,
                    viewPhase: _viewPhase,
                    livePhase: phase),
                currentStepId: _currentStepId,
                onPhaseTap: (p) => setState(() {
                  // Re-tapping the selected phase deselects it (returns to
                  // auto-follow + clears the dot); tapping another selects it (D6).
                  if (_phaseClicked && _viewPhase == p) {
                    _phaseClicked = false;
                  } else {
                    _viewPhase = p;
                    _phaseClicked = true;
                  }
                }),
              )
            : null,
        preview: LivePreviewPanel(
          api: widget.api,
          featureId: widget.featureId,
          phase: phase,
          status: status,
          requirement: requirement,
          currentStep: _currentStepId,
          gates: gates,
          combinedRecommendation:
              _detail!['combined_recommendation'] as String?,
          awaitingApproval: awaiting,
          building: _autopilotRunning || _isRunning,
          // Clicking a phase in the rail focuses that stage's artifacts (only on
          // an explicit tap, not the rail's default current-phase highlight).
          selectedPhase: artifactSelection(
              phaseClicked: _phaseClicked, viewPhase: _viewPhase),
          // Sticky review gate in the panel. Approve is one-click (safe); Request
          // changes prompts for what to change (D5), and both are disabled while a
          // request is in flight (D10).
          onApprove:
              awaiting && !_approvalInFlight ? () => _approve('approved') : null,
          onRevise: awaiting && !_approvalInFlight ? _promptRevise : null,
        ),
      ),
    );
  }
}
