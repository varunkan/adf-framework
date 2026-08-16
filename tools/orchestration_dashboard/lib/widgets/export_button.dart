import 'package:flutter/material.dart';

import '../services/api_client.dart';

/// "Own your code" — one click packages the app + its sealed audit bundle +
/// Proof of Build into a portable, self-verifying zip on your machine. The
/// ownership half of the moat, made visible.
class ExportButton extends StatefulWidget {
  const ExportButton({super.key, required this.api, required this.featureId});

  final ApiClient api;
  final String featureId;

  @override
  State<ExportButton> createState() => _ExportButtonState();
}

class _ExportButtonState extends State<ExportButton> {
  bool _busy = false;
  String? _result;

  Future<void> _export() async {
    setState(() {
      _busy = true;
      _result = null;
    });
    try {
      final r = await widget.api.exportApp(widget.featureId);
      if (!mounted) return;
      if (r['ok'] == true) {
        final kb = ((r['bytes'] as num) / 1024).toStringAsFixed(0);
        setState(() => _result = 'Exported ${r['files']} files ($kb KB) → ${r['out']}');
      } else {
        setState(() => _result = 'Export failed: ${r['error'] ?? 'unknown'}');
      }
    } catch (e) {
      if (mounted) setState(() => _result = 'Export failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('export-button'),
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        FilledButton.tonalIcon(
          onPressed: _busy ? null : _export,
          icon: _busy
              ? const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 1.6))
              : const Icon(Icons.archive_outlined, size: 16),
          label: const Text('Export (own your code)'),
        ),
        if (_result != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(_result!,
                style: Theme.of(context).textTheme.bodySmall, softWrap: true),
          ),
      ],
    );
  }
}
