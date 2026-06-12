import 'package:flutter/material.dart';

/// Tamper-evident integrity status for ADF Studio header / preview rail.
class IntegrityBadge extends StatelessWidget {
  const IntegrityBadge({
    super.key,
    this.valid,
    this.sealedFiles,
    this.breachCount = 0,
    this.compact = false,
  });

  final bool? valid;
  final int? sealedFiles;
  final int breachCount;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    if (valid == null) {
      return _chip(
        context,
        label: compact ? 'Integrity…' : 'Checking integrity…',
        icon: Icons.shield_outlined,
        color: Colors.white54,
      );
    }
    if (valid == true && breachCount == 0) {
      return _chip(
        context,
        label: compact
            ? 'Sealed'
            : 'Sealed${sealedFiles != null ? ' · $sealedFiles files' : ''}',
        icon: Icons.verified_outlined,
        color: Colors.greenAccent,
      );
    }
    return _chip(
      context,
      label: compact ? 'Breach' : 'Integrity breach ($breachCount)',
      icon: Icons.warning_amber_rounded,
      color: Colors.orangeAccent,
    );
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
