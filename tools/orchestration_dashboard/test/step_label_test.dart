import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/step_label.dart';

void main() {
  group('stepLabelFromId', () {
    test('a test-plan id is "Writing tests", NOT "Planning" (D4 order bug)', () {
      expect(stepLabelFromId('bmad-test-plan-phase-5', 5), 'Writing tests');
      expect(stepLabelFromId('build-test-cases', 5), 'Writing tests');
    });

    test('a plain plan id is "Planning"', () {
      expect(stepLabelFromId('create-plan', 3), 'Planning');
    });

    test('review wins over spec', () {
      expect(stepLabelFromId('spec-review-phase-2', 2), 'Reviewing with the AI panel');
    });

    test('spec / implement / intake map as expected', () {
      expect(stepLabelFromId('write-spec', 2), 'Writing the spec');
      expect(stepLabelFromId('implement-feature', 7), 'Building');
      expect(stepLabelFromId('problem-intake', 1), 'Capturing requirements');
    });

    test('empty/null id falls back to the phase', () {
      expect(stepLabelFromId(null, 4), 'Phase 4');
      expect(stepLabelFromId('   ', null), 'Working…');
    });

    test('unknown id is prettified, never the raw machine id', () {
      expect(stepLabelFromId('some-unknown-step', 3), 'some unknown step');
    });
  });
}
