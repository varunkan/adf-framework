import 'package:flutter/material.dart';

import '../main.dart';
import '../services/api_client.dart';

class NewFeatureScreen extends StatefulWidget {
  const NewFeatureScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<NewFeatureScreen> createState() => _NewFeatureScreenState();
}

/// Parses reference links from free text (newline/comma separated), keeping only
/// http(s) URLs. Pure + top-level so the new-feature form's source handling is
/// testable (P4).
List<String> parseSourceLinks(String raw) => raw
    .split(RegExp(r'[\n,]'))
    .map((s) => s.trim())
    .where((s) => s.startsWith('http://') || s.startsWith('https://'))
    .toList();

class _NewFeatureScreenState extends State<NewFeatureScreen> {
  final _idController = TextEditingController();
  final _reqController = TextEditingController();
  final _linksController = TextEditingController();
  String _track = 'M';
  String _stack = 'react-vite-sqlite';
  bool _saving = false;

  @override
  void dispose() {
    _idController.dispose();
    _reqController.dispose();
    _linksController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final id = _idController.text.trim();
    if (id.isEmpty || _reqController.text.trim().isEmpty) {
      showMessage(context, 'ID and requirement required');
      return;
    }
    setState(() => _saving = true);
    try {
      final detail = await widget.api.createFeature(
        id: id,
        requirement: _reqController.text.trim(),
        track: _track,
        stack: _stack,
        sourceLinks: parseSourceLinks(_linksController.text),
      );
      if (!mounted) return;
      final mode = detail['mode'] as String?;
      final msg = detail['message'] as String?;
      if (msg != null && msg.isNotEmpty) {
        showMessage(context, msg);
      } else {
        final run = detail['run_status'] as Map<String, dynamic>?;
        final status = run?['status'] as String?;
        if (status == 'needs_login' || mode == 'needs_login') {
          showMessage(
            context,
            'Feature created. Run cursor-agent login, then open it to start.',
          );
        } else if (run?['headless_unavailable'] == true || mode == 'ide_only') {
          showMessage(
            context,
            'Feature created (IDE mode). In Cursor run: '
            '@orch-orchestrator start $id — then Sync in the dashboard.',
          );
        }
      }
      Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) showMessage(context, e.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('New feature')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _idController,
              decoration: const InputDecoration(
                labelText: 'Feature ID (kebab-case)',
                hintText: 'order-merge-v2',
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _track,
              decoration: const InputDecoration(labelText: 'Track'),
              items: const [
                DropdownMenuItem(value: 'S', child: Text('S — small')),
                DropdownMenuItem(value: 'M', child: Text('M — medium')),
                DropdownMenuItem(value: 'L', child: Text('L — large')),
                DropdownMenuItem(value: 'XL', child: Text('XL — extra large')),
              ],
              onChanged: (v) => setState(() => _track = v ?? 'M'),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: const Key('stack-picker'),
              initialValue: _stack,
              decoration: const InputDecoration(labelText: 'Stack'),
              items: const [
                DropdownMenuItem(
                  value: 'react-vite-sqlite',
                  child: Text('Web (React + Vite + SQLite)'),
                ),
                DropdownMenuItem(
                  value: 'expo-rn',
                  child: Text('Mobile (Expo / React Native)'),
                ),
                DropdownMenuItem(
                  value: 'stdlib',
                  child: Text('Single-file (Python)'),
                ),
              ],
              onChanged: (v) =>
                  setState(() => _stack = v ?? 'react-vite-sqlite'),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: TextField(
                key: const Key('requirement-field'),
                controller: _reqController,
                maxLines: null,
                expands: true,
                decoration: const InputDecoration(
                  labelText: 'Requirement',
                  alignLabelWithHint: true,
                  border: OutlineInputBorder(),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('source-links'),
              controller: _linksController,
              maxLines: 2,
              decoration: const InputDecoration(
                labelText: 'Reference links (optional)',
                hintText: 'https://… — one per line; the crew grounds the spec in these',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Create feature'),
            ),
          ],
        ),
      ),
    );
  }
}
