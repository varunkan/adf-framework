import 'dart:io';

import 'feature_store.dart';

/// After a headless agent run, sync state.json from artifacts on disk.
class RunPostSync {
  RunPostSync(this.store, {bool? crewEnabled})
      : crewEnabled = crewEnabled ??
            (Platform.environment['ADF_REQUIREMENTS_CREW'] == '1');

  final FeatureStore store;

  /// When the requirements CREW is enabled the PO verdict is REAL (the crew writes
  /// it), so we must NOT fabricate "completed reviewers" as a fallback — that faked a
  /// passing PO review, the exact dishonesty this replaces (P2).
  final bool crewEnabled;

  static const int _backfillMaxChars = 8000;

  /// The reviewers to record for a phase when none are in state yet:
  ///  - real reviewers parsed from the verdict, if any;
  ///  - else the legacy canonical pair ONLY when the crew is OFF (back-compat);
  ///  - else null when the crew is ON — never fabricate a passing PO review (P2).
  /// Pure + static → unit-testable without the state-pruning machinery.
  static List<String>? resolveReviewers({
    required List<String>? fromVerdict,
    required bool crewEnabled,
  }) {
    if (fromVerdict != null && fromVerdict.isNotEmpty) return fromVerdict;
    if (!crewEnabled) {
      return const ['bmad-agent-analyst', 'bmad-review-adversarial-general'];
    }
    return null;
  }

  /// Returns true if state was updated to awaiting approval.
  bool syncAfterRun(String featureId, int phase) {
    backfillLastAgentResponse(featureId, phase);

    final state = store.readState(featureId);
    var changed = false;

    final verdictPath =
        store.paths.featureRel(featureId, 'judge-verdicts/phase-$phase.md');
    final verdictFile = File('${store.repoRoot}/$verdictPath');
    String? verdictWord;

    if (verdictFile.existsSync()) {
      final md = verdictFile.readAsStringSync();
      verdictWord = store.parseJudgeVerdict(md);
      if (verdictWord != null) {
        state['last_judge_verdict'] = verdictWord;
        changed = true;
      }
    }

    if (phase == 1 &&
        store.artifactExists(
            store.paths.featureRel(featureId, '00-intake.md'))) {
      final builders = Map<String, dynamic>.from(
        state['completed_builders'] as Map<String, dynamic>? ?? {},
      );
      final list = (builders['$phase'] as List<dynamic>?)?.toList() ?? [];
      if (!list.contains('orch-product-analyst')) {
        list.add('orch-product-analyst');
        builders['$phase'] = list;
        state['completed_builders'] = builders;
        changed = true;
      }
    }

    if (verdictFile.existsSync()) {
      final reviewers = Map<String, dynamic>.from(
        state['completed_reviewers'] as Map<String, dynamic>? ?? {},
      );
      final rlist = (reviewers['$phase'] as List<dynamic>?)?.toList() ?? [];
      if (rlist.isEmpty) {
        final resolved = resolveReviewers(
          fromVerdict: store.parseReviewerSkills(verdictFile.readAsStringSync()),
          crewEnabled: crewEnabled,
        );
        if (resolved != null) {
          reviewers['$phase'] = resolved;
          state['completed_reviewers'] = reviewers;
          changed = true;
        }
      }
    }

    final current = (state['current_phase'] as num?)?.toInt() ?? 0;
    if (current < phase) {
      state['current_phase'] = phase;
      changed = true;
    }

    // Auto-flow (the user's chosen default): record the verdict for transparency
    // but DO NOT pause for approval at every phase — that was the confirm/revise
    // nag. The artifacts remain viewable; the pipeline advances on its own. Only
    // when auto-approve is OFF do we gate the phase on a human.
    final autoFlow = FeatureStore.autoApprove(state);
    if (verdictWord != null || verdictFile.existsSync()) {
      state['pending_approval_phase'] = phase;
      if (!autoFlow) {
        state['awaiting_user'] = true;
      }
      changed = true;
    } else if (store.artifactExists(
        store.paths.featureRel(featureId, '00-intake.md'))) {
      state['pending_approval_phase'] = phase;
      state['last_judge_verdict'] ??= 'pending';
      if (!autoFlow) {
        state['awaiting_user'] = true;
      }
      changed = true;
    }

    if (changed) {
      store.writeState(featureId, state);
    }
    return state['awaiting_user'] == true;
  }

  /// Backfill last-agent-response.md from verdict or intake when missing.
  void backfillLastAgentResponse(String featureId, int phase) {
    final existing = store.readLastAgentResponse(featureId);
    if (existing != null && existing.isNotEmpty) return;

    final verdictPath =
        store.paths.featureRel(featureId, 'judge-verdicts/phase-$phase.md');
    final verdictFile = File('${store.repoRoot}/$verdictPath');
    if (verdictFile.existsSync()) {
      final md = verdictFile.readAsStringSync();
      final combined = store.parseCombinedRecommendation(md);
      final body = combined != null && combined.isNotEmpty
          ? '## Judge feedback (combined recommendation)\n\n$combined'
          : md;
      store.writeLastAgentResponse(
        featureId,
        _truncate(body, _backfillMaxChars),
      );
      return;
    }

    final intakePath =
        store.paths.featureRel(featureId, '00-intake.md');
    final intakeFile = File('${store.repoRoot}/$intakePath');
    if (intakeFile.existsSync()) {
      final md = intakeFile.readAsStringSync();
      store.writeLastAgentResponse(
        featureId,
        _truncate(md, _backfillMaxChars),
      );
    }
  }

  String _truncate(String s, int max) {
    if (s.length <= max) return s;
    return '${s.substring(0, max)}\n\n… (truncated)';
  }
}
