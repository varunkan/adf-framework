import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/agent_crew.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/autopilot.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

/// Engine whose [slowPhases] hang past any tiny test budget (simulating a
/// stuck LLM brain) while every other phase generates real artifacts in
/// milliseconds. Slow phases write nothing, so only a working timeout +
/// escalation path can complete the pipeline.
class SlowEngine extends DeterministicArtifactEngine {
  SlowEngine(
    FeatureStore store, {
    required this.delay,
    required this.slowPhases,
  }) : super(store, brain: DeterministicBrain());

  final Duration delay;
  final Set<int> slowPhases;

  @override
  Future<List<String>> generatePhase(String id, int phase) async {
    if (slowPhases.contains(phase)) {
      await Future<void>.delayed(delay);
      return const [];
    }
    return super.generatePhase(id, phase);
  }
}

void main() {
  late String repoRoot;
  late FeatureStore store;
  late Directory tempLearnings;
  const id = 'agent-timeout-test';
  const budget = Duration(milliseconds: 100);
  const slowDelay = Duration(milliseconds: 400);

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    tempLearnings = Directory.systemTemp.createTempSync('adf-timeout');
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Render the checkout screen. Print a receipt. '
            'Email the receipt to the customer.',
        track: 'M',
      );
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
    tempLearnings.deleteSync(recursive: true);
  });

  AgentCrew buildCrew(
    DeterministicArtifactEngine engine, {
    AgentEscalation? escalation,
  }) =>
      AgentCrew(
        store,
        engine,
        ArtifactValidator(repoRoot),
        LearningStore(tempLearnings.path),
        agentBudget: budget,
        escalation: escalation,
        env: const {'ADF_REQUIREMENTS_CREW': '0'}, // CREW-1: deterministic suite
      );

  AgentEscalation fastEscalation() {
    final fast = DeterministicArtifactEngine(store, brain: DeterministicBrain());
    return AgentEscalation(
      tier: 'fast',
      run: (featureId, phase) => fast.generatePhase(featureId, phase),
    );
  }

  AgentEscalation slowEscalation() => AgentEscalation(
        tier: 'fast',
        run: (featureId, phase) async {
          await Future<void>.delayed(slowDelay);
          return const [];
        },
      );

  List<Map<String, dynamic>> crewLog() =>
      File('${store.featurePath(id)}/crew-log.jsonl')
          .readAsLinesSync()
          .where((l) => l.trim().isNotEmpty)
          .map((l) => jsonDecode(l) as Map<String, dynamic>)
          .toList();

  group('crew agent budget', () {
    test('timeout escalates once and the escalated tier completes the run',
        () async {
      final crew = buildCrew(
        SlowEngine(store, delay: slowDelay, slowPhases: {1}),
        escalation: fastEscalation(),
      );

      final summary = await crew.run(id);

      expect(summary['phases_completed'], [1, 2, 3, 4, 5, 6]);
      // G1: track-M holds for spec approval (was 'implementation_handoff'); the
      // budget/escalation invariant is that all 6 phases still completed (above).
      expect(summary['stop_reason'], 'awaiting_approval');

      final analyst = (summary['agents'] as List)
          .cast<Map>()
          .firstWhere((a) => a['agent'] == 'product-analyst');
      expect(analyst['status'], 'escalated');
      expect(analyst['escalated_to'], 'fast');

      final timedOut =
          crewLog().firstWhere((l) => l['status'] == 'timed_out');
      expect(timedOut['agent'], 'product-analyst');
      expect(timedOut['escalated_to'], 'fast');
      expect(timedOut['elapsed_ms'], isA<int>());
      expect(
        timedOut['elapsed_ms'] as int,
        greaterThanOrEqualTo(budget.inMilliseconds - 10),
        reason: 'breach must be recorded at (or after) the budget',
      );
    });

    test('double timeout blocks the agent and the crew run', () async {
      final crew = buildCrew(
        SlowEngine(store, delay: slowDelay, slowPhases: {1}),
        escalation: slowEscalation(),
      );

      final summary = await crew.run(id);

      expect(summary['stop_reason'], 'blocked');
      expect(summary['phases_completed'], isEmpty);
      expect(
        (summary['blockers'] as List).single,
        allOf(contains('product-analyst'), contains('timed out')),
      );

      final blocked = (summary['agents'] as List)
          .cast<Map>()
          .firstWhere((a) => a['status'] == 'blocked');
      expect(blocked['agent'], 'product-analyst');
      expect(blocked['escalated_to'], 'fast');

      final log = crewLog();
      expect(log.map((l) => l['status']), contains('timed_out'));
      expect(log.map((l) => l['status']), contains('blocked'));
      for (final entry in log) {
        expect(entry['elapsed_ms'], isA<int>(),
            reason: 'every crew log entry carries elapsed_ms');
      }
    });

    test('timeout without an escalation hook blocks immediately', () async {
      final crew = buildCrew(
        SlowEngine(store, delay: slowDelay, slowPhases: {1}),
      );

      final summary = await crew.run(id);

      expect(summary['stop_reason'], 'blocked');
      final blocked = (summary['agents'] as List)
          .cast<Map>()
          .firstWhere((a) => a['status'] == 'blocked');
      expect(blocked['escalated_to'], isNull);
    });

    test('deterministic-brain agents finish untouched under the budget',
        () async {
      final crew = buildCrew(
        DeterministicArtifactEngine(store, brain: DeterministicBrain()),
      );

      final summary = await crew.run(id);

      expect(summary['phases_completed'], [1, 2, 3, 4, 5, 6]);
      // G1: track-M holds for spec approval (was 'implementation_handoff'); the
      // budget/escalation invariant is that all 6 phases still completed (above).
      expect(summary['stop_reason'], 'awaiting_approval');
      expect(
        (summary['agents'] as List).cast<Map>().map((a) => a['status']),
        everyElement('ok'),
      );
    });
  });

  group('autopilot budget surfacing', () {
    Autopilot buildAutopilot(
      DeterministicArtifactEngine engine, {
      AgentEscalation? escalation,
    }) =>
        Autopilot(
          store,
          engine,
          ArtifactValidator(repoRoot),
          LearningStore(tempLearnings.path),
          agentBudget: budget,
          escalation: escalation,
        );

    test('escalated phase surfaces status and escalated_to in the log',
        () async {
      final pilot = buildAutopilot(
        SlowEngine(store, delay: slowDelay, slowPhases: {1}),
        escalation: fastEscalation(),
      );

      final summary = await pilot.run(id);

      expect(summary['phases_completed'], [1, 2, 3, 4, 5, 6]);
      final phase1 = (summary['log'] as List)
          .cast<Map>()
          .firstWhere((e) => e['phase'] == 1);
      expect(phase1['pass'], isTrue);
      expect(phase1['status'], 'escalated');
      expect(phase1['escalated_to'], 'fast');
    });

    test('double timeout blocks the phase with elapsed_ms in the log',
        () async {
      final pilot = buildAutopilot(
        SlowEngine(store, delay: slowDelay, slowPhases: {1}),
        escalation: slowEscalation(),
      );

      final summary = await pilot.run(id);

      expect(summary['stop_reason'], 'blocked');
      expect(summary['phases_completed'], isEmpty);
      final phase1 = (summary['log'] as List)
          .cast<Map>()
          .firstWhere((e) => e['phase'] == 1);
      expect(phase1['pass'], isFalse);
      expect(phase1['status'], 'blocked');
      expect(phase1['escalated_to'], 'fast');
      expect(phase1['elapsed_ms'], isA<int>());
      expect((phase1['blockers'] as List).single, contains('timed out'));
    });
  });

  group('budget resolution from env', () {
    test('agent budget honors ORCH_AGENT_TIMEOUT_SEC with a 30s default', () {
      expect(agentBudgetFromEnv({'ORCH_AGENT_TIMEOUT_SEC': '7'}),
          const Duration(seconds: 7));
      expect(agentBudgetFromEnv({}), const Duration(seconds: 30));
      expect(agentBudgetFromEnv({'ORCH_AGENT_TIMEOUT_SEC': '0'}),
          const Duration(seconds: 30));
      expect(agentBudgetFromEnv({'ORCH_AGENT_TIMEOUT_SEC': 'soon'}),
          const Duration(seconds: 30));
    });

    test('crew picks the env budget when no override is injected', () {
      final crew = AgentCrew(
        store,
        DeterministicArtifactEngine(store, brain: DeterministicBrain()),
        ArtifactValidator(repoRoot),
        LearningStore(tempLearnings.path),
        env: {'ORCH_AGENT_TIMEOUT_SEC': '9', 'ADF_REQUIREMENTS_CREW': '0'},
      );
      expect(crew.agentBudget, const Duration(seconds: 9));
    });

    test('runner budget honors ORCH_RUNNER_TIMEOUT_SEC with a 30s default',
        () {
      expect(PhaseRunner(store, env: {}).runnerTimeout,
          const Duration(seconds: 30));
      expect(
          PhaseRunner(store, env: {'ORCH_RUNNER_TIMEOUT_SEC': '5'})
              .runnerTimeout,
          const Duration(seconds: 5));
      expect(
          PhaseRunner(store, env: {'ORCH_RUNNER_TIMEOUT_SEC': '-1'})
              .runnerTimeout,
          const Duration(seconds: 30));
    });
  });
}
