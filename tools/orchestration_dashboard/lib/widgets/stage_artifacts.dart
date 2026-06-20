import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../services/api_client.dart';

/// **Browse every artifact at every stage.** Lists the artifacts each pipeline
/// phase produced (problem → spec → plan → tasks → tests → review → code), grouped
/// by stage, and lets you click any one to read its full content. Always available
/// — during and after the build. Reuses the existing `listArtifacts`/`getArtifact`
/// API; no server change needed.
class StageArtifacts extends StatefulWidget {
  const StageArtifacts({
    super.key,
    required this.api,
    required this.featureId,
    this.selectedPhase,
  });

  final ApiClient api;
  final String featureId;

  /// When set (a phase was clicked in the rail), that stage's section is
  /// expanded, highlighted, and scrolled into view; others collapse.
  final int? selectedPhase;

  @override
  State<StageArtifacts> createState() => _StageArtifactsState();
}

/// The 7 user-facing stages and the artifacts that belong to each.
const _stages = <int, String>{
  1: 'Problem',
  2: 'Spec',
  3: 'Plan',
  4: 'Tasks',
  5: 'Tests',
  6: 'Review',
  7: 'Code',
};

int phaseForArtifact(String name) {
  final n = name.toLowerCase();
  if (n.contains('problem') || n.contains('intake')) {
    return 1;
  }
  if (n.contains('spec')) {
    return 2;
  }
  if (n.contains('plan') && !n.contains('test')) {
    return 3;
  }
  if (n.contains('task')) {
    return 4;
  }
  if (n.contains('test')) {
    return 5; // test-cases.md, test-plan.md
  }
  if (n.contains('traceability') || n.contains('verdict') ||
      n.contains('review')) {
    return 6;
  }
  return 7; // generated code + anything else
}

class _StageArtifactsState extends State<StageArtifacts> {
  // phase -> list of {name, path, group}
  Map<int, List<Map<String, dynamic>>> _byPhase = {};
  bool _loading = true;
  String? _error;

  final ScrollController _scroll = ScrollController();
  final Map<int, GlobalKey> _sectionKeys = {};
  // ExpansionTile.controller still takes ExpansionTileController in this SDK.
  // ignore: deprecated_member_use
  final Map<int, ExpansionTileController> _controllers = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant StageArtifacts old) {
    super.didUpdateWidget(old);
    if (old.selectedPhase != widget.selectedPhase &&
        widget.selectedPhase != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _focusSelected());
    }
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  /// Expand + scroll the selected stage into view (best-effort — the section may
  /// not be laid out yet on first paint).
  void _focusSelected() {
    final p = widget.selectedPhase;
    if (p == null || !mounted) return;
    try {
      _controllers[p]?.expand();
    } catch (e) {
      debugPrint('StageArtifacts: could not expand stage $p — $e'); // D13
    }
    final ctx = _sectionKeys[p]?.currentContext;
    if (ctx != null) {
      Scrollable.ensureVisible(ctx,
          duration: const Duration(milliseconds: 300), alignment: 0.05);
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.api.listArtifacts(widget.featureId);
      final byPhase = <int, List<Map<String, dynamic>>>{};
      for (final entry in data.entries) {
        final group = entry.key; // 'spec' | 'code'
        for (final f in (entry.value as List).cast<Map<String, dynamic>>()) {
          final name = f['name'] as String? ?? '?';
          final phase = group == 'code' ? 7 : phaseForArtifact(name);
          byPhase.putIfAbsent(phase, () => []).add({
            'name': name,
            'path': f['path'] as String? ?? '',
            'bytes': f['bytes'] ?? 0,
          });
        }
      }
      if (mounted) setState(() => _byPhase = byPhase);
      if (widget.selectedPhase != null) {
        WidgetsBinding.instance.addPostFrameCallback((_) => _focusSelected());
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _view(String path, String name) async {
    String content;
    try {
      content = await widget.api.getArtifact(widget.featureId, path);
    } catch (e) {
      content = 'Could not load: $e';
    }
    if (!mounted) return;
    final isMarkdown = name.toLowerCase().endsWith('.md');
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(name),
        content: SizedBox(
          width: 680,
          height: 480,
          child: SingleChildScrollView(
            child: isMarkdown
                ? MarkdownBody(data: content, selectable: true)
                : SelectableText(content,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _byPhase.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(child: Text('Artifacts unavailable: $_error'));
    }
    final total = _byPhase.values.fold<int>(0, (a, b) => a + b.length);
    if (total == 0) {
      return const Center(
        key: Key('stage-artifacts-empty'),
        child: Text('No artifacts yet — they appear here as each stage runs.'),
      );
    }
    final phases = _stages.keys.toList()..sort();
    return ListView(
      key: const Key('stage-artifacts'),
      controller: _scroll,
      padding: const EdgeInsets.all(12),
      children: [
        Row(
          children: [
            Text('Artifacts by stage',
                style: Theme.of(context).textTheme.titleSmall),
            const Spacer(),
            IconButton(
              tooltip: 'Refresh',
              icon: const Icon(Icons.refresh, size: 18),
              onPressed: _load,
            ),
          ],
        ),
        for (final phase in phases)
          if ((_byPhase[phase] ?? const []).isNotEmpty)
            _stageSection(phase, _byPhase[phase]!),
      ],
    );
  }

  Widget _stageSection(int phase, List<Map<String, dynamic>> items) {
    final selected = widget.selectedPhase == phase;
    final controller =
        // ignore: deprecated_member_use
        _controllers.putIfAbsent(phase, () => ExpansionTileController());
    final sectionKey = _sectionKeys.putIfAbsent(phase, () => GlobalKey());
    final scheme = Theme.of(context).colorScheme;
    return Container(
      key: sectionKey,
      margin: const EdgeInsets.symmetric(vertical: 2),
      decoration: selected
          ? BoxDecoration(
              border: Border.all(color: scheme.primary.withValues(alpha: 0.55)),
              borderRadius: BorderRadius.circular(8),
              color: scheme.primary.withValues(alpha: 0.05),
            )
          : null,
      child: ExpansionTile(
        key: Key('stage-$phase'),
        controller: controller,
        // Selected → only that stage opens; no selection → browse all open.
        initiallyExpanded: widget.selectedPhase == null || selected,
        tilePadding: const EdgeInsets.symmetric(horizontal: 4),
        title: Text('$phase · ${_stages[phase]}',
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
      subtitle: Text('${items.length} artifact${items.length == 1 ? '' : 's'}',
          style: const TextStyle(fontSize: 11)),
      children: [
        for (final f in items)
          ListTile(
            dense: true,
            leading: Icon(
                (f['name'] as String).endsWith('.md')
                    ? Icons.description_outlined
                    : Icons.code,
                size: 18),
            title: Text(f['name'] as String),
            subtitle: Text('${f['bytes']} bytes',
                style: const TextStyle(fontSize: 11)),
            trailing: const Icon(Icons.open_in_full, size: 14),
            onTap: () => _view(f['path'] as String, f['name'] as String),
          ),
        ],
      ),
    );
  }
}
