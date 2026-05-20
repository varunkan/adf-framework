import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../main.dart';
import '../services/api_client.dart';
import '../theme/orchestration_colors.dart';
import '../widgets/runner_setup_card.dart';
import 'feature_detail_screen.dart';
import 'new_feature_screen.dart';

class FeatureListScreen extends StatefulWidget {
  const FeatureListScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<FeatureListScreen> createState() => _FeatureListScreenState();
}

class _FeatureListScreenState extends State<FeatureListScreen> {
  List<Map<String, dynamic>> _features = [];
  int _featureCount = 0;
  bool _loading = true;
  bool _serverUp = false;
  String? _error;
  Timer? _poll;
  final _searchController = TextEditingController();
  String _query = '';

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() {
      setState(() => _query = _searchController.text.trim().toLowerCase());
    });
    _refresh();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _refresh(silent: true));
  }

  @override
  void dispose() {
    _poll?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  List<Map<String, dynamic>> get _filtered {
    if (_query.isEmpty) return _features;
    return _features.where((f) {
      final id = (f['id'] as String? ?? '').toLowerCase();
      return id.contains(_query);
    }).toList();
  }

  Future<void> _refresh({bool silent = false}) async {
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final up = await widget.api.health();
      if (!up) {
        if (!silent || !_serverUp) {
          setState(() {
            _serverUp = false;
            _loading = false;
            _error = 'API not reachable at ${widget.api.baseUrl}';
          });
        }
        return;
      }
      final result = await widget.api.listFeatures();
      if (!mounted) return;
      setState(() {
        _serverUp = true;
        _features = result.features;
        _featureCount = result.count;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!silent || _features.isEmpty) {
        setState(() {
          _loading = false;
          _serverUp = false;
          _error = e.toString();
        });
      }
    }
  }

  Future<void> _openNewFeature() async {
    final created = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => NewFeatureScreen(api: widget.api)),
    );
    if (created == true) _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final status = context.orchStatus;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Orchestration'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: 'Search features…',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _query.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () => _searchController.clear(),
                      )
                    : null,
                isDense: true,
              ),
            ),
          ),
        ),
        actions: [
          if (_serverUp) RunnerHealthLoader(api: widget.api),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _serverUp ? _openNewFeature : null,
        icon: const Icon(Icons.add),
        label: const Text('New feature'),
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!_serverUp && _error != null)
            Material(
              color: status.errorBg,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Icon(Icons.cloud_off, color: status.error, size: 20),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _error!,
                        style: TextStyle(fontSize: 13, color: status.error),
                      ),
                    ),
                    TextButton(onPressed: _refresh, child: const Text('Retry')),
                  ],
                ),
              ),
            )
          else if (_serverUp)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Text(
                '$_featureCount feature${_featureCount == 1 ? '' : 's'} · ${widget.api.baseUrl}',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
            ),
          Expanded(child: _buildList(context)),
        ],
      ),
    );
  }

  Widget _buildList(BuildContext context) {
    if (_loading && _features.isEmpty && _error == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null && _features.isEmpty) {
      return _ErrorState(error: _error!, onRetry: _refresh);
    }
    if (_features.isEmpty) {
      return _EmptyState(serverUp: _serverUp, onCreate: _openNewFeature);
    }
    final list = _filtered;
    if (list.isEmpty) {
      return Center(
        child: Text(
          'No features match "$_query"',
          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: list.length,
        itemBuilder: (context, index) => _FeatureCard(
          feature: list[index],
          onTap: () async {
            final id = list[index]['id'] as String? ?? '';
            await Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => FeatureDetailScreen(
                  api: widget.api,
                  featureId: id,
                ),
              ),
            );
            _refresh(silent: true);
          },
        ),
      ),
    );
  }
}

class _FeatureCard extends StatelessWidget {
  const _FeatureCard({required this.feature, required this.onTap});

  final Map<String, dynamic> feature;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final status = context.orchStatus;
    final scheme = Theme.of(context).colorScheme;
    final id = feature['id'] as String? ?? '';
    final phase = feature['current_phase'];
    final pipelineComplete = feature['pipeline_complete'] == true ||
        (feature['status'] as String? ?? '') == 'completed';
    final awaiting = feature['awaiting_user'] == true;
    final judgeVerdict =
        (feature['last_judge_verdict'] as String? ?? '').toLowerCase();
    final runStatus = feature['run_status'] as String?;
    final featureStatus = feature['status'] as String? ?? 'active';

    final running = runStatus == 'queued' ||
        runStatus == 'running' ||
        runStatus == 'healing';
    final needsSetup = runStatus == 'needs_login';
    final blocked = runStatus == 'blocked' || runStatus == 'error';
    final needsRevision = awaiting && judgeVerdict != 'pass';

    String chipLabel;
    Color chipColor;
    Color chipBg;

    if (pipelineComplete) {
      chipLabel = 'Complete';
      chipColor = Colors.green.shade700;
      chipBg = Colors.green.shade50;
    } else if (running) {
      chipLabel = 'Running';
      chipColor = status.running;
      chipBg = status.runningBg;
    } else if (needsRevision) {
      chipLabel = 'Revision needed';
      chipColor = status.error;
      chipBg = status.errorBg;
    } else if (awaiting) {
      chipLabel = 'Ready to approve';
      chipColor = status.awaiting;
      chipBg = status.awaitingBg;
    } else if (needsSetup) {
      chipLabel = 'Setup required';
      chipColor = status.error;
      chipBg = status.errorBg;
    } else if (blocked) {
      chipLabel = 'Blocked';
      chipColor = status.error;
      chipBg = status.errorBg;
    } else {
      chipLabel = featureStatus;
      chipColor = status.idle;
      chipBg = status.idleBg;
    }

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: scheme.primaryContainer,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(Icons.layers_outlined, color: scheme.primary),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      id,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      pipelineComplete
                          ? 'Complete · Track ${feature['track'] ?? '—'}'
                          : 'Phase $phase · Track ${feature['track'] ?? '—'}',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: scheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Chip(
                    label: Text(
                      chipLabel,
                      style: TextStyle(fontSize: 11, color: chipColor),
                    ),
                    backgroundColor: chipBg,
                    side: BorderSide(color: chipColor.withValues(alpha: 0.3)),
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  ),
                  if (running)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: status.running,
                        ),
                      ),
                    )
                  else
                    Icon(Icons.chevron_right, color: scheme.outline),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.serverUp, required this.onCreate});

  final bool serverUp;
  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.rocket_launch_outlined, size: 64, color: scheme.outline),
            const SizedBox(height: 16),
            Text(
              'Build your first feature',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              'Create a feature to run the orchestration pipeline with AI agents.',
              textAlign: TextAlign.center,
              style: TextStyle(color: scheme.onSurfaceVariant),
            ),
            const SizedBox(height: 24),
            if (serverUp)
              FilledButton.icon(
                onPressed: onCreate,
                icon: const Icon(Icons.add),
                label: const Text('Create feature'),
              ),
          ],
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.error, required this.onRetry});

  final String error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.cloud_off, size: 64, color: Colors.grey.shade400),
            const SizedBox(height: 16),
            Text(error, textAlign: TextAlign.center),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () {
                Clipboard.setData(
                  const ClipboardData(
                    text: './scripts/start_orchestration_dashboard.sh web',
                  ),
                );
                showMessage(context, 'Copied start script (API + dashboard)');
              },
              icon: const Icon(Icons.copy),
              label: const Text('Copy start script'),
            ),
            const SizedBox(height: 8),
            Text(
              'API only: ORCH_REPO_ROOT=\$PWD dart run tools/orchestration_server/bin/server.dart\n'
              'Dashboard: http://localhost:3848 (run the script above)',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
            ),
          ],
        ),
      ),
    );
  }
}
