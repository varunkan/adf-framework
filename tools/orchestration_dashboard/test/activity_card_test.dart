import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/widgets/activity_card.dart';

void main() {
  group('activityTone — honest visual mapping', () {
    test('positive/sealed ONLY for real-success kinds', () {
      expect(activityTone('VERIFY_OK'), ActivityTone.positive);
      expect(activityTone('POLICY_OK'), ActivityTone.positive);
      expect(activityTone('DONE_OK'), ActivityTone.positive);
      expect(activityTone('SEAL'), ActivityTone.sealed);
    });

    test('negative for failure / blocked', () {
      expect(activityTone('VERIFY_FAIL'), ActivityTone.negative);
      expect(activityTone('DONE_FAIL'), ActivityTone.negative);
      expect(activityTone('BLOCKED'), ActivityTone.negative);
    });

    test('in-progress kinds are active; misc is neutral', () {
      expect(activityTone('VERIFY_RUN'), ActivityTone.active);
      expect(activityTone('GENERATE'), ActivityTone.active);
      expect(activityTone('SEALING'), ActivityTone.active);
      expect(activityTone('FILE_WRITE'), ActivityTone.neutral);
      expect(activityTone('STEP'), ActivityTone.neutral);
    });

    test('NO non-success kind is ever positive/sealed (the moat in pixels)', () {
      const nonSuccess = [
        'VERIFY_FAIL', 'DONE_FAIL', 'BLOCKED', 'POLICY_WARN', 'VERIFY_RUN',
        'SEALING', 'FILE_WRITE', 'STEP', 'AUDIT', 'HEAL', 'DEPS', 'SCAFFOLD',
        'GENERATE',
      ];
      for (final k in nonSuccess) {
        final t = activityTone(k);
        expect(t == ActivityTone.positive || t == ActivityTone.sealed, isFalse,
            reason: '$k must never render as positive/sealed');
      }
    });
  });
}
