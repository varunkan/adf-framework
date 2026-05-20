import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../services/api_client.dart';
import '../theme/orchestration_colors.dart';
import 'agent_thought_stream.dart';
import 'artifact_checklist_panel.dart';
import 'gates_panel.dart';
import 'phase_step_list.dart';
import 'runner_setup_card.dart';

class FeatureInspector extends StatelessWidget {
  const FeatureInspector({
    super.key,
    required this.api,
    required this.featureId,
    required this.requirement,
    required this.gates,
    this.verdict,
    this.combinedRecommendation,
    this.runnerHealth,
    this.phases = const [],
    this.expandedPhase = 1,
    this.currentStepId,
    this.traceCount = 0,
    this.isRunning = false,
    this.onVerifyRunner,
    this.onRetryRunner,
    this.onStepCommand,
    this.onSyncState,
    this.artifactChecklist,
  });

  final ApiClient api;
  final String featureId;
  final String requirement;
  final Map<String, dynamic> gates;
  final String? verdict;
  final String? combinedRecommendation;
  final Map<String, dynamic>? runnerHealth;
  final List<Map<String, dynamic>> phases;
  final int expandedPhase;
  final String? currentStepId;
  final int traceCount;
  final bool isRunning;
  final VoidCallback? onVerifyRunner;
  final VoidCallback? onRetryRunner;
  final Future<void> Function(String stepId, String cmd)? onStepCommand;
  final Future<void> Function()? onSyncState;
  final Map<String, dynamic>? artifactChecklist;

  @override
  Widget build(BuildContext context) {
    final spacing = context.orchSpacing;
    final scheme = Theme.of(context).colorScheme;

    return ListView(
      padding: EdgeInsets.all(spacing.lg),
      children: [
        if (runnerHealth != null)
          RunnerSetupCard(
            health: runnerHealth!,
            onVerify: onVerifyRunner ?? () {},
            onRetry: onRetryRunner,
          ),
        SizedBox(height: spacing.md),
        Text(
          'Requirement',
          style: Theme.of(context).textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
        SizedBox(height: spacing.sm),
        Container(
          padding: EdgeInsets.all(spacing.md),
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(context.orchRadii.card),
          ),
          child: Text(
            requirement.isEmpty ? 'No requirement text.' : requirement,
            style: const TextStyle(fontSize: 13, height: 1.45),
          ),
        ),
        SizedBox(height: spacing.lg),
        GatesPanel(gates: gates),
        if (artifactChecklist != null) ...[
          SizedBox(height: spacing.lg),
          ArtifactChecklistPanel(
            checklist: artifactChecklist!,
            onOpenAdfGuide: () {
              showDialog<void>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: const Text('ADF v3 guide'),
                  content: const SingleChildScrollView(
                    child: Text(
                      'Read .cursor/orchestration/ADF.md and adf-grok-refinement.md.\n\n'
                      'Before approve on phases 2–4, run:\n'
                      './scripts/orch/validate_adf_artifacts.sh <feature-id> --phase <N>',
                    ),
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text('Close'),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
        if (phases.isNotEmpty && onStepCommand != null) ...[
          SizedBox(height: spacing.lg),
          PhaseStepList(
            phases: phases,
            expandedPhase: expandedPhase,
            currentStepId: currentStepId,
            onStepCommand: onStepCommand!,
          ),
        ],
        if (combinedRecommendation != null &&
            combinedRecommendation!.trim().isNotEmpty) ...[
          SizedBox(height: spacing.lg),
          Text(
            'Combined recommendation',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
          SizedBox(height: spacing.sm),
          Container(
            padding: EdgeInsets.all(spacing.md),
            decoration: BoxDecoration(
              color: context.orchStatus.awaitingBg,
              borderRadius: BorderRadius.circular(context.orchRadii.card),
              border: Border.all(
                color: context.orchStatus.awaiting.withValues(alpha: 0.3),
              ),
            ),
            child: MarkdownBody(
              data: combinedRecommendation!,
              selectable: true,
              styleSheet: MarkdownStyleSheet(
                p: const TextStyle(fontSize: 13, height: 1.4),
              ),
            ),
          ),
        ],
        if (verdict != null && verdict!.isNotEmpty) ...[
          SizedBox(height: spacing.lg),
          Text(
            'Full judge verdict',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
          SizedBox(height: spacing.sm),
          Container(
            padding: EdgeInsets.all(spacing.md),
            decoration: BoxDecoration(
              color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
              borderRadius: BorderRadius.circular(context.orchRadii.card),
            ),
            child: MarkdownBody(
              data: verdict!.length > 6000
                  ? '${verdict!.substring(0, 6000)}\n\n…'
                  : verdict!,
              selectable: true,
              styleSheet: MarkdownStyleSheet(
                p: const TextStyle(fontSize: 13, height: 1.4),
              ),
            ),
          ),
        ],
        if (onSyncState != null) ...[
          SizedBox(height: spacing.md),
          OutlinedButton.icon(
            onPressed: onSyncState,
            icon: const Icon(Icons.sync, size: 18),
            label: const Text('Sync from artifacts'),
          ),
        ],
        SizedBox(height: spacing.lg),
        ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: const Text('Technical event log'),
          subtitle: Text('$traceCount raw OTEL events'),
          children: [
            AgentThoughtStream(
              api: api,
              featureId: featureId,
              pollInterval: const Duration(milliseconds: 800),
              maxHeight: 240,
              enableLivePoll: isRunning,
              emptyHint: isRunning ? 'Agent running…' : 'Paused — tap refresh',
            ),
          ],
        ),
      ],
    );
  }
}
