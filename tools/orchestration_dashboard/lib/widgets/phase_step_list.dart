import 'package:flutter/material.dart';

class PhaseStepList extends StatefulWidget {
  const PhaseStepList({
    super.key,
    required this.phases,
    required this.expandedPhase,
    this.currentStepId,
    this.onStepCommand,
  });

  final List<Map<String, dynamic>> phases;
  final int expandedPhase;
  final String? currentStepId;
  final Future<void> Function(String stepId, String command)? onStepCommand;

  @override
  State<PhaseStepList> createState() => _PhaseStepListState();
}

class _PhaseStepListState extends State<PhaseStepList> {
  late int _expanded;

  @override
  void initState() {
    super.initState();
    _expanded = widget.expandedPhase;
  }

  @override
  void didUpdateWidget(PhaseStepList oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.expandedPhase != widget.expandedPhase) {
      _expanded = widget.expandedPhase;
    }
  }

  @override
  Widget build(BuildContext context) {
    final phase = widget.phases.cast<Map<String, dynamic>?>().firstWhere(
          (p) => (p?['phase'] as num?)?.toInt() == _expanded,
          orElse: () => null,
        );
    if (phase == null) return const SizedBox.shrink();

    final steps =
        (phase['steps'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ?? [];

    return Card(
      child: ExpansionTile(
        initiallyExpanded: true,
        title: Text(
          'Phase $_expanded: ${phase['name']} steps (${steps.length})',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: phase['gate_met'] == true
            ? const Text('Gate met', style: TextStyle(color: Colors.green))
            : Text('Gate: ${phase['gate']}'),
        children: steps
            .map((s) => _StepTile(
                  step: s,
                  isCurrent: s['id'] == widget.currentStepId,
                  onRun: widget.onStepCommand == null
                      ? null
                      : () => widget.onStepCommand!(
                            s['id'] as String,
                            s['cursor_command'] as String? ?? '',
                          ),
                ))
            .toList(),
      ),
    );
  }
}

class _StepTile extends StatelessWidget {
  const _StepTile({
    required this.step,
    required this.isCurrent,
    this.onRun,
  });

  final Map<String, dynamic> step;
  final bool isCurrent;
  final VoidCallback? onRun;

  @override
  Widget build(BuildContext context) {
    final status = step['status'] as String? ?? 'pending';
    final kind = step['kind'] as String? ?? '';
    final label = step['label'] as String? ?? step['id'];
    final artifacts =
        (step['artifacts'] as List<dynamic>?)?.cast<String>() ?? [];

    IconData icon;
    Color? color;
    switch (status) {
      case 'done':
        icon = Icons.check_circle;
        color = Colors.green;
      case 'running':
        icon = Icons.autorenew;
        color = Colors.blue;
      case 'failed':
        icon = Icons.error;
        color = Colors.red;
      case 'skipped':
        icon = Icons.skip_next;
        color = Colors.grey;
      default:
        icon = Icons.radio_button_unchecked;
        color = Colors.grey;
    }

    return ListTile(
      dense: true,
      tileColor: isCurrent ? Colors.blue.shade50 : null,
      leading: Icon(icon, color: color, size: 22),
      title: Text(label, style: TextStyle(fontWeight: isCurrent ? FontWeight.bold : null)),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('$kind · $status', style: Theme.of(context).textTheme.bodySmall),
          if (artifacts.isNotEmpty)
            Text(
              'Artifacts: ${artifacts.join(', ')}',
              style: Theme.of(context).textTheme.bodySmall,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
        ],
      ),
      trailing: onRun != null && status != 'done'
          ? IconButton(
              icon: const Icon(Icons.play_arrow),
              tooltip: 'Run in Cursor',
              onPressed: onRun,
            )
          : null,
    );
  }
}
