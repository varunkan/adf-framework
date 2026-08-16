import 'dart:io';

import 'package:orchestration_server/approval_gate.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

/// P0-5: the proof-governance enforcement point. The /approve route shells
/// approval_gate.dart; these pin the rules that route had no test for — the
/// decision allowlist, the verdict/revise gates with waiver overrides, and the
/// state transitions (advance, the `completed` terminal, revise bookkeeping,
/// reject). Plus the childEnvFor ADF_FEATURE_ID injection the runner relies on.
void main() {
  group('decision allowlist', () {
    test('only approved/revise/rejected are valid', () {
      for (final d in ['approved', 'revise', 'rejected']) {
        expect(isValidDecision(d), isTrue, reason: d);
      }
      for (final d in ['reject', 'deny', 'APPROVED', 'approve', '', 'ok']) {
        expect(isValidDecision(d), isFalse, reason: d);
      }
    });
  });

  group('checkApprovalGate', () {
    test('approve is blocked (409) when the judge verdict is not pass', () {
      final g = checkApprovalGate(
          decision: 'approved',
          verdict: 'revise',
          judgeWaiver: false,
          clientConfirmed: false);
      expect(g.blocked, isTrue);
      expect(g.status, 409);
      expect(g.reason, contains('verdict is not pass'));
    });

    test('judge_waiver overrides a failing verdict', () {
      final g = checkApprovalGate(
          decision: 'approved',
          verdict: 'revise',
          judgeWaiver: true,
          clientConfirmed: false);
      expect(g.blocked, isFalse);
    });

    test('approve passes the gate when verdict is pass', () {
      final g = checkApprovalGate(
          decision: 'approved',
          verdict: 'pass',
          judgeWaiver: false,
          clientConfirmed: false);
      expect(g.blocked, isFalse);
    });

    test('revise requires client confirmation (400)', () {
      final blocked = checkApprovalGate(
          decision: 'revise',
          verdict: 'revise',
          judgeWaiver: false,
          clientConfirmed: false);
      expect(blocked.blocked, isTrue);
      expect(blocked.status, 400);
      final ok = checkApprovalGate(
          decision: 'revise',
          verdict: 'revise',
          judgeWaiver: false,
          clientConfirmed: true);
      expect(ok.blocked, isFalse);
    });

    test('reject is never gated', () {
      final g = checkApprovalGate(
          decision: 'rejected',
          verdict: null,
          judgeWaiver: false,
          clientConfirmed: false);
      expect(g.blocked, isFalse);
    });
  });

  group('applyApprovalDecision', () {
    late Directory tmp;
    late FeatureStore store;
    setUp(() {
      tmp = Directory.systemTemp.createTempSync('adf-approve');
      store = FeatureStore(tmp.path);
    });
    tearDown(() => tmp.existsSync() ? tmp.deleteSync(recursive: true) : null);

    Map<String, dynamic> stateAt(int phase) =>
        {'gates': <String, dynamic>{}, 'current_phase': phase, 'status': 'active'};

    test('approve mid-pipeline sets the gate, clears flags, advances one phase',
        () {
      final state = stateAt(5);
      state['awaiting_user'] = true;
      state['pending_approval_phase'] = 5;
      final seal = applyApprovalDecision(store, state, 5, 'approved');
      expect(seal, isTrue, reason: 'a genuine approval must be sealed');
      expect((state['gates'] as Map)['test_strategy_approved'], isTrue);
      expect(state['awaiting_user'], isFalse);
      expect(state['pending_approval_phase'], isNull);
      expect(state['current_phase'], 6);
      expect(state['status'], 'active');
    });

    test('approving the last phase pins it and marks completed (terminal)', () {
      final state = stateAt(9);
      final seal = applyApprovalDecision(store, state, 9, 'approved');
      expect(seal, isTrue);
      expect(state['current_phase'], FeatureStore.lastPipelinePhase);
      expect(state['status'], 'completed');
      expect((state['gates'] as Map)['review_approved'], isTrue);
    });

    test('approve never regresses an already-further current_phase', () {
      final state = stateAt(8); // already past the phase being approved
      applyApprovalDecision(store, state, 5, 'approved');
      expect(state['current_phase'], 8);
    });

    test('revise records the phase, bumps the count, keeps awaiting_user', () {
      final state = stateAt(3);
      final seal = applyApprovalDecision(store, state, 3, 'revise');
      expect(seal, isFalse, reason: 'a revise is not sealed');
      expect(state['pending_approval_phase'], 3);
      expect(state['phase_revision_count'], 1);
      expect(state['awaiting_user'], isTrue);
      applyApprovalDecision(store, state, 3, 'revise');
      expect(state['phase_revision_count'], 2);
    });

    test('reject is terminal and clears awaiting_user', () {
      final state = stateAt(4);
      state['awaiting_user'] = true;
      final seal = applyApprovalDecision(store, state, 4, 'rejected');
      expect(seal, isFalse);
      expect(state['status'], 'rejected');
      expect(state['awaiting_user'], isFalse);
    });
  });

  group('childEnvFor', () {
    test('injects ADF_FEATURE_ID explicitly and inherits parent env', () {
      final tmp = Directory.systemTemp.createTempSync('adf-childenv');
      addTearDown(() => tmp.existsSync() ? tmp.deleteSync(recursive: true) : null);
      final store = FeatureStore(tmp.path);
      final runner = PhaseRunner(store, env: {'PATH': '/usr/bin', 'FOO': 'bar'});
      final env = runner.childEnvFor('checkout-flow');
      expect(env['ADF_FEATURE_ID'], 'checkout-flow',
          reason: 'the runner must never guess the id from prompt prose');
      expect(env.containsKey('ADF_STACK'), isTrue);
      expect(env['FOO'], 'bar', reason: 'inherits the parent env');
    });
  });
}
