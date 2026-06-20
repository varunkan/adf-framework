/// Pure helpers for the pipeline-rail phase selection (D6), so the deselect /
/// auto-clear behaviour is unit-testable instead of buried in the screen build.

/// The phase the rail should HIGHLIGHT: the explicitly-selected phase when one is
/// picked, else the live phase — so DESELECTING returns the highlight to the
/// build's current phase (it used to stay pinned to the old viewPhase).
int railHighlight({
  required bool phaseClicked,
  required int viewPhase,
  required int livePhase,
}) =>
    phaseClicked && viewPhase > 0 ? viewPhase : (livePhase > 0 ? livePhase : 1);

/// The phase whose artifacts are focused (drives the Artifacts-tab dot); null when
/// nothing is explicitly selected (so deselect unlights the dot).
int? artifactSelection({required bool phaseClicked, required int viewPhase}) =>
    phaseClicked && viewPhase > 0 ? viewPhase : null;

/// Whether a manual selection should be released. Only on build COMPLETION — NOT
/// on every phase advance, which would yank a deliberate look-back at a past phase.
bool clearSelectionOnComplete({
  required bool phaseClicked,
  required bool complete,
}) =>
    phaseClicked && complete;
