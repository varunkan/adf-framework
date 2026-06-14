import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../services/api_client.dart';
import '../theme/studio_theme.dart';
import 'app_preview_frame.dart';
import 'cost_badge.dart';
import 'integrity_badge.dart';

/// Right-rail live preview (Lovable-style): phase, artifacts, spec, integrity, crew.
class LivePreviewPanel extends StatefulWidget {
  const LivePreviewPanel({
    super.key,
    required this.api,
    required this.featureId,
    required this.phase,
    required this.status,
    this.requirement = '',
    this.currentStep,
    this.gates = const {},
    this.combinedRecommendation,
    this.awaitingApproval = false,
    this.building = false,
  });

  final ApiClient api;
  final String featureId;
  final int phase;
  final String status;
  final String requirement;
  final String? currentStep;
  final Map<String, dynamic> gates;
  final String? combinedRecommendation;
  final bool awaitingApproval;
  final bool building;

  @override
  State<LivePreviewPanel> createState() => _LivePreviewPanelState();
}

class _LivePreviewPanelState extends State<LivePreviewPanel>
    with SingleTickerProviderStateMixin {
  Map<String, dynamic>? _preview;
  Map<String, dynamic>? _cost;
  Map<String, dynamic>? _appPreview;
  bool _appPreviewLoading = false;
  bool _loading = true;
  Timer? _poll;
  int _pollMs = 2000;
  bool _buildInFlight = false;
  late TabController _tabs;

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 5, vsync: this);
    _load();
    _schedulePoll();
  }


  void _schedulePoll() {
    _poll?.cancel();
    _poll = Timer(Duration(milliseconds: _pollMs), () async {
      await _load(silent: true);
      final unchanged = widget.api.wasPreviewNotModified(widget.featureId);
      _pollMs = unchanged ? (_pollMs * 2).clamp(2000, 10000) : 2000;
      if (mounted) _schedulePoll();
    });
  }

  void _wakePoll() {
    _pollMs = 2000;
    if (mounted) _schedulePoll();
  }

  @override
  void didUpdateWidget(covariant LivePreviewPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.phase != widget.phase ||
        oldWidget.building != widget.building ||
        oldWidget.featureId != widget.featureId) {
      if (oldWidget.featureId != widget.featureId) _cost = null;
      _wakePoll();
      _load(silent: true);
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    _tabs.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (!silent && mounted) setState(() => _loading = true);
    try {
      final data = await widget.api.fetchPreview(
        widget.featureId,
        phase: widget.phase > 0 ? widget.phase : null,
      );
      if (!mounted) return;
      setState(() {
        _preview = data;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loading = false);
    }
    await _loadCost();
    _loadAppPreview();
  }

  /// Cost endpoint is optional (older servers 404) — degrade silently.
  Future<void> _loadCost() async {
    try {
      final cost = await widget.api.getFeatureCost(widget.featureId);
      if (!mounted) return;
      setState(() => _cost = cost);
    } catch (_) {
      // Keep the last known value; badge stays hidden if it never loaded.
    }
  }

  /// Launches (lazily) and polls the live app. The server only spawns a process
  /// once an app exists, and `ensureRunning` is idempotent, so polling is cheap.
  /// `restart=true` kills + relaunches on a fresh port after a rebuild.
  Future<void> _loadAppPreview({bool restart = false}) async {
    // The app only exists after the implement phase; don't poke earlier.
    if (widget.phase < 6 && !restart && _appPreview == null) return;
    if (restart && mounted) {
      setState(() {
        _appPreviewLoading = true;
        _appPreview = null;
      });
    }
    try {
      final res = restart
          ? await widget.api.restartAppPreview(widget.featureId)
          : await widget.api.getAppPreview(widget.featureId);
      if (!mounted) return;
      setState(() {
        _appPreview = res;
        _appPreviewLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _appPreviewLoading = false);
    }
  }

  Map<String, dynamic>? get _integrity =>
      _preview?['integrity'] as Map<String, dynamic>?;

  Map<String, dynamic>? get _crew =>
      _preview?['crew'] as Map<String, dynamic>?;

  Map<String, dynamic>? get _product =>
      _preview?['product'] as Map<String, dynamic>?;

  Map<String, dynamic>? get _buildInfo =>
      _preview?['build'] as Map<String, dynamic>?;

  List<Map<String, dynamic>> get _agents =>
      (_crew?['agents'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ?? [];

  List<Map<String, dynamic>> get _artifacts =>
      (_preview?['artifacts'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ??
          [];

  bool get _isBuilding =>
      widget.building || _preview?['building'] == true || _crew?['running'] == true;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final passed = widget.gates.entries.where((e) => e.value == true).length;
    final total = widget.gates.length;
    final specExcerpt = _preview?['spec_excerpt'] as String?;
    final codeExcerpt = _product?['code_excerpt'] as String?;
    final previewUrl = _product?['preview_url'] as String?;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          child: Row(
            children: [
              Icon(Icons.visibility_outlined, size: 18, color: StudioTheme.accent),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Live preview',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
              CostBadge(compact: true, cost: _cost),
              const SizedBox(width: 8),
              IntegrityBadge(
                compact: true,
                valid: _integrity?['valid'] as bool?,
                sealedFiles: (_integrity?['sealed_files'] as num?)?.toInt(),
                breachCount:
                    (_integrity?['breaches'] as List?)?.length ?? 0,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _chip(context, 'Phase ${widget.phase}', StudioTheme.accent),
              _chip(context, widget.status, scheme.outline),
              if (_isBuilding) _chip(context, 'Building…', StudioTheme.accentSoft),
              if (_buildInfo?['status'] == 'building')
                _chip(context, 'Preview build', StudioTheme.accentSoft),
              if (_buildInfo?['status'] == 'ready' || previewUrl != null)
                _chip(context, 'Preview live', Colors.greenAccent),
              if (widget.awaitingApproval) _chip(context, 'Awaiting you', Colors.amber),
              if (widget.currentStep != null)
                _chip(context, widget.currentStep!, StudioTheme.accentSoft),
            ],
          ),
        ),
        if (_isBuilding)
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 10, 16, 0),
            child: LinearProgressIndicator(
              minHeight: 4,
              backgroundColor: StudioTheme.panelBorder,
              color: StudioTheme.accent,
            ),
          ),
        if (total > 0)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: LinearProgressIndicator(
              value: total > 0 ? passed / total : 0,
              backgroundColor: StudioTheme.panelBorder,
              color: StudioTheme.accent,
              minHeight: 6,
              borderRadius: BorderRadius.circular(3),
            ),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
          child: Row(
            children: [
              _actionBtn(
                context,
                icon: Icons.rocket_launch_outlined,
                label: _buildInFlight ? 'Building…' : 'Run preview',
                enabled: !_buildInFlight,
                onTap: _runPreviewBuild,
              ),
              const SizedBox(width: 8),
              _actionBtn(
                context,
                icon: Icons.open_in_new,
                label: 'Open',
                enabled: previewUrl != null,
                onTap: () => _copyUrl(previewUrl!),
              ),
              const SizedBox(width: 8),
              _actionBtn(
                context,
                icon: Icons.description_outlined,
                label: 'Spec',
                enabled: specExcerpt != null,
                onTap: () => _tabs.animateTo(1),
              ),
            ],
          ),
        ),
        TabBar(
          controller: _tabs,
          labelColor: StudioTheme.accent,
          unselectedLabelColor: Colors.white54,
          indicatorColor: StudioTheme.accent,
          tabs: const [
            Tab(text: 'App'),
            Tab(text: 'Overview'),
            Tab(text: 'Spec'),
            Tab(text: 'Crew'),
            Tab(text: 'Artifacts'),
          ],
        ),
        Expanded(
          child: _loading && _preview == null
              ? _skeleton(context)
              : TabBarView(
                  controller: _tabs,
                  children: [
                    _appTab(context),
                    _overviewTab(context, scheme, codeExcerpt, previewUrl),
                    _specTab(context, scheme, specExcerpt),
                    _crewTab(context),
                    _artifactsTab(context),
                  ],
                ),
        ),
      ],
    );
  }

  /// The hero tab: the REAL running app, rendered inline in an iframe.
  Widget _appTab(BuildContext context) {
    final ap = _appPreview;
    final available = ap != null && ap['available'] == true;
    final url = ap?['url'] as String?;
    if (available && url != null) {
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
            child: Row(
              children: [
                _chip(context, 'Live app', Colors.greenAccent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    url,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 11, color: Colors.white60),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.refresh, size: 18),
                  tooltip: 'Restart app preview',
                  onPressed: () => _loadAppPreview(restart: true),
                ),
              ],
            ),
          ),
          Expanded(
            child: Container(
              margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: StudioTheme.panelBorder),
              ),
              clipBehavior: Clip.antiAlias,
              child: buildAppPreviewFrame(url),
            ),
          ),
        ],
      );
    }
    final status = ap?['status'] as String?;
    final reason = ap?['reason'] as String?;
    final building = widget.building || _isBuilding;
    final failed = status == 'failed_to_start' || status == 'spawn_failed';
    IconData icon;
    String headline;
    if (_appPreviewLoading) {
      icon = Icons.hourglass_top;
      headline = 'Starting your app…';
    } else if (failed) {
      icon = Icons.error_outline;
      headline = 'Could not start the app preview';
    } else if (widget.phase < 7 || building) {
      icon = Icons.auto_awesome;
      headline = 'Your app appears here — live — the moment the build finishes.';
    } else {
      icon = Icons.web_asset;
      headline = 'No running app yet — build the feature to see it live.';
    }
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (_appPreviewLoading)
              const SizedBox(
                width: 28,
                height: 28,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              )
            else
              Icon(icon, size: 44, color: StudioTheme.accentSoft),
            const SizedBox(height: 14),
            Text(
              headline,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            if (reason != null) ...[
              const SizedBox(height: 8),
              Text(
                reason,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 12, color: Colors.white54),
              ),
            ],
            if (failed) ...[
              const SizedBox(height: 16),
              FilledButton.tonalIcon(
                onPressed: () => _loadAppPreview(restart: true),
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Retry'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _overviewTab(
    BuildContext context,
    ColorScheme scheme,
    String? codeExcerpt,
    String? previewUrl,
  ) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (previewUrl != null) ...[
            Text('App preview', style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 8),
            _panel(
              child: SelectableText(
                previewUrl,
                style: TextStyle(color: StudioTheme.accent, fontSize: 12),
              ),
            ),
            const SizedBox(height: 16),
          ],
          Text('Requirement', style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 8),
          _panel(
            child: MarkdownBody(
              data: widget.requirement.isEmpty
                  ? '_Describe your feature in chat — ADF will spec, plan, test, and implement with proof gates._'
                  : widget.requirement,
              selectable: true,
              styleSheet: MarkdownStyleSheet(
                p: TextStyle(color: scheme.onSurface, height: 1.5),
              ),
            ),
          ),
          if (codeExcerpt != null) ...[
            const SizedBox(height: 16),
            Text('Generated UI', style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 8),
            _panel(
              child: SelectableText(
                codeExcerpt,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 11,
                  height: 1.4,
                ),
              ),
            ),
          ],
          if (widget.combinedRecommendation != null &&
              widget.combinedRecommendation!.trim().isNotEmpty) ...[
            const SizedBox(height: 16),
            Text('BMAD feedback', style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 8),
            _panel(
              color: Colors.amber.withValues(alpha: 0.08),
              border: Colors.amber.withValues(alpha: 0.3),
              child: Text(widget.combinedRecommendation!.trim()),
            ),
          ],
          const SizedBox(height: 16),
          Text('What happens next', style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 8),
          _nextStepRow(Icons.auto_awesome, 'Crew builds spec → plan → tests (~300ms)'),
          _nextStepRow(Icons.fact_check_outlined, 'BMAD panel reviews each phase'),
          _nextStepRow(Icons.approval, 'You approve — integrity chain seals artifacts'),
          _nextStepRow(Icons.code, 'Phase 7 implements with TDD + quality gates'),
        ],
      ),
    );
  }

  Widget _specTab(BuildContext context, ColorScheme scheme, String? spec) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: _panel(
        child: MarkdownBody(
          data: spec ??
              '_Spec not generated yet. Submit a prompt or hit **Autopilot**._',
          selectable: true,
          styleSheet: MarkdownStyleSheet(
            p: TextStyle(color: scheme.onSurface, height: 1.5),
          ),
        ),
      ),
    );
  }

  Widget _crewTab(BuildContext context) {
    if (_agents.isEmpty) {
      return Center(
        child: Text(
          _isBuilding ? 'Crew is spinning up subagents…' : 'No crew run yet',
          style: TextStyle(color: Colors.white.withValues(alpha: 0.55)),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _agents.length,
      itemBuilder: (context, i) {
        final a = _agents[i];
        final done = a['status'] == 'done';
        final running = a['status'] == 'running';
        return ListTile(
          dense: true,
          leading: Icon(
            done
                ? Icons.check_circle_outline
                : running
                    ? Icons.hourglass_top
                    : Icons.radio_button_unchecked,
            color: done
                ? Colors.greenAccent
                : running
                    ? StudioTheme.accent
                    : Colors.white38,
            size: 20,
          ),
          title: Text(a['agent'] as String? ?? a['name'] as String? ?? 'agent'),
          subtitle: Text(a['role'] as String? ?? ''),
          trailing: Text(
            a['duration_ms'] != null ? '${a['duration_ms']}ms' : '',
            style: const TextStyle(fontSize: 11),
          ),
        );
      },
    );
  }

  Widget _artifactsTab(BuildContext context) {
    final gateItems = _artifacts.where((a) => a['gate'] != null).toList();
    final fileItems = _artifacts.where((a) => a['file'] != null).toList();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Pipeline gates', style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 8),
        ...gateItems.map((g) => _checkRow(
              label: 'Phase ${g['phase']}: ${g['gate']}',
              done: g['done'] == true,
            )),
        if (fileItems.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text('Phase artifacts', style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 8),
          ...fileItems.map((f) => _checkRow(
                label: f['file'] as String? ?? '',
                done: f['done'] == true,
                required: f['required'] == true,
              )),
        ],
      ],
    );
  }

  Widget _skeleton(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: List.generate(
        4,
        (i) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Container(
            height: i == 0 ? 80 : 48,
            decoration: BoxDecoration(
              color: StudioTheme.panel,
              borderRadius: BorderRadius.circular(12),
            ),
          ),
        ),
      ),
    );
  }

  Widget _panel({
    required Widget child,
    Color? color,
    Color? border,
  }) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color ?? StudioTheme.panel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: border ?? StudioTheme.panelBorder),
      ),
      child: child,
    );
  }

  Widget _chip(BuildContext context, String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(label, style: TextStyle(fontSize: 12, color: color)),
    );
  }

  Widget _actionBtn(
    BuildContext context, {
    required IconData icon,
    required String label,
    required bool enabled,
    required VoidCallback onTap,
  }) {
    return Expanded(
      child: FilledButton.tonalIcon(
        onPressed: enabled ? onTap : null,
        icon: Icon(icon, size: 16),
        label: Text(label, style: const TextStyle(fontSize: 11)),
        style: FilledButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          visualDensity: VisualDensity.compact,
        ),
      ),
    );
  }

  Widget _nextStepRow(IconData icon, String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: StudioTheme.accentSoft),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 13))),
        ],
      ),
    );
  }

  Widget _checkRow({
    required String label,
    required bool done,
    bool required = false,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Icon(
            done ? Icons.check_box : Icons.check_box_outline_blank,
            size: 18,
            color: done ? Colors.greenAccent : Colors.white38,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              label,
              style: TextStyle(
                fontSize: 12,
                color: done ? Colors.white : Colors.white70,
              ),
            ),
          ),
          if (required && !done)
            const Text('required', style: TextStyle(fontSize: 10, color: Colors.amber)),
        ],
      ),
    );
  }


  Future<void> _runPreviewBuild() async {
    if (_buildInFlight) return;
    setState(() => _buildInFlight = true);
    _wakePoll();
    try {
      final res = await widget.api.buildPreview(widget.featureId);
      if (!mounted) return;
      final status = res['status'] as String? ?? '';
      final enabled = res['enabled'] as bool? ?? true;
      if (!enabled) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          const SnackBar(
            content: Text(
              'Preview build disabled — set ORCH_PREVIEW_BUILD=1 on the API server.',
            ),
          ),
        );
      } else if (status == 'building') {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          const SnackBar(content: Text('Preview building — panel will refresh automatically.')),
        );
      } else if (status == 'ready' || res['preview_url'] != null) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          const SnackBar(content: Text('Preview live — open the URL in your browser.')),
        );
      } else if (res['error'] != null) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          SnackBar(content: Text('Preview: ${res['error']}')),
        );
      }
      await _load(silent: true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          SnackBar(content: Text('Preview build failed: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _buildInFlight = false);
    }
  }

  void _copyUrl(String url) {
    Clipboard.setData(ClipboardData(text: url));
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
      SnackBar(content: Text('Preview URL copied — open in browser: $url')),
    );
  }

}
