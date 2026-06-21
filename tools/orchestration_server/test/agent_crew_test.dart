import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/agent_crew.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  late Directory tempLearnings;
  const id = 'agent-crew-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    tempLearnings = Directory.systemTemp.createTempSync('adf-crew');
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

  AgentCrew buildCrew() => AgentCrew(
        store,
        DeterministicArtifactEngine(store, brain: DeterministicBrain()),
        ArtifactValidator(repoRoot),
        LearningStore(tempLearnings.path),
        // CREW-1: this suite exercises the DETERMINISTIC engine; pin the crew off
        // so _specPhase doesn't shell the real python crew (now default-on for M).
        env: const {'ADF_REQUIREMENTS_CREW': '0'},
      );

  CrewAgent agent(String name, {List<String> needs = const []}) => CrewAgent(
        name: name,
        role: name,
        phase: 1,
        needs: needs,
        run: () async => <String>[],
      );

  test('buildExecutionWaves groups independent agents into one parallel wave', () {
    final waves = AgentCrew.buildExecutionWaves([
      agent('a'),
      agent('b', needs: ['a']),
      agent('c', needs: ['a']),
      agent('d', needs: ['b', 'c']),
    ]);
    expect(waves[0], ['a']);
    expect(waves[1].toSet(), {'b', 'c'});
    expect(waves[2], ['d']);
  });

  test('buildExecutionWaves rejects a self-dependency', () {
    expect(() => AgentCrew.buildExecutionWaves([agent('a', needs: ['a'])]),
        throwsArgumentError);
  });

  test('buildExecutionWaves rejects an unknown dependency', () {
    expect(() => AgentCrew.buildExecutionWaves([agent('a', needs: ['ghost'])]),
        throwsArgumentError);
  });

  test('buildExecutionWaves detects a cycle', () {
    expect(
        () => AgentCrew.buildExecutionWaves(
            [agent('a', needs: ['b']), agent('b', needs: ['a'])]),
        throwsArgumentError);
  });

  test('crew runs subagents in parallel dependency waves', () async {
    final summary = await buildCrew().run(id);

    final waves = (summary['waves'] as List).cast<List>();
    expect(waves.first, ['product-analyst']);
    expect(waves[1], ['spec-writer']);
    expect(
      waves[2].toSet(),
      {'architect', 'task-planner', 'test-architect'},
      reason: 'independent agents must run concurrently in one wave',
    );
    expect(waves.last, ['test-author']);
    expect(summary['parallelism'], 3);
    expect(summary['phases_completed'], [1, 2, 3, 4, 5, 6]);
    expect(summary['token_cost'], 'zero');
    // G1: track-M (the default for this fixture) HOLDS for spec approval; the
    // implementation_handoff path is covered by the auto-approve G1 test below.
    expect(summary['stop_reason'], 'awaiting_approval');
  });

  test('crew sets gates and logs every subagent', () async {
    await buildCrew().run(id);

    final gates = store.readState(id)['gates'] as Map<String, dynamic>;
    expect(gates['tests_red'], isTrue);
    expect(store.readState(id)['current_phase'], 7);

    final log = File('${store.featurePath(id)}/crew-log.jsonl');
    expect(log.existsSync(), isTrue);
    expect(log.readAsLinesSync().where((l) => l.trim().isNotEmpty).length, 6);

    final announce = store
        .listCommands(id)
        .lastWhere((c) => c['llm_source'] == 'crew');
    expect(announce['assistant_reply'], contains('Multi-agent crew finished'));
    expect(announce['assistant_reply'], contains('6 subagents'));
  });

  // ---- G1: the requirements/spec hold (track-aware) -----------------------
  // A track-M feature must NOT barrel from the crew straight into phase-7
  // implementation. It must HOLD so the user can confirm the verified spec.
  // _advance hardcoded awaiting_user=false and the summary always reported
  // 'implementation_handoff' (which is what auto-enqueues phase 7) — both
  // bypassing FeatureStore.autoApprove (the track-aware gate). RED until fixed.
  test('G1: a track-M crew HOLDS for spec approval, not implementation_handoff',
      () async {
    final summary = await buildCrew().run(id); // id is track M, no auto_approve
    expect(summary['stop_reason'], 'awaiting_approval',
        reason: 'track M must hold for human confirmation, not hand off to '
            'phase 7 implementation');
    final state = store.readState(id);
    expect(state['awaiting_user'], isTrue,
        reason: 'the feature must wait for the user at the spec gate');
    expect(state['pending_approval_phase'], 6,
        reason: 'approving phase 6 advances current_phase to 7 (implementation)');
  });

  test('G1: an auto-approved feature still hands off to implementation',
      () async {
    final st = store.readState(id);
    st['auto_approve'] = true; // per-feature override → autoApprove true
    store.writeState(id, st);
    final summary = await buildCrew().run(id);
    expect(summary['stop_reason'], 'implementation_handoff');
    expect(store.readState(id)['awaiting_user'], isFalse);
    expect(store.readState(id)['pending_approval_phase'], isNull);
  });
}
