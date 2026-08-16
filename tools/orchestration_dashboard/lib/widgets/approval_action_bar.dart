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
        return 'The AI review found issues that need fixing. Read the feedback '
            'below, then approve or request changes.';
      case 'pending':
        return 'The AI review is still forming. Read the feedback below, then '
            'approve or request changes.';
      default:
        return 'The AI review suggests some changes. Read the feedback below, '
            'then approve as-is or request changes.';
    }
  }

  Future<void> _confirmReject() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancel this build?'),
        content: const Text(
            'This stops the feature here. It cannot be undone.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Keep building')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Cancel build')),
        ],
      ),
    );
    if (ok == true) {
      await _act(() =>
          widget.onReject('rejected', notes: _notesController.text.trim()));
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
                        ? 'ADF checks blocked — Phase ${widget.phase}'
                        : canApprove
                            ? 'Phase ${widget.phase} ready for your review'
                            : 'Phase ${widget.phase} needs your decision',
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
                  'What the AI review found',
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
                  "I've reviewed the feedback — make these changes",
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
                    label: const Text('Approve'),
                  )
                else ...[
                  // One-click request-changes — no checkbox ceremony required.
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _act(() => widget.onClarifyAndRedo(
                              _notesController.text.trim(),
                              clientConfirmed: true,
                            )),
                    icon: const Icon(Icons.rate_review_outlined, size: 18),
                    label: const Text('Request changes'),
                  ),
                  // Confirmed redo (carries the reviewed-feedback acknowledgement).
                  FilledButton.icon(
                    onPressed: _busy || !_clientConfirmed
                        ? null
                        : () => _act(() => widget.onClarifyAndRedo(
                              _notesController.text.trim(),
                              clientConfirmed: _clientConfirmed,
                            )),
                    icon: const Icon(Icons.edit_note, size: 18),
                    label: const Text('Make these changes'),
                  ),
                ],
                TextButton(
                  onPressed: _busy ? null : _confirmReject,
                  child: const Text('Cancel build'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
