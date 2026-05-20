import 'dart:io';

import 'feature_store.dart';

/// After headless cursor-agent run, sync state.json from artifacts on disk.
class RunPostSync {
  RunPostSync(this.store);

  final FeatureStore store;

  static const int _backfillMaxChars = 8000;

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
        final fromVerdict =
            store.parseReviewerSkills(verdictFile.readAsStringSync());
        reviewers['$phase'] = fromVerdict != null && fromVerdict.isNotEmpty
            ? fromVerdict
            : [
                'bmad-agent-analyst',
                'bmad-review-adversarial-general',
              ];
        state['completed_reviewers'] = reviewers;
        changed = true;
      }
    }

    final current = (state['current_phase'] as num?)?.toInt() ?? 0;
    if (current < phase) {
      state['current_phase'] = phase;
      changed = true;
    }

    if (verdictWord != null || verdictFile.existsSync()) {
      state['pending_approval_phase'] = phase;
      state['awaiting_user'] = true;
      changed = true;
    } else if (store.artifactExists(
        store.paths.featureRel(featureId, '00-intake.md'))) {
      state['pending_approval_phase'] = phase;
      state['awaiting_user'] = true;
      state['last_judge_verdict'] ??= 'pending';
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
