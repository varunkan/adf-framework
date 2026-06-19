import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/models/trace_span.dart';

TraceSpan runner(String type, {Map<String, dynamic>? extra}) =>
    TraceSpan.fromJson({
      'timestamp': '2026-06-19T12:00:00Z',
      'name': 'runner.$type',
      'status': 'OK',
      'attributes': {'orch.feature_id': 'demo', if (extra != null) ...extra},
    });

void main() {
  group('TraceSpan.cardKind (honest typed classification)', () {
    test('verify result is green ONLY when runner.ok == true', () {
      expect(runner('verify_stage_result', extra: {'runner.ok': true}).cardKind,
          'VERIFY_OK');
      expect(runner('verify_stage_result', extra: {'runner.ok': false}).cardKind,
          'VERIFY_FAIL');
      // fail-safe: a MISSING ok flag must never render green
      expect(runner('verify_stage_result').cardKind, 'VERIFY_FAIL');
    });

    test('verify_result binds to ok too', () {
      expect(runner('verify_result', extra: {'runner.ok': true}).cardKind,
          'VERIFY_OK');
      expect(runner('verify_result', extra: {'runner.ok': false}).cardKind,
          'VERIFY_FAIL');
    });

    test('running stages claim no verdict (VERIFY_RUN)', () {
      expect(runner('verify_stage', extra: {'runner.stage': 'vitest'}).cardKind,
          'VERIFY_RUN');
      expect(runner('verifying').cardKind, 'VERIFY_RUN');
    });

    test('policy gate binds to ok; blocked is its own kind', () {
      expect(
          runner('policy_gate', extra: {'runner.ok': true}).cardKind, 'POLICY_OK');
      expect(runner('policy_gate', extra: {'runner.ok': false}).cardKind,
          'POLICY_WARN');
      expect(runner('policy_blocked').cardKind, 'BLOCKED');
    });

    test('seal only on a sealed event, exposes the real seal', () {
      expect(runner('sealing').cardKind, 'SEALING');
      final s = runner('sealed', extra: {'runner.seal': 'abc123'});
      expect(s.cardKind, 'SEAL');
      expect(s.runnerSeal, 'abc123');
    });

    test('build_complete binds to ok', () {
      expect(runner('build_complete', extra: {'runner.ok': true}).cardKind,
          'DONE_OK');
      expect(runner('build_complete', extra: {'runner.ok': false}).cardKind,
          'DONE_FAIL');
    });

    test('file.write is FILE_WRITE and exposes the path', () {
      final fw = TraceSpan.fromJson({
        'timestamp': 't',
        'name': 'file.write',
        'status': 'OK',
        'attributes': {
          'runner.path': 'src/App.tsx',
          'orch.message': 'Writing src/App.tsx (3/6)',
        },
      });
      expect(fw.cardKind, 'FILE_WRITE');
      expect(fw.runnerPath, 'src/App.tsx');
    });

    test('unknown runner control events are HIDDEN (never shown as cards)', () {
      expect(runner('superseded').cardKind, 'HIDDEN');
      expect(runner('cancel').cardKind, 'HIDDEN');
      expect(runner('some_future_control').cardKind, 'HIDDEN');
    });

    test('step events fall to STEP; non-runner spans keep displayKind', () {
      expect(runner('feature_resolved').cardKind, 'STEP');
      expect(runner('planning').cardKind, 'STEP');
      final reasoning = TraceSpan.fromJson({
        'timestamp': 't',
        'name': 'agent.thought',
        'status': 'OK',
        'attributes': {'agent.reasoning': 'thinking…'},
      });
      expect(reasoning.cardKind, 'REASONING'); // falls through to displayKind
    });
  });
}
