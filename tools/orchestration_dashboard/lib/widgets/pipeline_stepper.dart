import 'package:flutter/material.dart';

class PipelineStepper extends StatelessWidget {
  const PipelineStepper({
    super.key,
    required this.phases,
    required this.currentPhase,
    this.onPhaseTap,
  });

  final List<Map<String, dynamic>> phases;
  final int currentPhase;
  final void Function(int phase)? onPhaseTap;

  @override
  Widget build(BuildContext context) {
    final pipelinePhases = phases.where((p) {
      final n = (p['phase'] as num?)?.toInt() ?? -1;
      return n >= 0 && n <= 9;
    }).toList();

    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Text(
                'Pipeline',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            const SizedBox(height: 8),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (var i = 0; i < pipelinePhases.length; i++) ...[
                    if (i > 0)
                      SizedBox(
                        width: 24,
                        child: Divider(
                          color: _connectorColor(pipelinePhases[i - 1]),
                        ),
                      ),
                    _PhaseChip(
                      phase: pipelinePhases[i],
                      isCurrent: (pipelinePhases[i]['phase'] as num?)?.toInt() ==
                          currentPhase,
                      onTap: onPhaseTap == null
                          ? null
                          : () => onPhaseTap!(
                                (pipelinePhases[i]['phase'] as num).toInt(),
                              ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Color? _connectorColor(Map<String, dynamic> prev) {
    if (prev['gate_met'] == true) return Colors.green;
    return Colors.grey.shade400;
  }
}

class _PhaseChip extends StatelessWidget {
  const _PhaseChip({
    required this.phase,
    required this.isCurrent,
    this.onTap,
  });

  final Map<String, dynamic> phase;
  final bool isCurrent;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final n = (phase['phase'] as num?)?.toInt() ?? 0;
    final name = phase['name'] as String? ?? 'P$n';
    final status = phase['status'] as String? ?? 'pending';
    final gateMet = phase['gate_met'] == true;

    Color bg;
    IconData icon;
    if (gateMet) {
      bg = Colors.green.shade100;
      icon = Icons.check_circle;
    } else if (isCurrent || status == 'active') {
      bg = Colors.blue.shade100;
      icon = Icons.play_circle;
    } else if (status == 'done') {
      bg = Colors.green.shade50;
      icon = Icons.check;
    } else {
      bg = Colors.grey.shade200;
      icon = Icons.circle_outlined;
    }

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        width: 72,
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(8),
          border: isCurrent
              ? Border.all(color: Colors.blue.shade700, width: 2)
              : null,
        ),
        child: Column(
          children: [
            Icon(icon, size: 20),
            const SizedBox(height: 4),
            Text(
              '$n',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
            ),
            Text(
              name,
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 9),
            ),
          ],
        ),
      ),
    );
  }
}
