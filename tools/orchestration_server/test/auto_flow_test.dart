import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/run_post_sync.dart';
import 'package:test/test.dart';

/// The "confirm/revise again and again" fix: under auto-approve the per-phase
/// post-sync must NOT pause for a human (it only nagged because awaiting_user was
/// set unconditionally), while still recording the verdict for transparency.
void main() {
  late Directory tmp;
  late FeatureStore store;
  late RunPostSync postSync;
  const id = 'autoflow';

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('adf-autoflow');
    store = FeatureStore(tmp.path);
    postSync = RunPostSync(store);
    store.createFeature(id: id, requirement: 'x', track: 'M');
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  void writeVerdict(int phase, String verdict) {
    final rel = store.paths.featureRel(id, 'judge-verdicts/phase-$phase.md');
    final f = File('${tmp.path}/$rel');
    f.parent.createSync(recursive: true);
    f.writeAsStringSync('# Phase $phase\n\n**Verdict:** $verdict\n');
  }

  group('FeatureStore.autoApprove', () {
    test('per-feature flag wins', () {
      expect(FeatureStore.autoApprove({'auto_approve': true}, {}), isTrue);
    });
    test('track-aware: M/L/XL hold for a human, S may auto, =all forces, default off',
        () {
      // M/L/XL never auto-flow from the global flag — their requirements need a human
      expect(FeatureStore.autoApprove({'track': 'M'}, {'ORCH_AUTO_APPROVE': 'true'}),
          isFalse);
      expect(FeatureStore.autoApprove({'track': 'L'}, {'ORCH_AUTO_APPROVE': '1'}),
          isFalse);
      // unknown/absent track defaults to M (the safe choice) → holds
      expect(FeatureStore.autoApprove({}, {'ORCH_AUTO_APPROVE': 'true'}), isFalse);
      // track-S micro-fixes may auto-flow when the global flag is on
      expect(FeatureStore.autoApprove({'track': 'S'}, {'ORCH_AUTO_APPROVE': 'true'}),
          isTrue);
      expect(FeatureStore.autoApprove({'track': 'S'}, {}), isFalse);
      // =all is the power-user escape hatch: auto-approve every track
      expect(FeatureStore.autoApprove({'track': 'M'}, {'ORCH_AUTO_APPROVE': 'all'}),
          isTrue);
      expect(FeatureStore.autoApprove({}, {}), isFalse);
    });
  });

  test('auto-flow: post-sync records the verdict but does NOT gate awaiting_user',
      () {
    final s = store.readState(id)..['auto_approve'] = true;
    store.writeState(id, s);
    writeVerdict(2, 'PASS');

    final awaiting = postSync.syncAfterRun(id, 2);

    expect(awaiting, isFalse, reason: 'auto-flow must not pause for approval');
    final after = store.readState(id);
    expect(after['awaiting_user'], isNot(true));
    expect(after['last_judge_verdict'], 'pass'); // verdict still recorded
    expect(after['pending_approval_phase'], 2);  // phase noted for transparency
  });

  test('gated mode (auto-approve OFF): post-sync DOES set awaiting_user', () {
    writeVerdict(2, 'PASS'); // auto_approve not set, no env in this process by default
    final result = postSync.syncAfterRun(id, 2);
    // Only assert the gated branch when the ambient env isn't forcing auto-approve.
    if (!FeatureStore.autoApprove(store.readState(id))) {
      expect(result, isTrue);
      expect(store.readState(id)['awaiting_user'], true);
    }
  });

  test('reconcile clears a stranded awaiting_user under auto-approve', () {
    final s = store.readState(id)
      ..['auto_approve'] = true
      ..['awaiting_user'] = true;
    store.writeState(id, s);
    store.reconcileFeatureState(id);
    expect(store.readState(id)['awaiting_user'], isNot(true));
  });
}
