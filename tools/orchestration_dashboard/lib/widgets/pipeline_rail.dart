import 'package:flutter/material.dart';

import '../theme/orchestration_colors.dart';

/// Compact vertical pipeline stepper for the left rail.
class PipelineRail extends StatelessWidget {
  const PipelineRail({
    super.key,
    required this.phases,
    required this.currentPhase,
    required this.selectedPhase,
    this.onPhaseTap,
    this.currentStepId,
  });

  final List<Map<String, dynamic>> phases;
  final int currentPhase;
  final int selectedPhase;
  final void Function(int phase)? onPhaseTap;
  final String? currentStepId;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final status = context.orchStatus;
    final spacing = context.orchSpacing;

    final pipelinePhases = phases.where((p) {
      final n = (p['phase'] as num?)?.toInt() ?? -1;
      return n >= 0 && n <= 9;
    }).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: EdgeInsets.fromLTRB(spacing.lg, spacing.lg, spacing.lg, spacing.sm),
          child: Text(
            'Pipeline',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
        ),
        if (currentStepId != null)
          Padding(
            padding: EdgeInsets.symmetric(horizontal: spacing.lg),
            child: Text(
              currentStepId!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        SizedBox(height: spacing.sm),
        Expanded(
          child: ListView.builder(
            padding: EdgeInsets.symmetric(horizontal: spacing.sm),
            itemCount: pipelinePhases.length,
            itemBuilder: (context, index) {
              final ph = pipelinePhases[index];
              final n = (ph['phase'] as num).toInt();
              final label = (ph['name'] as String?) ??
                  (ph['label'] as String?) ??
                  'Phase $n';
              final phStatus = ph['status'] as String? ?? 'pending';
              final gateMet = ph['gate_met'] == true;
              final isComplete = gateMet ||
                  phStatus == 'done' ||
                  phStatus == 'complete' ||
                  phStatus == 'passed';
              final isCurrent = !isComplete &&
                  (phStatus == 'active' ||
                      phStatus == 'running' ||
                      n == currentPhase);
              final isSelected = n == selectedPhase;

              Color dotColor;
              if (isComplete) {
                dotColor = status.success;
              } else if (isCurrent) {
                dotColor = status.running;
              } else {
                dotColor = status.idle;
              }

              return InkWell(
                onTap: onPhaseTap == null ? null : () => onPhaseTap!(n),
                borderRadius: BorderRadius.circular(8),
                child: Container(
                  margin: EdgeInsets.symmetric(vertical: spacing.xs),
                  padding: EdgeInsets.symmetric(
                    horizontal: spacing.md,
                    vertical: spacing.sm,
                  ),
                  decoration: BoxDecoration(
                    color: isSelected
                        ? scheme.primaryContainer.withValues(alpha: 0.5)
                        : null,
                    borderRadius: BorderRadius.circular(8),
                    border: isSelected
                        ? Border.all(color: scheme.primary.withValues(alpha: 0.4))
                        : null,
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 28,
                        height: 28,
                        decoration: BoxDecoration(
                          color: dotColor.withValues(alpha: 0.15),
                          shape: BoxShape.circle,
                          border: Border.all(color: dotColor, width: 2),
                        ),
                        alignment: Alignment.center,
                        child: Text(
                          '$n',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.bold,
                            color: dotColor,
                          ),
                        ),
                      ),
                      SizedBox(width: spacing.sm),
                      Expanded(
                        child: Text(
                          label,
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: isCurrent ? FontWeight.w600 : FontWeight.normal,
                          ),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}
