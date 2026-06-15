import 'package:flutter/material.dart';

import '../services/api_client.dart';

/// The visible face of ADF's moat: a live **Proof of Build** badge. It asks the
/// server to recompute the app's tamper-evident Merkle seal offline and shows
/// `🔏 VERIFIED · adf1:…` (green) or `TAMPERED` (red, with the divergent files).
/// Tap to re-verify. No competitor can show this — the app proves itself.
class ProofBadge extends StatefulWidget {
  const ProofBadge({super.key, required this.api, required this.featureId});

  final ApiClient api;
  final String featureId;

  @override
  State<ProofBadge> createState() => _ProofBadgeState();
}

class _ProofBadgeState extends State<ProofBadge> {
  Map<String, dynamic>? _proof;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _verify();
  }

  Future<void> _verify() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final p = await widget.api.getProof(widget.featureId);
      if (mounted) setState(() => _proof = p);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return _shell(
        const Color(0xFF64748B),
        Icons.lock_outline,
        'Verifying build…',
        const SizedBox(
          width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.6)),
      );
    }
    if (_error != null || _proof == null) {
      return _shell(const Color(0xFF64748B), Icons.lock_outline,
          'Proof unavailable', null);
    }
    if (_proof!['has_proof'] != true) {
      return _shell(const Color(0xFF64748B), Icons.lock_outline,
          'No proof yet', null);
    }
    final ok = _proof!['ok'] == true;
    final seal = _proof!['seal'] as String? ?? '';
    final color = ok ? const Color(0xFF16A34A) : const Color(0xFFDC2626);
    final label = ok ? 'Verified · $seal' : 'TAMPERED';
    return Tooltip(
      message: _tooltip(ok),
      child: InkWell(
        onTap: _verify,
        borderRadius: BorderRadius.circular(999),
        child: _shell(color, ok ? Icons.verified_user : Icons.gpp_bad, label, null),
      ),
    );
  }

  String _tooltip(bool ok) {
    if (ok) {
      final n = _proof!['n_files'] ?? '?';
      return 'Proof of Build VERIFIED offline\n'
          '$n files + spec + build verdict sealed under a Merkle root\n'
          'Tap to re-verify';
    }
    final files = (_proof!['files'] as List?)?.cast<Map>() ?? const [];
    final bad = files.where((f) => f['status'] != 'ok').toList();
    final lines = bad.take(4).map((f) => '• ${f['path']} (${f['status']})').join('\n');
    return 'TAMPERED — diverges from the sealed build:\n$lines\nTap to re-verify';
  }

  Widget _shell(Color color, IconData icon, String text, Widget? trailing) {
    return Container(
      key: const Key('proof-badge'),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 6),
          Text(text,
              style: TextStyle(
                  color: color, fontSize: 12, fontWeight: FontWeight.w600)),
          if (trailing != null) ...[const SizedBox(width: 8), trailing],
        ],
      ),
    );
  }
}
