import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/phase_selection.dart';

void main() {
  group('phase selection (D6)', () {
    test('rail highlights the selected phase, else follows the live phase', () {
      expect(railHighlight(phaseClicked: true, viewPhase: 3, livePhase: 5), 3);
      // Deselected → the rail returns to the live phase (used to stay pinned).
      expect(railHighlight(phaseClicked: false, viewPhase: 3, livePhase: 5), 5);
      expect(railHighlight(phaseClicked: false, viewPhase: 0, livePhase: 0), 1);
    });

    test('artifact dot is null when deselected', () {
      expect(artifactSelection(phaseClicked: true, viewPhase: 3), 3);
      expect(artifactSelection(phaseClicked: false, viewPhase: 3), isNull);
    });

    test('selection clears only when selected AND the build completed', () {
      expect(clearSelectionOnComplete(phaseClicked: true, complete: true), isTrue);
      // Mid-build (not complete): keep the look-back — never yank.
      expect(
          clearSelectionOnComplete(phaseClicked: true, complete: false), isFalse);
      expect(
          clearSelectionOnComplete(phaseClicked: false, complete: true), isFalse);
    });
  });
}
