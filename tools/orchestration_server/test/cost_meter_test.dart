import 'dart:io';

import 'package:orchestration_server/cost_meter.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  const id = 'cost-meter-test';

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_cost_test_');
    store = FeatureStore(tmp.path);
    store.createFeature(
      id: id,
      requirement: 'Meter real agent spend per run.',
      track: 'S',
    );
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  test('claude-style result event records the reported cost', () {
    final meter = CostMeter(store, env: const {});
    meter.recordFromResultEvent(
      id,
      {
        'type': 'result',
        'total_cost_usd': 0.042,
        'usage': {'input_tokens': 1200, 'output_tokens': 350},
      },
      phase: 6,
    );

    final cost = meter.featureCost(id);
    expect(cost['feature_id'], id);
    expect(cost['total_usd'], closeTo(0.042, 1e-9));
    expect(cost['total_input_tokens'], 1200);
    expect(cost['total_output_tokens'], 350);
    expect(cost['zero_cost'], isFalse);
    final run = (cost['runs'] as List).single as Map<String, dynamic>;
    expect(run['source'], CostMeter.sourceReported);
    expect(run['phase'], 6);
    expect(DateTime.tryParse(run['at'] as String), isNotNull);
  });

  test('usage-only event is estimated from env per-MTok rates', () {
    final meter = CostMeter(store, env: const {
      'ORCH_PRICE_IN_PER_MTOK': '3',
      'ORCH_PRICE_OUT_PER_MTOK': '15',
    });
    meter.recordFromResultEvent(
      id,
      {
        'type': 'result',
        'usage': {'input_tokens': 1000000, 'output_tokens': 200000},
      },
      phase: 2,
    );

    final cost = meter.featureCost(id);
    // 1M in @ $3/MTok + 0.2M out @ $15/MTok = 3 + 3 = 6.
    expect(cost['total_usd'], closeTo(6.0, 1e-9));
    expect(cost['zero_cost'], isFalse);
    final run = (cost['runs'] as List).single as Map<String, dynamic>;
    expect(run['source'], CostMeter.sourceEstimated);
    expect(run['usd'], closeTo(6.0, 1e-9));
  });

  test('bare result event with no rates records a zero run', () {
    final meter = CostMeter(store, env: const {});
    meter.recordFromResultEvent(id, {'type': 'result', 'result': 'done'});

    final cost = meter.featureCost(id);
    expect(cost['total_usd'], 0);
    expect(cost['total_input_tokens'], 0);
    expect(cost['total_output_tokens'], 0);
    expect(cost['zero_cost'], isTrue);
    final run = (cost['runs'] as List).single as Map<String, dynamic>;
    expect(run['source'], CostMeter.sourceZero);
    expect(run['phase'], isNull);
  });

  test('cost accumulates across runs and persists to cost.json', () {
    final meter = CostMeter(store, env: const {});
    meter.recordFromResultEvent(
      id,
      {
        'type': 'result',
        'total_cost_usd': 0.01,
        'usage': {'input_tokens': 100, 'output_tokens': 10},
      },
      phase: 1,
    );
    meter.recordFromResultEvent(
      id,
      {
        'type': 'result',
        'total_cost_usd': 0.02,
        'usage': {'input_tokens': 200, 'output_tokens': 20},
      },
      phase: 2,
    );

    expect(File('${store.featurePath(id)}/cost.json').existsSync(), isTrue);
    // A fresh meter reads the same persisted evidence back.
    final cost = CostMeter(store, env: const {}).featureCost(id);
    expect((cost['runs'] as List).length, 2);
    expect(cost['total_usd'], closeTo(0.03, 1e-9));
    expect(cost['total_input_tokens'], 300);
    expect(cost['total_output_tokens'], 30);
    expect(
      (cost['runs'] as List).map((r) => r['phase']),
      containsAllInOrder([1, 2]),
    );
  });

  test('summary aggregates across multiple features', () {
    store.createFeature(
      id: 'cost-meter-other',
      requirement: 'Second metered feature.',
      track: 'S',
    );
    final meter = CostMeter(store, env: const {});
    meter.recordFromResultEvent(id, {
      'type': 'result',
      'total_cost_usd': 0.05,
      'usage': {'input_tokens': 500, 'output_tokens': 50},
    });
    meter.recordFromResultEvent('cost-meter-other', {'type': 'result'});

    final summary = meter.summary();
    expect(summary['total_usd'], closeTo(0.05, 1e-9));
    expect(summary['zero_cost'], isFalse);
    final byFeature =
        (summary['by_feature'] as List).cast<Map<String, dynamic>>();
    expect(
      byFeature.map((f) => f['feature_id']),
      containsAll([id, 'cost-meter-other']),
    );
    expect(
      byFeature.firstWhere((f) => f['feature_id'] == id)['total_usd'],
      closeTo(0.05, 1e-9),
    );
    expect(
      byFeature.firstWhere(
          (f) => f['feature_id'] == 'cost-meter-other')['total_usd'],
      0,
    );
  });

  test('zero_cost flips once a metered run lands', () {
    final meter = CostMeter(store, env: const {});
    meter.recordFromResultEvent(id, {'type': 'result'});
    expect(meter.featureCost(id)['zero_cost'], isTrue);
    expect(meter.summary()['zero_cost'], isTrue);

    meter.recordFromResultEvent(
      id,
      {'type': 'result', 'total_cost_usd': 0.001},
      phase: 7,
    );
    final cost = meter.featureCost(id);
    expect((cost['runs'] as List).length, 2);
    expect(cost['zero_cost'], isFalse);
    expect(meter.summary()['zero_cost'], isFalse);
  });
}
