/// Whether a seemingly-stuck run (agent still "active" while the state already
/// says awaiting_user / awaiting_approval) should be auto-cancelled to recover the
/// UI.
///
/// Only true once the stuck state has PERSISTED for at least [grace], as observed
/// by the CLIENT (`stuckFor` = how long we've been seeing it). Never true on the
/// first sighting: a phase that just finished and set awaiting_user briefly looks
/// stuck while the agent process tears down, and cancelling then would clear the
/// approval gate before the human sees it. Anchored to client-observed duration —
/// NOT a server `started_at`, which ages independently and would leave a >grace
/// phase's fresh gate unprotected (D16). Because [stuckFor] resets to null
/// whenever the run is no longer stuck, the valve re-arms per stuck-episode (D15).
bool shouldAutoUnstick({
  required bool stuck,
  required Duration? stuckFor,
  Duration grace = const Duration(seconds: 30),
}) =>
    stuck && stuckFor != null && stuckFor >= grace;
