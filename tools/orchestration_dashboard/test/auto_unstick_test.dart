import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/auto_unstick.dart';

void main() {
  group('shouldAutoUnstick', () {
    test('never on first sighting (D16): stuckFor null or below grace', () {
      expect(shouldAutoUnstick(stuck: true, stuckFor: null), isFalse);
      expect(
          shouldAutoUnstick(stuck: true, stuckFor: const Duration(seconds: 5)),
          isFalse);
      // A 45s phase that JUST set awaiting_user: client has only seen it briefly.
      expect(
          shouldAutoUnstick(stuck: true, stuckFor: const Duration(seconds: 2)),
          isFalse);
    });

    test('unstick once the stuck state persists past grace', () {
      expect(
          shouldAutoUnstick(stuck: true, stuckFor: const Duration(seconds: 31)),
          isTrue);
    });

    test('not stuck → never unstick (valve re-arms, D15)', () {
      expect(
          shouldAutoUnstick(stuck: false, stuckFor: const Duration(minutes: 5)),
          isFalse);
    });
  });
}
