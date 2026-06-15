import 'package:flutter/material.dart';

import '../services/api_client.dart';

/// A live **context budget** chip — ADF's `/compact` made visible. It shows how
/// much of the model's context window the app's accumulated state would use
/// (`12k / 120k tokens`), turns amber and offers **Compact** when over budget,
/// and folds the context on tap. The same `/compact` discipline Claude Code uses,
/// surfaced for the app being built.
class ContextChip extends StatefulWidget {
  const ContextChip({super.key, required this.api, required this.featureId});

  final ApiClient api;
  final String featureId;

  @override
  State<ContextChip> createState() => _ContextChipState();
}

class _ContextChipState extends State<ContextChip> {
  Map<String, dynamic>? _ctx;
  bool _loading = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final c = await widget.api.getContext(widget.featureId);
      if (mounted) setState(() => _ctx = c);
    } catch (_) {
      // leave _ctx null -> the chip renders an unobtrusive "context" placeholder
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _onTap() async {
    if (_busy) return;
    final over = _ctx?['over'] == true;
    if (!over) {
      await _load();
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.compact(widget.featureId);
    } catch (_) {
      // best-effort; the re-estimate below reflects whatever actually happened
    } finally {
      if (mounted) setState(() => _busy = false);
      await _load();
    }
  }

  static String _fmt(num n) =>
      n >= 1000 ? '${(n / 1000).round()}k' : '$n';

  @override
  Widget build(BuildContext context) {
    if (_loading && _ctx == null) {
      return _shell(const Color(0xFF64748B), Icons.memory, 'context…');
    }
    final ctx = _ctx;
    if (ctx == null || ctx['has_app'] != true || ctx['tokens'] == null) {
      return _shell(const Color(0xFF64748B), Icons.memory, 'context');
    }
    final tokens = ctx['tokens'] as num;
    final budget = (ctx['budget'] as num?) ?? 120000;
    final over = ctx['over'] == true;
    final color = over ? const Color(0xFFD97706) : const Color(0xFF16A34A);
    final label = over
        ? '${_fmt(tokens)} / ${_fmt(budget)} · Compact'
        : '${_fmt(tokens)} / ${_fmt(budget)}';
    return Tooltip(
      message: over
          ? 'Context is over budget (${_fmt(tokens)} / ${_fmt(budget)} tokens).\n'
              'Tap to /compact — fold the low-value context, keep a durable card.'
          : 'Context budget: ${_fmt(tokens)} of ${_fmt(budget)} tokens.\n'
              'Tap to re-estimate.',
      child: InkWell(
        onTap: _onTap,
        borderRadius: BorderRadius.circular(999),
        child: _shell(color, over ? Icons.warning_amber : Icons.memory, label),
      ),
    );
  }

  Widget _shell(Color color, IconData icon, String text) {
    return Container(
      key: const Key('context-chip'),
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
          if (_busy) ...[
            const SizedBox(width: 8),
            const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(strokeWidth: 1.6)),
          ],
        ],
      ),
    );
  }
}
