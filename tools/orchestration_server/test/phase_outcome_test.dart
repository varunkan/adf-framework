import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

/// B3 — the durable phase-completion line must never claim "tests passed" when
/// the tests_green gate is not set. In the regulatory-affairs incident a phase-7
/// build exited 0 with tests_green=false yet the chat said "the build ran and
/// tests passed" — a flat contradiction with the blocked feature.
void main() {
  group('B3: phaseOutcomeLine never lies about tests', () {
    test('phase 7 with tests NOT green does not claim tests passed', () {
      final line = phaseOutcomeLine(7, awaiting: false, testsGreen: false);
      expect(line, isNot(contains('tests passed')),
          reason: 'a phase-7 build with tests_green=false must not read as success');
      expect(line.toLowerCase(), contains('not'),
          reason: 'it must say tests are not green / phase not complete');
    });

    test('phase 7 with tests green reports success', () {
      final line = phaseOutcomeLine(7, awaiting: false, testsGreen: true);
      expect(line, contains('tests passed'));
    });

    test('awaiting approval reads as ready for review regardless of tests', () {
      final line = phaseOutcomeLine(6, awaiting: true, testsGreen: false);
      expect(line, contains('review and approval'));
    });

    test('pre-implementation phases are not flagged on tests_green', () {
      final line = phaseOutcomeLine(3, awaiting: false, testsGreen: false);
      expect(line, isNot(contains('not green')));
    });
  });
}
