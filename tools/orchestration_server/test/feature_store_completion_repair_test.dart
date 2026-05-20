import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  const id = 'repair-completion-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
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

  test('repairStalePhaseCompletionMaps drops builders/reviewers ahead of gates', () {
    final state = store.readState(id)
      ..['gates'] = {
        'problem_statement_approved': false,
        'requirements_complete': false,
        'plan_covers_all_requirements': false,
        'tasks_atomic_and_traced': false,
        'test_strategy_approved': false,
        'tests_red': false,
        'tests_green': false,
        'r100': false,
        'l100': false,
        'l100_repo': false,
        'l100_feature': false,
        'lint_clean': false,
        'security_clean': false,
        'performance_clean': false,
        'all_quality_gates_pass': false,
        'review_approved': false,
      }
      ..['completed_builders'] = {
        '1': ['orch-product-analyst'],
        '7': ['speckit-implement'],
      }
      ..['completed_reviewers'] = {
        '8': ['bmad-agent-analyst'],
      };

    store.writeState(id, state);

    store.reconcileFeatureState(id);

    final disk = store.readState(id);
    expect(
      disk['completed_builders'],
      {
        '1': ['orch-product-analyst'],
      },
    );
    expect(disk['completed_reviewers'], isEmpty);
  });
}
