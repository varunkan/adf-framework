import 'dart:async';
import 'dart:io';

import 'agent_crew.dart' show AgentEscalation, agentBudgetFromEnv;
import 'artifact_validator.dart';
import 'deterministic_artifacts.dart';
import 'feature_store.dart';
import 'learning_store.dart';

/// The built-in ADF harness: plan -> generate -> validate -> heal -> advance.
///
/// Runs phases 1-6 fully automatically at zero token cost using the
/// deterministic artifact engine, machine-validating every phase before its
/// gate is set. Implementation phases (7+) are intentionally left to a code
/// agent + human review — autopilot never ships unverified code.
class Autopilot {
  Autopilot(
    this.store,
    this.engine,
    this.validator,
    this.learnings, {
    this.maxHealAttempts = 2,
    this.escalation,
    Duration? agentBudget,
    Map<String, String>? env,
  }) : agentBudget =
            agentBudget ?? agentBudgetFromEnv(env ?? Platform.environment);

  final FeatureStore store;
  final DeterministicArtifactEngine engine;
  final ArtifactValidator validator;
  final LearningStore learnings;
  final int maxHealAttempts;

  /// Optional router-backed escalation hook for budget breaches; without it
  /// a timed-out phase blocks immediately.
  final AgentEscalation? escalation;

  /// Per-task wall-clock budget (`ORCH_AGENT_TIMEOUT_SEC`, default 30s).
  /// Deterministic-brain generation finishes in milliseconds and never
  /// comes close to the budget.
  final Duration agentBudget;

  /// Phases whose artifacts are machine-validated by the shell validator.
  static const validatedPhases = {2, 3, 4};

  static const int defaultMaxPhase = 6;

  Future<Map<String, dynamic>> run(
    String id, {
    int maxPhase = defaultMaxPhase,
  }) async {
    final started = DateTime.now();
    final completed = <int>[];
    final log = <Map<String, dynamic>>[];
    String? stopReason;
    List<String> blockers = const [];

    while (true) {
      final state = store.readState(id);
      final gates = state['gates'] as Map<String, dynamic>? ?? {};
      final phase = store.inferWorkPhase(gates);

      if (phase > maxPhase) {
        stopReason = phase >= 7
            ? 'implementation_handoff'
            : 'max_phase_reached';
        break;
      }

      final outcome = await _runPhase(id, phase);
      log.add(outcome);
      if (outcome['pass'] == true) {
        completed.add(phase);
        _advance(id, phase);
        learnings.record(featureId: id, phase: phase, kind: 'success');
      } else {
        blockers = (outcome['blockers'] as List? ?? [])
            .map((b) => b.toString())
            .toList();
        learnings.record(
          featureId: id,
          phase: phase,
          kind: 'failure',
          blockers: blockers,
        );
        stopReason = 'blocked';
        break;
      }
    }

    final summary = {
      'feature_id': id,
      'phases_completed': completed,
      'stop_reason': stopReason,
      'blockers': blockers,
      'token_cost': engine.brain.billsTokens ? 'metered' : 'zero',
      'brain': engine.brain.name,
      'duration_ms': DateTime.now().difference(started).inMilliseconds,
      'log': log,
      'learnings': learnings.stats(),
    };
    _announce(id, summary);
    return summary;
  }

  Future<Map<String, dynamic>> _runPhase(String id, int phase) async {
    var attempt = 0;
    String? escalatedTo;
    while (true) {
      List<String> written;
      final sw = Stopwatch()..start();
      try {
        written = await engine.generatePhase(id, phase).timeout(agentBudget);
      } on TimeoutException {
        // Budget breached: escalate ONCE to the next-higher tier, then
        // block if the retry also breaches (or no hook is wired).
        final hook = escalation;
        if (hook == null || escalatedTo != null) {
          return _timedOutOutcome(
            phase,
            elapsedMs: sw.elapsedMilliseconds,
            escalatedTo: escalatedTo,
            attempts: attempt + 1,
          );
        }
        escalatedTo = hook.tier;
        try {
          written = await hook.run(id, phase).timeout(agentBudget);
        } on TimeoutException {
          return _timedOutOutcome(
            phase,
            elapsedMs: sw.elapsedMilliseconds,
            escalatedTo: escalatedTo,
            attempts: attempt + 1,
          );
        }
      }
      Map<String, dynamic> validation = {'pass': true, 'blockers': []};
      if (validatedPhases.contains(phase)) {
        validation = await validator.check(id, phase: phase);
      }
      if (validation['pass'] == true) {
        return {
          'phase': phase,
          'pass': true,
          'artifacts': written,
          'attempts': attempt + 1,
          if (escalatedTo != null) 'status': 'escalated',
          if (escalatedTo != null) 'escalated_to': escalatedTo,
        };
      }
      if (attempt >= maxHealAttempts) {
        return {
          'phase': phase,
          'pass': false,
          'blockers': validation['blockers'],
          'attempts': attempt + 1,
          if (escalatedTo != null) 'status': 'escalated',
          if (escalatedTo != null) 'escalated_to': escalatedTo,
        };
      }
      attempt++;
      _heal(id, validation['blockers'] as List? ?? []);
      learnings.record(
        featureId: id,
        phase: phase,
        kind: 'heal',
        blockers:
            (validation['blockers'] as List? ?? []).map((b) => '$b').toList(),
        fix: 'regenerated artifacts (attempt ${attempt + 1})',
      );
    }
  }

  /// Terminal outcome for a phase whose generation breached [agentBudget]
  /// twice (or once with no escalation hook). Carries `status`,
  /// `elapsed_ms`, and `escalated_to` so run() log entries surface it.
  Map<String, dynamic> _timedOutOutcome(
    int phase, {
    required int elapsedMs,
    required String? escalatedTo,
    required int attempts,
  }) {
    return {
      'phase': phase,
      'pass': false,
      'status': 'blocked',
      'elapsed_ms': elapsedMs,
      'budget_ms': agentBudget.inMilliseconds,
      'escalated_to': escalatedTo,
      'attempts': attempts,
      'blockers': [
        'phase $phase generation timed out after '
            '${agentBudget.inMilliseconds}ms budget (ORCH_AGENT_TIMEOUT_SEC; '
            'escalated_to: ${escalatedTo ?? 'none'})',
      ],
    };
  }

  /// Deterministic self-heal: recreate any missing directories the
  /// validator complained about, then regenerate.
  void _heal(String id, List<dynamic> blockers) {
    for (final b in blockers) {
      final text = b.toString();
      final m = RegExp(r'missing (?:required file|directory):\s*(\S+)')
          .firstMatch(text);
      if (m != null) {
        final p = m.group(1)!;
        final dir = p.endsWith('.md') || p.endsWith('.yaml')
            ? File(p).parent
            : Directory(p);
        dir.createSync(recursive: true);
      }
    }
  }

  void _advance(String id, int phase) {
    final state = store.readState(id);
    store.setGateForPhase(state, phase, true);
    final builders =
        Map<String, dynamic>.from(state['completed_builders'] as Map? ?? {});
    builders['$phase'] = ['adf-autopilot'];
    state['completed_builders'] = builders;
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    state['current_phase'] = store.inferWorkPhase(gates);
    state['status'] = 'active';
    // G1: same track-aware hold as AgentCrew._advance — M/L/XL hold for the user.
    if (FeatureStore.autoApprove(state)) {
      state['awaiting_user'] = false;
      state['pending_approval_phase'] = null;
    } else {
      state['awaiting_user'] = true;
      state['pending_approval_phase'] = phase;
    }
    store.writeState(id, state);
  }

  void _announce(String id, Map<String, dynamic> summary) {
    final phases = (summary['phases_completed'] as List).join(', ');
    final reason = summary['stop_reason'];
    final text = StringBuffer('**Autopilot run finished.**\n\n');
    if (phases.isNotEmpty) {
      text.writeln('- Phases completed: $phases');
    }
    text
      ..writeln('- Brain: ${summary['brain']} '
          '(token cost: ${summary['token_cost']})')
      ..writeln('- Duration: ${summary['duration_ms']}ms');
    switch (reason) {
      case 'implementation_handoff':
        text.writeln(
            '- Next: phase 7 implementation — run the code agent or approve '
            'in the pipeline. Autopilot never ships unverified code.');
      case 'blocked':
        text.writeln('- Blocked: ${(summary['blockers'] as List).join('; ')}');
      default:
        text.writeln('- Pipeline is up to date.');
    }
    final cmd = store.appendCommand(id, prompt: 'autopilot', execute: false);
    store.updateCommandMeta(
      id,
      cmd['id'] as String,
      assistantReply: text.toString().trim(),
      llmSource: 'autopilot',
    );
    store.markCommandExecuted(id, cmd['id'] as String);
  }
}
