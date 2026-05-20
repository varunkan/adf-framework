import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../theme/orchestration_colors.dart';

class ApprovalActionBar extends StatefulWidget {
  const ApprovalActionBar({
    super.key,
    required this.phase,
    required this.verdict,
    required this.onApprove,
    required this.onClarifyAndRedo,
    required this.onReject,
    this.combinedRecommendation,
    this.artifactPass = true,
  });

  final int phase;
  final String verdict;
  final String? combinedRecommendation;
  final bool artifactPass;
  final Future<void> Function(String decision, {String notes}) onApprove;
  final Future<void> Function(String notes, {required bool clientConfirmed})
      onClarifyAndRedo;
  final Future<void> Function(String decision, {String notes}) onReject;

  bool get canApprove =>
      verdict.toLowerCase() == 'pass' && artifactPass;

  @override
  State<ApprovalActionBar> createState() => _ApprovalActionBarState();
}

class _ApprovalActionBarState extends State<ApprovalActionBar> {
  final _notesController = TextEditingController();
  bool _busy = false;
  bool _clientConfirmed = false;

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _act(Future<void> Function() fn) async {
    setState(() => _busy = true);
    try {
      await fn();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String get _guidance {
    switch (widget.verdict.toLowerCase()) {
      case 'fail':
        return 'Judge FAIL — review the combined recommendation below, confirm direction '
            'with the client, then authorize the orchestrator to fix requirement, plan, and specs.';
      case 'pending':
        return 'Review pending — use the combined recommendation as the feedback loop. '
            'Confirm with the client before re-running the phase.';
      default:
        return 'Verdict REVISE — the combined recommendation is the authoritative feedback. '
            'Confirm with the client, then the orchestrator will update requirement.md, '
            'specs plan, and phase artifacts until review PASS.';
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = context.orchStatus;
    final spacing = context.orchSpacing;
    final scheme = Theme.of(context).colorScheme;
    final canApprove = widget.canApprove;
    final artifactBlocked = !widget.artifactPass && widget.verdict.toLowerCase() == 'pass';
    final combined = widget.combinedRecommendation?.trim() ?? '';

    return Material(
      color: canApprove ? status.awaitingBg : status.errorBg,
      child: Padding(
        padding: EdgeInsets.all(spacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Icon(
                  canApprove ? Icons.how_to_reg : Icons.rate_review_outlined,
                  color: canApprove ? status.awaiting : status.error,
                  size: 22,
                ),
                SizedBox(width: spacing.sm),
                Expanded(
                  child: Text(
                    artifactBlocked
                        ? 'ADF validator blocked — Phase ${widget.phase}'
                        : canApprove
                            ? 'Ready to approve — Phase ${widget.phase}'
                            : 'Client confirmation required — Phase ${widget.phase}',
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                          color: canApprove ? status.awaiting : status.error,
                        ),
                  ),
                ),
                Chip(
                  label: Text(
                    widget.verdict.toUpperCase(),
                    style: const TextStyle(fontSize: 11, fontWeight: FontWeight.bold),
                  ),
                  backgroundColor: scheme.surface,
                  side: BorderSide(
                    color: (canApprove ? status.awaiting : status.error)
                        .withValues(alpha: 0.5),
                  ),
                  visualDensity: VisualDensity.compact,
                ),
              ],
            ),
            if (!canApprove) ...[
              SizedBox(height: spacing.md),
              Text(
                _guidance,
                style: TextStyle(
                  fontSize: 13,
                  height: 1.4,
                  color: scheme.onSurface,
                ),
              ),
              if (combined.isNotEmpty) ...[
                SizedBox(height: spacing.md),
                Text(
                  'Combined recommendation (feedback loop)',
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
                SizedBox(height: spacing.sm),
                Container(
                  constraints: const BoxConstraints(maxHeight: 160),
                  padding: EdgeInsets.all(spacing.md),
                  decoration: BoxDecoration(
                    color: scheme.surface,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: scheme.outlineVariant),
                  ),
                  child: SingleChildScrollView(
                    child: MarkdownBody(
                      data: combined,
                      selectable: true,
                      styleSheet: MarkdownStyleSheet(
                        p: const TextStyle(fontSize: 13, height: 1.4),
                      ),
                    ),
                  ),
                ),
              ],
              SizedBox(height: spacing.md),
              CheckboxListTile(
                value: _clientConfirmed,
                onChanged: _busy
                    ? null
                    : (v) => setState(() => _clientConfirmed = v ?? false),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: const Text(
                  'Client confirms: apply combined recommendation and fix '
                  'requirement, plan (specs), and phase artifacts',
                  style: TextStyle(fontSize: 13),
                ),
              ),
            ],
            SizedBox(height: spacing.sm),
            TextField(
              controller: _notesController,
              enabled: !_busy,
              maxLines: canApprove ? 2 : 3,
              decoration: InputDecoration(
                labelText: canApprove
                    ? 'Notes (optional)'
                    : 'Additional client notes (optional)',
                hintText: canApprove
                    ? 'Feedback when approving…'
                    : 'Scope decisions, answers to judge questions…',
                isDense: true,
              ),
            ),
            SizedBox(height: spacing.md),
            Wrap(
              spacing: spacing.sm,
              runSpacing: spacing.sm,
              children: [
                if (canApprove)
                  FilledButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _act(() => widget.onApprove(
                              'approved',
                              notes: _notesController.text.trim(),
                            )),
                    icon: const Icon(Icons.check_circle_outline, size: 18),
                    label: const Text('Approve phase'),
                  )
                else
                  FilledButton.icon(
                    onPressed: _busy || !_clientConfirmed
                        ? null
                        : () => _act(() => widget.onClarifyAndRedo(
                              _notesController.text.trim(),
                              clientConfirmed: _clientConfirmed,
                            )),
                    icon: const Icon(Icons.edit_note, size: 18),
                    label: const Text('Confirm & redo with feedback'),
                  ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () => _act(() => widget.onReject(
                            'rejected',
                            notes: _notesController.text.trim(),
                          )),
                  child: const Text('Reject feature'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
