import 'package:flutter/material.dart';

import '../models/trace_span.dart';
import '../theme/orchestration_colors.dart';

/// Single step in the agent chain-of-thought timeline (Cursor-style).
class ThoughtChainTile extends StatelessWidget {
  const ThoughtChainTile({
    super.key,
    required this.span,
    this.showConnector = true,
  });

  final TraceSpan span;
  final bool showConnector;

  static Color kindColor(String kind, OrchStatusColors status) {
    switch (kind) {
      case 'REASONING':
        return Colors.deepPurple;
      case 'TOOL':
        return Colors.blue;
      case 'SUBAGENT':
        return Colors.teal;
      case 'RESPONSE':
        return Colors.blueGrey;
      case 'SESSION':
        return Colors.orange;
      default:
        return status.idle;
    }
  }

  static IconData kindIcon(String kind) {
    switch (kind) {
      case 'REASONING':
        return Icons.psychology_outlined;
      case 'TOOL':
        return Icons.build_outlined;
      case 'SUBAGENT':
        return Icons.hub_outlined;
      case 'RESPONSE':
        return Icons.chat_bubble_outline;
      default:
        return Icons.radio_button_checked;
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = context.orchStatus;
    final kind = span.displayKind;
    final color = kindColor(kind, status);

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              width: 28,
              child: Column(
                children: [
                  Icon(kindIcon(kind), size: 16, color: color),
                  if (showConnector)
                    Expanded(
                      child: Container(
                        width: 2,
                        margin: const EdgeInsets.symmetric(vertical: 4),
                        color: color.withValues(alpha: 0.25),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Container(
                margin: const EdgeInsets.only(bottom: 4),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.06),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: color.withValues(alpha: 0.2)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 6,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: color,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            kind,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 9,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          span.shortTime,
                          style: TextStyle(
                            fontSize: 10,
                            color: Colors.grey.shade600,
                          ),
                        ),
                        if (span.status == 'ERROR')
                          const Padding(
                            padding: EdgeInsets.only(left: 6),
                            child: Icon(
                              Icons.error_outline,
                              size: 14,
                              color: Colors.red,
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    SelectableText(
                      span.body,
                      style: const TextStyle(fontSize: 13, height: 1.4),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
