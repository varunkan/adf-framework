// Pure, testable status-decision logic for the feature detail screen.
//
// The cardinal rule (audit "DASH-honest"): the UI must NEVER lie about state.
// Concretely that means two guarantees this module enforces and tests pin down:
//   1. a blocked / failed run is never presented as success, and
//   2. there is never a blank/empty banner — every reachable status maps to a
//      non-empty title + body, so the user is never left staring at nothing.
//
// Keeping this free of Flutter widgets lets the screen delegate to it (single
// source of truth, no drift) while the guarantees are unit-tested directly.

/// Semantic category of a status banner. The widget maps this to a background
/// colour (running/awaiting/error/success) — the logic here never touches colours.
enum BannerKind { running, awaiting, error, success }

class StatusBanner {
  const StatusBanner(this.kind, this.title, this.body);
  final BannerKind kind;
  final String title;
  final String body;

  bool get isSuccess => kind == BannerKind.success;
}

/// Runner statuses that mean "the build did not even get going". These must read
/// as errors, not as a blank bar (the pre-fix behaviour) and never as success.
const _failedStatuses = {
  'build_failed',
  'failed_to_start',
  'spawn_failed',
  'escalated',
  'unavailable',
  'disabled',
};

/// Decide what the status bar should show. Inputs mirror exactly the signals the
/// screen already reads from `run_status` / `state`; branch order is significant.
StatusBanner statusBanner({
  required String runSt,
  required bool awaiting,
  required bool agentActive,
  required bool isRunning,
  required bool done,
  required bool longRun,
  required int phase,
  int? elapsed,
  String? error,
  String judgeVerdict = 'revise',
  String stepLabel = '',
  bool ideMode = false,
  String? ideHint,
  String featureId = '',
}) {
  if (awaiting && agentActive) {
    return const StatusBanner(
      BannerKind.running,
      'Applying your message',
      'Your note is saved in requirement.md. Agent is updating specs — send '
          'again to replace, or Cancel run.',
    );
  }
  if (isRunning) {
    return StatusBanner(BannerKind.running, 'Running', 'Step: $stepLabel');
  }
  if (awaiting) {
    final v = judgeVerdict.toLowerCase();
    if (v == 'pass') {
      return const StatusBanner(BannerKind.awaiting, 'Ready to approve',
          'Judge verdict: PASS — review and approve to continue');
    }
    return StatusBanner(BannerKind.error, 'Revision required',
        'Verdict: ${v.toUpperCase()} — clarify requirement and redo specs');
  }
  if (runSt == 'needs_login' || runSt == 'error') {
    return StatusBanner(
      BannerKind.error,
      runSt == 'needs_login' ? 'Login required' : 'Error',
      error ?? 'Check runner setup',
    );
  }
  if (runSt == 'blocked') {
    return const StatusBanner(
      BannerKind.error,
      'Build stopped',
      'The builder could not finish after several tries. Tap "Reset & retry" '
          'to start the build over.',
    );
  }
  if (ideMode) {
    return StatusBanner(
      BannerKind.awaiting,
      'IDE mode',
      ideHint ??
          'Run `@orch-orchestrator resume $featureId` in Cursor IDE, then Sync.',
    );
  }
  if (runSt == 'running' || runSt == 'queued') {
    if (longRun) {
      return StatusBanner(
        BannerKind.running,
        phase >= 7
            ? 'Still building — ${elapsed}s elapsed'
            : 'Still working — ${elapsed}s elapsed',
        'This is taking longer than usual. You can keep waiting, or Cancel and '
            'tap Reset & retry to start over.',
      );
    }
    return StatusBanner(
      BannerKind.running,
      phase >= 7 ? 'Building your app…' : 'Working… (step $phase of 9)',
      phase >= 7
          ? 'Writing the code and running the tests. This usually takes about a '
              'minute.'
          : 'Generating the spec, plan, and tests (a few seconds).',
    );
  }
  if (_failedStatuses.contains(runSt)) {
    // Previously fell through to a blank bar — a build that never started must
    // never look like nothing happened.
    return StatusBanner(
      BannerKind.error,
      'Build did not start',
      error ?? 'The builder reported "$runSt". Tap "Reset & retry" to try again.',
    );
  }
  if (done) {
    return const StatusBanner(
      BannerKind.success,
      'Complete',
      'All phases passed and the Proof of Build is sealed. Send a change to '
          'iterate, or open the artifacts to review.',
    );
  }
  if (phase == 0) {
    return const StatusBanner(
      BannerKind.running, 'Ready', 'Start the pipeline when agent is ready');
  }
  // Catch-all: never a blank bar. Surface whatever state we're in so the user is
  // never left staring at nothing (e.g. an unrecognised runner status).
  return StatusBanner(
    BannerKind.awaiting,
    'Needs attention',
    error ??
        'Status: "$runSt" at phase $phase. Tap "Reset & retry" if this looks '
            'stuck.',
  );
}

/// Non-empty blocker strings from an autopilot/crew summary (`blockers` list).
/// Defensive: a missing or malformed value yields an empty list, never a crash.
List<String> blockersOf(Map<String, dynamic> summary) {
  final raw = summary['blockers'];
  if (raw is! List) return const [];
  return raw.map((b) => '$b'.trim()).where((s) => s.isNotEmpty).toList();
}

/// The user-facing one-line outcome of an autopilot run. A blocked run is NEVER
/// reported as a celebratory success — it names the blocker instead.
String autopilotOutcomeMessage(Map<String, dynamic> summary) {
  final phases = (summary['phases_completed'] as List?)?.join(', ') ?? '';
  final reason = summary['stop_reason'] as String? ?? '';
  final blockers = blockersOf(summary);
  final agents = (summary['agents'] as List?)?.length ?? 0;
  final ms = summary['duration_ms'] ?? '?';
  if (reason == 'blocked' || blockers.isNotEmpty) {
    return 'Autopilot blocked: ${blockers.isNotEmpty ? blockers.first : reason}'
        '${phases.isEmpty ? '' : ' (completed $phases first)'}';
  }
  if (phases.isEmpty) return 'Autopilot: nothing to do ($reason)';
  return 'Crew of $agents subagents completed phases $phases in ${ms}ms '
      '(zero tokens) — $reason';
}
