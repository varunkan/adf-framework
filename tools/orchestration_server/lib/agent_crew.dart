import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'artifact_validator.dart';
import 'deterministic_artifacts.dart';
import 'feature_store.dart';
import 'integrity_chain.dart';
import 'learning_store.dart';
import 'trace_writer.dart';

/// Re-runs a timed-out task at a higher router tier, returning artifact paths.
typedef AgentEscalationRun = Future<List<String>> Function(
    String featureId, int phase);

/// Minimal local contract for the model router (model_router.dart is owned
/// elsewhere): when a task breaches its wall-clock budget it escalates ONCE
/// to the next-higher tier (local -> fast -> balanced -> deep). Callers wire
/// a router-backed hook in; the crew never imports the router directly, so
/// the dependency stays loose.
class AgentEscalation {
  AgentEscalation({required this.tier, required this.run});

  /// Tier name the retry executes on (e.g. 'fast') — recorded as
  /// `escalated_to` in logs.
  final String tier;

  /// Re-runs the same task on [tier].
  final AgentEscalationRun run;
}

/// Resolves the per-task wall-clock budget from `ORCH_AGENT_TIMEOUT_SEC`
/// (seconds, default 30). Invalid or non-positive values fall back to the
/// default so a bad env var can never disable the budget.
Duration agentBudgetFromEnv(Map<String, String> env) {
  final raw = int.tryParse(env['ORCH_AGENT_TIMEOUT_SEC']?.trim() ?? '');
  return Duration(seconds: raw == null || raw <= 0 ? 30 : raw);
}

/// A specialized subagent in the crew. Agents declare dependencies; the
/// crew runs every agent whose needs are met concurrently (wave execution).
class CrewAgent {
  CrewAgent({
    required this.name,
    required this.role,
    required this.phase,
    this.needs = const [],
    required this.run,
  });

  final String name;
  final String role;
  final int phase;
  final List<String> needs;
  final Future<List<String>> Function() run;
}

/// Multi-agent harness: product analyst, spec writer, architect, task
/// planner, test architect, and test author work together in parallel
/// dependency waves — deterministic, zero tokens, milliseconds.
class AgentCrew {
  AgentCrew(
    this.store,
    this.engine,
    this.validator,
    this.learnings, {
    IntegrityChain? integrity,
    this.escalation,
    Duration? agentBudget,
    Map<String, String>? env,
    this.traces,
  })  : integrity = integrity ?? IntegrityChain(store),
        agentBudget =
            agentBudget ?? agentBudgetFromEnv(env ?? Platform.environment);

  /// Optional live-trace sink. When wired, the crew narrates itself span-by-span
  /// (wave start + each subagent done) so the dashboard's live-trace stream has
  /// something to show during the run instead of ~14s of dead-air.
  final TraceWriter? traces;

  final FeatureStore store;
  final DeterministicArtifactEngine engine;
  final ArtifactValidator validator;
  final LearningStore learnings;
  final IntegrityChain integrity;

  /// Optional router-backed escalation hook; without it a budget breach
  /// blocks the agent immediately (there is no higher tier to try).
  final AgentEscalation? escalation;

  /// Per-subagent wall-clock budget (`ORCH_AGENT_TIMEOUT_SEC`, default 30s).
  /// Deterministic-brain tasks finish in milliseconds and never come close.
  final Duration agentBudget;

  List<CrewAgent> buildCrew(String id) => [
        CrewAgent(
          name: 'product-analyst',
          role: 'Problem statement & success criteria',
          phase: 1,
          run: () => engine.generatePhase(id, 1),
        ),
        CrewAgent(
          name: 'spec-writer',
          role: 'EARS requirements & acceptance criteria',
          phase: 2,
          needs: ['product-analyst'],
          run: () => engine.generatePhase(id, 2),
        ),
        CrewAgent(
          name: 'architect',
          role: 'Implementation plan & risk register',
          phase: 3,
          needs: ['spec-writer'],
          run: () => engine.generatePhase(id, 3),
        ),
        CrewAgent(
          name: 'task-planner',
          role: 'Micro-task DAG (≤90s tasks)',
          phase: 4,
          needs: ['spec-writer'],
          run: () => engine.generatePhase(id, 4),
        ),
        CrewAgent(
          name: 'test-architect',
          role: 'Test strategy & exit criteria',
          phase: 5,
          needs: ['spec-writer'],
          run: () => engine.generatePhase(id, 5),
        ),
        CrewAgent(
          name: 'test-author',
          role: 'Test cases & traceability matrix',
          phase: 6,
          needs: ['task-planner', 'test-architect'],
          run: () => engine.generatePhase(id, 6),
        ),
      ];

  /// Plan the crew's parallel execution waves with EXPLICIT validation (Kahn's
  /// algorithm): each wave is the set of agents whose dependencies are all met by
  /// earlier waves, so a wave runs fully in parallel. Throws [ArgumentError] naming
  /// the offending agents on a self-dependency, an unknown dependency, or a cycle —
  /// instead of the old implicit "empty wave" StateError mid-run. Pure + static, so
  /// the scheduling is unit-testable. (Adopted from oh-my-pi's swarm/dag.ts;
  /// see docs/ADF_VS_OH_MY_PI.md §5.10.)
  static List<List<String>> buildExecutionWaves(List<CrewAgent> agents) {
    final names = agents.map((a) => a.name).toSet();
    final deps = <String, Set<String>>{};
    for (final a in agents) {
      if (a.needs.contains(a.name)) {
        throw ArgumentError('crew agent "${a.name}" depends on itself');
      }
      for (final n in a.needs) {
        if (!names.contains(n)) {
          throw ArgumentError('crew agent "${a.name}" needs unknown agent "$n"');
        }
      }
      deps[a.name] = a.needs.toSet();
    }
    final done = <String>{};
    final waves = <List<String>>[];
    final remaining = agents.map((a) => a.name).toList();
    while (remaining.isNotEmpty) {
      final wave =
          remaining.where((n) => deps[n]!.every(done.contains)).toList();
      if (wave.isEmpty) {
        throw ArgumentError(
            'crew dependency cycle among: ${remaining.join(', ')}');
      }
      waves.add(wave);
      done.addAll(wave);
      remaining.removeWhere(wave.contains);
    }
    return waves;
  }

  Future<Map<String, dynamic>> run(String id) async {
    final started = DateTime.now();
    final crew = buildCrew(id);
    final agentResults = <Map<String, dynamic>>[];
    final waves = <List<String>>[];

    final crewBlockers = <String>[];
    final byName = {for (final a in crew) a.name: a};
    // Plan all execution waves once (validated: self-dep / unknown-dep / cycle all
    // throw a descriptive error here, before any agent runs), then execute them in
    // order — stopping after a wave that produced a blocker.
    final plan = buildExecutionWaves(crew);
    for (final waveNames in plan) {
      if (crewBlockers.isNotEmpty) break;
      final wave = [for (final n in waveNames) byName[n]!];
      waves.add(waveNames);
      traces?.append(
        featureId: id,
        name: 'crew.wave_start',
        event: 'crew',
        message: 'Wave ${waves.length}: ${waveNames.join(', ')}',
      );
      // All agents in a wave run concurrently, each under the budget.
      final results =
          await Future.wait(wave.map((agent) => _runWithBudget(id, agent)));
      for (final r in results) {
        agentResults.add(r);
        _logAgent(id, r);
        traces?.append(
          featureId: id,
          name: 'crew.agent_done',
          event: 'crew',
          phase: r['phase'] as int?,
          message: '✓ ${r['agent']} — ${r['role']}',
        );
        if (r['status'] == 'blocked') {
          final blocker = '${r['agent']} (phase ${r['phase']}): timed out '
              'after ${agentBudget.inMilliseconds}ms budget '
              '(escalated_to: ${r['escalated_to'] ?? 'none'})';
          crewBlockers.add(blocker);
          learnings.record(
            featureId: id,
            phase: r['phase'] as int,
            kind: 'failure',
            blockers: [blocker],
          );
        }
      }
    }

    // Machine-validate, then advance gates exactly like a human-led run.
    // A timed-out crew never advances gates — its artifacts are incomplete.
    final completed = <int>[];
    var blockers = List<String>.from(crewBlockers);
    for (final phase in [1, 2, 3, 4, 5, 6]) {
      if (blockers.isNotEmpty) break;
      if ({2, 3, 4}.contains(phase)) {
        final v = await validator.check(id, phase: phase);
        if (v['pass'] != true) {
          blockers = (v['blockers'] as List? ?? [])
              .map((b) => b.toString())
              .toList();
          learnings.record(
            featureId: id,
            phase: phase,
            kind: 'failure',
            blockers: blockers,
          );
          break;
        }
      }
      _advance(id, phase);
      completed.add(phase);
      // Cryptographically seal this phase: artifacts + gates into the chain.
      integrity.seal(id, phase: phase, actor: 'adf-crew');
      learnings.record(featureId: id, phase: phase, kind: 'success');
    }

    final summary = {
      'feature_id': id,
      'mode': 'multi_agent_crew',
      'agents': agentResults,
      'waves': waves,
      'parallelism': waves.map((w) => w.length).reduce((a, b) => a > b ? a : b),
      'phases_completed': completed,
      'stop_reason':
          blockers.isNotEmpty ? 'blocked' : 'implementation_handoff',
      'blockers': blockers,
      'token_cost': engine.brain.billsTokens ? 'metered' : 'zero',
      'integrity': integrity.verify(id),
      'brain': engine.brain.name,
      'duration_ms': DateTime.now().difference(started).inMilliseconds,
    };
    traces?.append(
      featureId: id,
      name: 'crew.finished',
      event: 'crew',
      message: blockers.isNotEmpty
          ? 'Crew blocked: ${blockers.first}'
          : 'Crew complete — phases ${completed.join(', ')} ready; handing off to implementation.',
    );
    _announce(id, summary);
    return summary;
  }

  /// Runs one subagent under [agentBudget]. On breach: log a `timed_out`
  /// entry with elapsed_ms, escalate ONCE to the next-higher tier via
  /// [escalation], then return a `blocked` entry if the retry also breaches
  /// (or no escalation hook is wired).
  Future<Map<String, dynamic>> _runWithBudget(String id, CrewAgent agent) async {
    final sw = Stopwatch()..start();
    Map<String, dynamic> entry(String status, {String? escalatedTo}) => {
          'agent': agent.name,
          'role': agent.role,
          'phase': agent.phase,
          'status': status,
          'elapsed_ms': sw.elapsedMilliseconds,
          'budget_ms': agentBudget.inMilliseconds,
          if (escalatedTo != null) 'escalated_to': escalatedTo,
        };

    try {
      final artifacts = await agent.run().timeout(agentBudget);
      sw.stop();
      return {
        ...entry('ok'),
        'artifacts': artifacts,
        'duration_ms': sw.elapsedMilliseconds,
      };
    } on TimeoutException {
      final escalatedTo = escalation?.tier;
      _logAgent(id, {
        ...entry('timed_out'),
        'escalated_to': escalatedTo,
      });
      if (escalation == null) {
        sw.stop();
        return {...entry('blocked'), 'escalated_to': null};
      }
      try {
        final artifacts =
            await escalation!.run(id, agent.phase).timeout(agentBudget);
        sw.stop();
        return {
          ...entry('escalated', escalatedTo: escalatedTo),
          'artifacts': artifacts,
          'duration_ms': sw.elapsedMilliseconds,
        };
      } on TimeoutException {
        sw.stop();
        return entry('blocked', escalatedTo: escalatedTo);
      }
    }
  }

  void _advance(String id, int phase) {
    final state = store.readState(id);
    store.setGateForPhase(state, phase, true);
    final builders =
        Map<String, dynamic>.from(state['completed_builders'] as Map? ?? {});
    builders['$phase'] = ['adf-crew'];
    state['completed_builders'] = builders;
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    state['current_phase'] = store.inferWorkPhase(gates);
    state['status'] = 'active';
    state['awaiting_user'] = false;
    store.writeState(id, state);
  }

  void _logAgent(String id, Map<String, dynamic> entry) {
    final file = File('${store.featurePath(id)}/crew-log.jsonl');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(
      '${jsonEncode({...entry, 'ts': DateTime.now().toUtc().toIso8601String()})}\n',
      mode: FileMode.append,
    );
  }

  void _announce(String id, Map<String, dynamic> summary) {
    final agents = summary['agents'] as List;
    final waves = summary['waves'] as List;
    final text = StringBuffer('**Multi-agent crew finished.**\n\n');
    for (final w in waves) {
      text.writeln('- Wave: ${(w as List).join(' + ')}');
    }
    text
      ..writeln('- ${agents.length} subagents, max parallelism '
          '${summary['parallelism']}, ${summary['duration_ms']}ms total, '
          'token cost: ${summary['token_cost']}')
      ..writeln(summary['stop_reason'] == 'implementation_handoff'
          ? '- Next: phase 7 implementation against the red tests.'
          : '- Blocked: ${(summary['blockers'] as List).join('; ')}');
    final cmd = store.appendCommand(id, prompt: 'crew', execute: false);
    store.updateCommandMeta(
      id,
      cmd['id'] as String,
      assistantReply: text.toString().trim(),
      llmSource: 'crew',
    );
    store.markCommandExecuted(id, cmd['id'] as String);
  }
}
