import 'package:orchestration_server/requirements_crew_runner.dart';
import 'package:test/test.dart';

/// CREW-1 — the model-backed requirements crew must be the DEFAULT spec engine
/// for net-new / cross-cutting work (tracks M/L/XL), not opt-in. The deterministic
/// template engine becomes a last-resort fallback. A track-S micro-fix stays off
/// (the full research crew is overkill for ≤1 file). Explicit env wins either way.
void main() {
  group('CREW-1: requirements crew default-on for M/L/XL', () {
    test('default (no env, no track) enables the crew', () {
      expect(RequirementsCrewRunner.isEnabled(const <String, String>{}), isTrue,
          reason: 'the crew must be the default spec engine, not opt-in');
    });

    test('explicit opt-out (=0) disables it', () {
      expect(
          RequirementsCrewRunner.isEnabled(const {'ADF_REQUIREMENTS_CREW': '0'}),
          isFalse);
    });

    test('default-on for M/L/XL, default-off for S', () {
      expect(RequirementsCrewRunner.isEnabled(const {}, 'M'), isTrue);
      expect(RequirementsCrewRunner.isEnabled(const {}, 'L'), isTrue);
      expect(RequirementsCrewRunner.isEnabled(const {}, 'XL'), isTrue);
      expect(RequirementsCrewRunner.isEnabled(const {}, 'S'), isFalse,
          reason: 'a track-S micro-fix should not run the full research crew');
    });

    test('explicit env overrides the track default both ways', () {
      expect(RequirementsCrewRunner.isEnabled(const {'ADF_REQUIREMENTS_CREW': '1'}, 'S'),
          isTrue, reason: 'opt-in forces the crew even on track S');
      expect(RequirementsCrewRunner.isEnabled(const {'ADF_REQUIREMENTS_CREW': '0'}, 'M'),
          isFalse, reason: 'opt-out forces it off even on track M');
    });
  });
}
