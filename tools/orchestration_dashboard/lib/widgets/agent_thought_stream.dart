import 'dart:async';

import 'package:flutter/material.dart';

import '../models/trace_span.dart';
import '../services/api_client.dart';
import '../utils/plain_thought_formatter.dart';
import 'plain_thought_view.dart';

/// Polls `/features/<id>/traces` and shows agent reasoning + tools in real time.
class AgentThoughtStream extends StatefulWidget {
  const AgentThoughtStream({
    super.key,
    required this.api,
    required this.featureId,
    this.pollInterval = const Duration(seconds: 1),
    this.maxHeight = 420,
    this.emptyHint,
    this.enableLivePoll = false,
  });

  final ApiClient api;
  final String featureId;
  final Duration pollInterval;
  final double maxHeight;
  final String? emptyHint;
  /// When false, no background polling (manual refresh only).
  final bool enableLivePoll;

  @override
  State<AgentThoughtStream> createState() => _AgentThoughtStreamState();
}

class _AgentThoughtStreamState extends State<AgentThoughtStream> {
  final List<TraceSpan> _spans = [];
  final Set<String> _seenKeys = {};
  final ScrollController _scroll = ScrollController();
  Timer? _timer;
  late bool _live;
  bool _reasoningOnly = false;
  String? _lastTimestamp;
  String? _error;
  bool _polling = false;

  @override
  void initState() {
    super.initState();
    _live = widget.enableLivePoll;
    _syncPolling();
  }

  @override
  void didUpdateWidget(AgentThoughtStream oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.enableLivePoll != oldWidget.enableLivePoll) {
      _live = widget.enableLivePoll;
      _syncPolling();
    }
  }

  void _syncPolling() {
    _timer?.cancel();
    if (widget.enableLivePoll && _live) {
      _poll();
      _timer = Timer.periodic(widget.pollInterval, (_) => _poll());
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _poll() async {
    if (_polling) return;
    _polling = true;
    try {
      final data = await widget.api.fetchTraces(
        widget.featureId,
        since: _lastTimestamp,
        reasoningOnly: _reasoningOnly,
        limit: 200,
      );
      final raw = data['traces'] as List<dynamic>? ?? [];
      final incoming = raw
          .cast<Map<String, dynamic>>()
          .map(TraceSpan.fromJson)
          .toList();
      final novel = <TraceSpan>[];
      for (final span in incoming) {
        if (span.isRunnerControlEvent) continue;
        final key =
            '${span.timestamp}|${span.name}|${span.body.hashCode}';
        if (_seenKeys.add(key)) novel.add(span);
      }
      if (novel.isNotEmpty) {
        setState(() {
          _spans.addAll(novel);
          _lastTimestamp =
              data['last_timestamp'] as String? ?? novel.last.timestamp;
          _error = null;
        });
        _scrollToEnd();
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      _polling = false;
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  void _clear() {
    setState(() {
      _spans.clear();
      _seenKeys.clear();
      _lastTimestamp = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 8, 8),
            child: Row(
              children: [
                Icon(
                  Icons.psychology,
                  color: _live ? Colors.green : Colors.grey,
                  size: 22,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Agent thought process',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (_live && widget.enableLivePoll)
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: Colors.green.shade50,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.green.shade300),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.fiber_manual_record,
                            size: 8, color: Colors.green.shade700),
                        const SizedBox(width: 6),
                        Text(
                          'LIVE',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: Colors.green.shade800,
                          ),
                        ),
                      ],
                    ),
                  ),
                IconButton(
                  tooltip: _live ? 'Pause live updates' : 'Resume live updates',
                  icon: Icon(_live ? Icons.pause : Icons.play_arrow),
                  onPressed: () {
                    setState(() => _live = !_live);
                    _syncPolling();
                  },
                ),
                IconButton(
                  tooltip: 'Refresh now',
                  icon: const Icon(Icons.refresh),
                  onPressed: _poll,
                ),
                IconButton(
                  tooltip: 'Clear view',
                  icon: const Icon(Icons.clear_all),
                  onPressed: _clear,
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              children: [
                FilterChip(
                  label: const Text('Reasoning only'),
                  selected: _reasoningOnly,
                  onSelected: (v) {
                    setState(() {
                      _reasoningOnly = v;
                      _clear();
                    });
                    _poll();
                  },
                ),
                const SizedBox(width: 8),
                Text(
                  '${_spans.length} events',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          SizedBox(
            height: widget.maxHeight,
            child: _spans.isEmpty
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.hourglass_empty,
                            size: 40, color: Colors.grey.shade400),
                        const SizedBox(height: 8),
                        Text(
                          widget.emptyHint ??
                              (_live
                                  ? 'Waiting for agent activity…\nRun phase in Cursor with hooks enabled.'
                                  : 'No events yet'),
                          textAlign: TextAlign.center,
                          style: TextStyle(color: Colors.grey.shade600),
                        ),
                      ],
                    ),
                  )
                : Scrollbar(
                    controller: _scroll,
                    thumbVisibility: true,
                    child: SingleChildScrollView(
                      controller: _scroll,
                      padding: const EdgeInsets.all(12),
                      child: PlainThoughtView(
                        lines: PlainThoughtFormatter.format(_spans),
                        isLive: _live && widget.enableLivePoll,
                      ),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}
