import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  const id = 'pipeline-repair-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) {
        throw StateError('repo root not found');
      }
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    if (!store.featureExists(id)) {
      store.createFeature(id: id, requirement: 'repair test', track: 'M');
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) {
      specDir.deleteSync(recursive: true);
    }
  });

  test('repairPipelineState clamps phase 10 and marks completed when all gates true',
      () {
    final state = store.readState(id)
      ..['current_phase'] = 10
      ..['status'] = 'active'
      ..['gates'] = {
        for (final e in FeatureStore.phaseGateMap.entries) e.value: true,
      };

    store.writeState(id, state, skipRepair: true);
    store.reconcileFeatureState(id);

    final disk = store.readState(id);
    expect(disk['current_phase'], 9);
    expect(disk['status'], 'completed');
    expect(store.effectivePhase(id, disk), 9);
  });

  test('a blocked feature is NOT awaiting approval — phantom phase gate cleared',
      () {
    // Repro: a feature blocked at phase 7 with a STALE awaiting_user + a
    // pending_approval_phase pointing at an already-passed phase made the UI ask
    // "approve phase 1" — a phase the user can neither act on nor see content for.
    final state = store.readState(id)
      ..['status'] = 'blocked'
      ..['current_phase'] = 7
      ..['awaiting_user'] = true
      ..['pending_approval_phase'] = 1
      ..['gates'] = {
        'problem_statement_approved': true,
        'requirements_complete': true,
        'plan_covers_all_requirements': true,
        'tasks_atomic_and_traced': true,
        'test_strategy_approved': true,
        'tests_red': true,
      };
    store.writeState(id, state, skipRepair: true);

    final disk = store.readState(id); // readState repairs
    expect(disk['awaiting_user'], isFalse,
        reason: 'a blocked feature has FAILED — it is not awaiting your approval');
    expect(disk['pending_approval_phase'], isNull,
        reason: 'no phantom "approve phase N" gate on a blocked feature');
    expect(disk['status'], 'blocked', reason: 'still blocked — the real state');
  });

  test('repairRunStatus clears queued when feature completed', () {
    final state = store.readState(id)
      ..['current_phase'] = 9
      ..['status'] = 'completed'
      ..['gates'] = {
        for (final e in FeatureStore.phaseGateMap.entries) e.value: true,
      };
    store.writeState(id, state, skipRepair: true);
    store.writeRunStatus(id, {
      'status': 'queued',
      'agent_active': true,
    });

    store.repairRunStatus(id);

    final run = store.readRunStatus(id);
    expect(run?['status'], 'idle');
    expect(run?['agent_active'], false);
  });
}
