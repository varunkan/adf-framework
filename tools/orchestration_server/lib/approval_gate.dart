import 'feature_store.dart';

/// The proof-governance approval gate, extracted from the `/approve` route so the
/// enforcement core is unit-testable (P0-5). The HTTP handler shells these: it
/// parses the request, runs the async artifact-validator check, then delegates the
/// decision allowlist, the verdict/revise gates, and the state transition here.

/// The only decisions the gate accepts. An unknown decision must be rejected
/// (HTTP 400) — never silently no-op the gate and return 200, which would let an
/// unenforced phase slip through.
const approvalDecisions = {'approved', 'revise', 'rejected'};

bool isValidDecision(String decision) => approvalDecisions.contains(decision);

/// The outcome of the pre-transition gate check: either allowed, or blocked with
/// the HTTP status + reason the route should return.
class GateCheck {
  const GateCheck.ok()
      : blocked = false,
        status = 200,
        reason = null;
  const GateCheck.blockedWith(this.status, this.reason) : blocked = true;

  final bool blocked;
  final int status;
  final String? reason;
}

/// Enforce the approval preconditions that don't require I/O:
///   - approving a phase whose judge verdict isn't `pass` is blocked (409) unless
///     `judgeWaiver` explicitly overrides it;
///   - a `revise` decision requires `clientConfirmed` (400) so a revise can't be
///     issued before the user has seen the combined recommendation.
/// (The phases 2–4 artifact-validator check stays in the route — it's async and
/// returns its checklist payload — but its waiver semantics mirror these.)
GateCheck checkApprovalGate({
  required String decision,
  required String? verdict,
  required bool judgeWaiver,
  required bool clientConfirmed,
}) {
  if (decision == 'approved' && verdict != 'pass' && !judgeWaiver) {
    return GateCheck.blockedWith(
      409,
      'Cannot approve: BMAD verdict is not pass (current: $verdict). '
      'Use judge_waiver: true to override.',
    );
  }
  if (decision == 'revise' && !clientConfirmed) {
    return const GateCheck.blockedWith(
      400,
      'Client confirmation required before revise. Set client_confirmed: true '
      'after reviewing combined recommendation.',
    );
  }
  return const GateCheck.ok();
}

/// Apply a validated decision to `state` (mutating it; the caller persists). The
/// decision is assumed already allowlisted and gate-checked. Returns whether the
/// approval should be sealed into the proof chain (only a genuine `approved`).
///
///   approved → mark the phase gate passed, clear the awaiting/pending flags, and
///              either advance current_phase by one, or, at the last pipeline
///              phase, pin it there and mark the feature `completed` (terminal).
///   revise   → record the pending phase, bump phase_revision_count, keep
///              awaiting_user so the approval bar stays if the follow-up fails.
///   rejected → terminal `rejected`, clear awaiting_user.
bool applyApprovalDecision(
  FeatureStore store,
  Map<String, dynamic> state,
  int phase,
  String decision,
) {
  switch (decision) {
    case 'approved':
      store.setGateForPhase(state, phase, true);
      state['awaiting_user'] = false;
      state['pending_approval_phase'] = null;
      if (phase >= FeatureStore.lastPipelinePhase) {
        state['current_phase'] = FeatureStore.lastPipelinePhase;
        state['status'] = 'completed';
      } else {
        final current = (state['current_phase'] as num?)?.toInt() ?? 0;
        if (current <= phase) state['current_phase'] = phase + 1;
      }
      return true;
    case 'revise':
      state['pending_approval_phase'] = phase;
      final rev = (state['phase_revision_count'] as num?)?.toInt() ?? 0;
      state['phase_revision_count'] = rev + 1;
      state['awaiting_user'] = true;
      return false;
    case 'rejected':
      state['status'] = 'rejected';
      state['awaiting_user'] = false;
      return false;
    default:
      return false;
  }
}
