import 'package:flutter/material.dart';

import '../models/trace_span.dart';
import '../theme/orchestration_colors.dart';

/// Visual tone for a live activity card. Kept separate + pure so the honesty rule
/// is unit-testable.
enum ActivityTone { positive, negative, warn, sealed, active, neutral }

/// Pure cardKind → tone. HONESTY: a tone is `positive` or `sealed` ONLY for kinds
/// the runner emits after a REAL success (VERIFY_OK / POLICY_OK / DONE_OK / SEAL).
/// Failure/blocked kinds are `negative`; in-progress kinds are `active`; the rest
/// are `neutral`. A missing/false ok never reaches a positive kind (see
/// TraceSpan.cardKind), so a green/sealed card can never be shown on an unverified
/// or policy-blocked build.
ActivityTone activityTone(String cardKind) {
  switch (cardKind) {
    case 'VERIFY_OK':
    case 'POLICY_OK':
    case 'DONE_OK':
    case 'MOBILE_OK':
    case 'PROCESS_OK':
      return ActivityTone.positive;
    case 'SEAL':
      return ActivityTone.sealed;
    case 'VERIFY_FAIL':
    case 'DONE_FAIL':
    case 'BLOCKED':
      return ActivityTone.negative;
    case 'POLICY_WARN':
    case 'MOBILE_FAIL':
    case 'PROCESS_WARN':
      return ActivityTone.warn;
    case 'VERIFY_RUN':
    case 'GENERATE':
    case 'SCAFFOLD':
    case 'DEPS':
    case 'SEALING':
    case 'HEAL':
    case 'MOBILE_RUN':
    case 'PROCESS_RUN':
      return ActivityTone.active;
    default:
      return ActivityTone.neutral;
  }
}

IconData activityIcon(String cardKind) {
  switch (cardKind) {
    case 'VERIFY_OK':
      return Icons.check_circle;
    case 'VERIFY_FAIL':
      return Icons.cancel;
    case 'VERIFY_RUN':
      return Icons.sync;
    case 'POLICY_OK':
      return Icons.verified_user;
    case 'POLICY_WARN':
      return Icons.gpp_maybe;
    case 'BLOCKED':
      return Icons.block;
    case 'SEALING':
      return Icons.lock_clock;
    case 'SEAL':
      return Icons.lock;
    case 'GENERATE':
      return Icons.auto_awesome;
    case 'SCAFFOLD':
      return Icons.dashboard_customize;
    case 'DEPS':
      return Icons.inventory_2;
    case 'FILE_WRITE':
      return Icons.description;
    case 'HEAL':
      return Icons.healing;
    case 'AUDIT':
      return Icons.fact_check;
    case 'DONE_OK':
      return Icons.task_alt;
    case 'DONE_FAIL':
      return Icons.report;
    case 'MOBILE_RUN':
      return Icons.adb;
    case 'MOBILE_OK':
      return Icons.phone_android;
    case 'MOBILE_FAIL':
      return Icons.mobile_off;
    case 'PROCESS_OK':
      return Icons.verified;
    case 'PROCESS_WARN':
      return Icons.rule;
    case 'PROCESS_RUN':
      return Icons.science;
    default:
      return Icons.chevron_right;
  }
}

Color toneColor(ActivityTone tone, OrchStatusColors s) {
  switch (tone) {
    case ActivityTone.positive:
    case ActivityTone.sealed:
      return s.success;
    case ActivityTone.negative:
      return s.error;
    case ActivityTone.warn:
      return s.awaiting;
    case ActivityTone.active:
      return s.running;
    case ActivityTone.neutral:
      return s.idle;
  }
}

Color toneBg(ActivityTone tone, OrchStatusColors s) {
  switch (tone) {
    case ActivityTone.positive:
    case ActivityTone.sealed:
      return s.successBg;
    case ActivityTone.negative:
      return s.errorBg;
    case ActivityTone.warn:
      return s.awaitingBg;
    case ActivityTone.active:
      return s.runningBg;
    case ActivityTone.neutral:
      return s.idleBg;
  }
}

/// One typed live-activity card (verify pill, file chip, seal chip, …).
class ActivityCard extends StatelessWidget {
  const ActivityCard({super.key, required this.span});

  final TraceSpan span;

  @override
  Widget build(BuildContext context) {
    final status = context.orchStatus;
    final kind = span.cardKind;
    final tone = activityTone(kind);
    final color = toneColor(tone, status);
    final bg = toneBg(tone, status);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withValues(alpha: 0.4)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(activityIcon(kind), size: 16, color: color),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                span.body,
                style: TextStyle(fontSize: 12.5, color: color, height: 1.3),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The vertical list of live activity cards (runner narration as it streams).
class LiveActivityList extends StatelessWidget {
  const LiveActivityList({super.key, required this.spans});

  final List<TraceSpan> spans;

  @override
  Widget build(BuildContext context) {
    if (spans.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [for (final s in spans) ActivityCard(span: s)],
    );
  }
}
