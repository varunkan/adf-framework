import 'package:flutter/material.dart';

import '../theme/orchestration_colors.dart';

/// ADF v3 artifact validator blockers before approve.
class ArtifactChecklistPanel extends StatelessWidget {
  const ArtifactChecklistPanel({
    super.key,
    required this.checklist,
    this.onOpenAdfGuide,
  });

  final Map<String, dynamic> checklist;
  final VoidCallback? onOpenAdfGuide;

  @override
  Widget build(BuildContext context) {
    final pass = checklist['pass'] == true;
    final blockers =
        (checklist['blockers'] as List<dynamic>?)?.cast<String>() ?? [];
    final warnings =
        (checklist['warnings'] as List<dynamic>?)?.cast<String>() ?? [];
    final artifacts = (checklist['artifacts'] as List<dynamic>?)
            ?.cast<Map<String, dynamic>>() ??
        [];
    final phase = (checklist['phase'] as num?)?.toInt();
    final status = context.orchStatus;
    final spacing = context.orchSpacing;

    return Container(
      padding: EdgeInsets.all(spacing.md),
      decoration: BoxDecoration(
        color: pass
            ? status.awaitingBg.withValues(alpha: 0.3)
            : status.errorBg,
        borderRadius: BorderRadius.circular(context.orchRadii.card),
        border: Border.all(
          color: pass
              ? status.awaiting.withValues(alpha: 0.35)
              : status.error.withValues(alpha: 0.35),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(
                pass ? Icons.check_circle_outline : Icons.error_outline,
                color: pass ? status.awaiting : status.error,
                size: 20,
              ),
              SizedBox(width: spacing.sm),
              Expanded(
                child: Text(
                  pass
                      ? 'ADF artifacts: PASS${phase != null ? ' (phase $phase)' : ''}'
                      : 'ADF artifacts: blocked${phase != null ? ' (phase $phase)' : ''}',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
              ),
              if (onOpenAdfGuide != null)
                TextButton(
                  onPressed: onOpenAdfGuide,
                  child: const Text('ADF guide'),
                ),
            ],
          ),
          if (blockers.isNotEmpty) ...[
            SizedBox(height: spacing.sm),
            ...blockers.map(
              (b) => Text('• $b', style: TextStyle(color: status.error, fontSize: 12)),
            ),
          ],
          if (warnings.isNotEmpty) ...[
            SizedBox(height: spacing.sm),
            ...warnings.map(
              (w) => Text('⚠ $w', style: const TextStyle(fontSize: 12)),
            ),
          ],
          if (artifacts.isNotEmpty) ...[
            SizedBox(height: spacing.sm),
            ...artifacts.map((a) {
              final exists = a['exists'] == true;
              final path = a['path'] as String? ?? '';
              return Text(
                '${exists ? '✓' : '✗'} $path',
                style: TextStyle(
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: exists ? null : status.error,
                ),
              );
            }),
          ],
        ],
      ),
    );
  }
}
