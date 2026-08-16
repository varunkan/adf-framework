import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/status_banner.dart';

/// DASH-honest: the status bar must never lie. These pin the two guarantees —
/// a blocked/failed run is never shown as success, and there is never a blank bar.
void main() {
  StatusBanner bannerFor(String runSt,
          {bool done = false, int phase = 5, String? error}) =>
      statusBanner(
        runSt: runSt,
        awaiting: false,
        agentActive: false,
        isRunning: false,
        done: done,
        longRun: false,
        phase: phase,
        error: error,
      );

  group('statusBanner — never blank, never a false success', () {
    test('every server-emitted status yields a non-empty title and body', () {
      // The full set the orchestration server can write into run-status.json.
      const statuses = [
        'idle', 'queued', 'running', 'building', 'healing', 'blocked', 'error',
        'needs_login', 'escalated', 'unavailable', 'disabled', 'no_app',
        'spawn_failed', 'failed_to_start', 'build_failed', 'pending', 'executed',
        'ok', 'active', 'completed', 'totally_unknown_future_status',
      ];
      for (final s in statuses) {
        final b = bannerFor(s);
        expect(b.title, isNotEmpty, reason: 'title blank for "$s"');
        expect(b.body, isNotEmpty, reason: 'body blank for "$s"');
      }
    });

    test('blocked is an error, not success', () {
      final b = bannerFor('blocked');
      expect(b.kind, BannerKind.error);
      expect(b.isSuccess, isFalse);
      expect(b.title, 'Build stopped');
    });

    test('build-did-not-start statuses surface as error (no silent blank)', () {
      for (final s in const [
        'build_failed', 'failed_to_start', 'spawn_failed', 'escalated',
        'unavailable', 'disabled',
      ]) {
        final b = bannerFor(s);
        expect(b.kind, BannerKind.error, reason: s);
        expect(b.title, 'Build did not start', reason: s);
      }
    });

    test('a runner error message is surfaced verbatim, not hidden', () {
      final b = bannerFor('build_failed', error: 'npm ci exploded');
      expect(b.body, contains('npm ci exploded'));
    });

    test('an unknown status falls to "Needs attention", never blank', () {
      final b = bannerFor('quantum_flux');
      expect(b.title, 'Needs attention');
      expect(b.isSuccess, isFalse);
      expect(b.body, contains('quantum_flux'));
    });

    test('done is the only path to a success banner', () {
      expect(bannerFor('idle', done: true).kind, BannerKind.success);
      // ...and a failed/blocked status never flips to success even if done leaks.
      expect(bannerFor('blocked', done: true).isSuccess, isFalse);
    });
  });

  group('autopilotOutcomeMessage — blocked is never celebrated', () {
    test('blocked summary names the blocker, not a completion brag', () {
      final msg = autopilotOutcomeMessage({
        'phases_completed': [2, 3],
        'stop_reason': 'blocked',
        'blockers': ['schema.sql failed to apply'],
        'agents': [1, 2, 3],
        'duration_ms': 1200,
      });
      expect(msg, contains('blocked'));
      expect(msg, contains('schema.sql failed to apply'));
      expect(msg, isNot(contains('completed phases 2, 3 in')));
    });

    test('stop_reason blocked with no blocker list still reads as blocked', () {
      final msg = autopilotOutcomeMessage(
          {'phases_completed': [], 'stop_reason': 'blocked', 'agents': []});
      expect(msg, startsWith('Autopilot blocked:'));
    });

    test('a clean handoff reads as a success summary', () {
      final msg = autopilotOutcomeMessage({
        'phases_completed': [2, 3, 4],
        'stop_reason': 'implementation_handoff',
        'blockers': [],
        'agents': [1, 2],
        'duration_ms': 900,
      });
      expect(msg, contains('completed phases 2, 3, 4'));
      expect(msg, isNot(contains('blocked')));
    });

    test('nothing-to-do summary is reported honestly', () {
      final msg = autopilotOutcomeMessage(
          {'phases_completed': [], 'stop_reason': 'idle', 'agents': []});
      expect(msg, contains('nothing to do'));
    });
  });

  group('blockersOf', () {
    test('extracts non-empty trimmed strings', () {
      expect(blockersOf({'blockers': ['  a  ', '', 'b']}), ['a', 'b']);
    });
    test('missing/!list → empty', () {
      expect(blockersOf({}), isEmpty);
      expect(blockersOf({'blockers': 'nope'}), isEmpty);
    });
  });
}
