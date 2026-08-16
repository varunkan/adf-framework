import 'package:flutter/material.dart';

/// LLM spend chip for ADF Studio header / preview rail.
///
/// Takes the `/features/<id>/cost` contract payload as-is — no fetching here.
/// Renders nothing when [cost] is null (older servers without the endpoint).
class CostBadge extends StatelessWidget {
  const CostBadge({
    super.key,
    this.cost,
    this.compact = false,
  });

  /// Contract payload: total_usd, total_input_tokens, total_output_tokens,
  /// zero_cost, runs.
  final Map<String, dynamic>? cost;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final data = cost;
    if (data == null) return const SizedBox.shrink();
    if (data['zero_cost'] == true) {
      return _chip(
        context,
        label: compact ? r'$0 · local' : r'LLM cost: $0.00 · local',
        icon: Icons.savings_outlined,
        color: Colors.greenAccent,
      );
    }
    final usd = (data['total_usd'] as num?)?.toDouble() ?? 0.0;
    final inTokens = (data['total_input_tokens'] as num?)?.toInt() ?? 0;
    final outTokens = (data['total_output_tokens'] as num?)?.toInt() ?? 0;
    return Tooltip(
      message: '${_tokens(inTokens)} in · ${_tokens(outTokens)} out tokens',
      child: _chip(
        context,
        label: compact
            ? '\$${usd.toStringAsFixed(2)}'
            : 'LLM cost: \$${usd.toStringAsFixed(2)}',
        icon: Icons.paid_outlined,
        color: Colors.amber,
      ),
    );
  }

  String _tokens(int n) {
    final s = '$n';
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }

  Widget _chip(
    BuildContext context, {
    required String label,
    required IconData icon,
    required Color color,
  }) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 10,
        vertical: compact ? 3 : 4,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: compact ? 14 : 16, color: color),
          if (!compact || label.length < 12) ...[
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: compact ? 11 : 12, color: color)),
          ],
        ],
      ),
    );
  }
}
