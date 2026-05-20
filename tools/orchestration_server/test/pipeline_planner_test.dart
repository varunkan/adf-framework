import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/pipeline_planner.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  late PipelinePlanner planner;

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
    planner = PipelinePlanner(store);
  });

  test('buildPlan includes phases 0-9', () {
    final ids = store.listFeatures();
    if (ids.isEmpty) {
      // Create ephemeral test feature
      const id = '_planner-test';
      if (store.featureExists(id)) {
        Directory(store.featurePath(id)).deleteSync(recursive: true);
      }
      store.createFeature(
        id: id,
        requirement: 'test',
        track: 'S',
      );
      addTearDown(() {
        Directory(store.featurePath(id)).deleteSync(recursive: true);
      });
      final plan = planner.buildPlan(id);
      expect(plan['phases'], isA<List>());
      final phases = plan['phases'] as List;
      expect(phases.length, greaterThanOrEqualTo(10));
      expect(plan['current_step_id'], isNotNull);
      expect(plan['summary'], isA<Map>());
    } else {
      final plan = planner.buildPlan(ids.first);
      expect(plan['feature_id'], ids.first);
      expect(plan['phases'], isA<List>());
    }
  });

  test('bootstrapped feature has exactly one active pipeline phase', () {
    const id = 'planner-single-active';
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    store.createFeature(id: id, requirement: 'single active', track: 'S');
    final specDir = Directory('$repoRoot/specs/$id');
    specDir.createSync(recursive: true);
    File('${specDir.path}/spec.md').writeAsStringSync('# spec\n');
    final state = store.readState(id)
      ..['current_phase'] = 0
      ..['status'] = 'active';
    store.writeState(id, state, skipRepair: true);
    store.reconcileFeatureState(id);

    final plan = planner.buildPlan(id);
    final phases = (plan['phases'] as List).cast<Map<String, dynamic>>();
    final active =
        phases.where((p) => p['status'] == 'active').map((p) => p['phase']).toList();
    expect(active, [1], reason: 'phase 0 done + work phase 1 active only');
    expect(plan['current_phase'], 1);

    specDir.deleteSync(recursive: true);
    Directory(store.featurePath(id)).deleteSync(recursive: true);
  });

  test('phase 1 has builder steps', () {
    final ids = store.listFeatures();
    if (ids.isEmpty) return;
    final plan = planner.buildPlan(ids.first);
    final phases = plan['phases'] as List;
    final p1 = phases.cast<Map<String, dynamic>>().firstWhere(
          (p) => p['phase'] == 1,
          orElse: () => <String, dynamic>{},
        );
    if (p1.isEmpty) return;
    final steps = p1['steps'] as List;
    expect(steps.any((s) => (s as Map)['kind'] == 'builder'), isTrue);
  });
}
