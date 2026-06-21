import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../models/trace_span.dart';
import '../services/api_client.dart';
import '../services/live_trace_client.dart';
import '../services/sse_connector_stub.dart'
    if (dart.library.html) '../services/sse_connector_web.dart';
import '../theme/orchestration_colors.dart';
import '../utils/plain_thought_formatter.dart';
import '../utils/live_span_cap.dart';
import 'activity_card.dart';
import 'plain_thought_view.dart';

/// Chat + live chain-of-thought (polls traces while agent runs).
class AgentConversationView extends StatefulWidget {
  const AgentConversationView({
    super.key,
    required this.messages,
    this.api,
    this.featureId,
    this.scrollController,
    this.isRunning = false,
    this.sessionEnded = false,
    this.awaitingApproval = false,
    this.needsRevision = false,
    this.liveTraceSince,
    this.onStartPipeline,
    this.canStartPipeline = false,
  });

  final List<Map<String, dynamic>> messages;
  final ApiClient? api;
  final String? featureId;
  final ScrollController? scrollController;
  final bool isRunning;
  final bool sessionEnded;
  final bool awaitingApproval;
  final bool needsRevision;
  /// Only ingest traces at/after this ISO timestamp during live polling.
  final String? liveTraceSince;
  final VoidCallback? onStartPipeline;
  final bool canStartPipeline;

  @override
  State<AgentConversationView> createState() => _AgentConversationViewState();
}

class _AgentConversationViewState extends State<AgentConversationView> {
  final List<TraceSpan> _liveSpans = [];
  /// Runner-control spans (runner.* / file.write) — rendered as typed cards.
  final List<TraceSpan> _activitySpans = [];
  final Set<String> _seenKeys = {};
  LiveTraceClient? _live;
  StreamSubscription<LiveState>? _connSub;
  LiveState _connState = LiveState.idle;
  String? _since;
  bool _wasRunning = false;

  ScrollController get _scroll =>
      widget.scrollController ?? _internalScroll;
  final ScrollController _internalScroll = ScrollController();

  bool get _canPoll =>
      widget.api != null &&
      widget.featureId != null &&
      widget.featureId!.isNotEmpty;

  /// Live trace polling only while agent is active and revision gate is not blocking UI.
  bool get _shouldPollLive =>
      widget.isRunning &&
      !widget.needsRevision &&
      !widget.sessionEnded;

  @override
  void initState() {
    super.initState();
    _startLive();
  }

  @override
  void didUpdateWidget(AgentConversationView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.isRunning && !oldWidget.isRunning) {
      _resetLiveStream();
    }
    if (widget.messages.length != oldWidget.messages.length) {
      _scrollToBottom();
    }
    if (widget.isRunning != oldWidget.isRunning ||
        widget.needsRevision != oldWidget.needsRevision ||
        widget.sessionEnded != oldWidget.sessionEnded) {
      _startLive();
    }
  }

  @override
  void dispose() {
    _stopLive();
    if (widget.scrollController == null) {
      _internalScroll.dispose();
    }
    super.dispose();
  }

  void _resetLiveStream() {
    setState(() {
      _liveSpans.clear();
      _activitySpans.clear();
      _seenKeys.clear();
      _since = widget.liveTraceSince;
    });
  }

  void _startLive() {
    _stopLive();
    if (!_canPoll) {
      _wasRunning = false;
      return;
    }
    if (_shouldPollLive) {
      final api = widget.api!;
      // SSE push first (self-healing client); degrades to the /traces poll on its
      // own if SSE can't hold, so the conversation never goes dark.
      _live = LiveTraceClient(
        uri: Uri.parse('${api.baseUrl}/features/${widget.featureId}/events'),
        since: _since,
        connect: connectSse,
        poll: ({since}) async {
          final data = await api.fetchTraces(
            widget.featureId!,
            since: since,
            limit: 300,
          );
          return (data['traces'] as List<dynamic>? ?? [])
              .cast<Map<String, dynamic>>();
        },
        onSpan: _ingestSpan,
      );
      _connSub = _live!.state.listen((s) {
        if (mounted) setState(() => _connState = s);
      });
      _live!.start();
    } else if (_wasRunning) {
      // The run just ended — one catch-up fetch so the final spans land.
      _catchUpPoll();
    }
    _wasRunning = _shouldPollLive;
  }

  void _stopLive() {
    _connSub?.cancel();
    _connSub = null;
    _live?.stop();
    _live = null;
    _connState = LiveState.idle;
  }

  /// Ingest ONE span (SSE push or poll fallback), de-duplicated, routing
  /// runner-control events (runner.* / file.write) to the typed-card list and the
  /// rest to the prose list — so the existing conversation rendering is preserved.
  void _ingestSpan(Map<String, dynamic> raw) {
    if (!mounted) return;
    final span = TraceSpan.fromJson(raw);
    final key = '${span.timestamp}|${span.name}|${span.body.hashCode}';
    if (!_seenKeys.add(key)) return; // dedup (survives reconnect backfill)
    setState(() {
      if (span.isRunnerControlEvent || span.name == 'file.write') {
        // Typed card — but drop control noise (cardKind HIDDEN), exactly as the
        // prose formatter already filters out runner.superseded / cancel.
        if (span.cardKind != 'HIDDEN') capLiveSpans(_activitySpans..add(span));
      } else {
        capLiveSpans(_liveSpans..add(span)); // bound the tail over a long build
      }
      if (span.timestamp.isNotEmpty) _since = span.timestamp;
    });
    _scrollToBottom();
  }

  Future<void> _catchUpPoll() async {
    if (!_canPoll) return;
    try {
      final data = await widget.api!.fetchTraces(
        widget.featureId!,
        since: _since,
        limit: 300,
      );
      for (final raw in (data['traces'] as List<dynamic>? ?? [])) {
        _ingestSpan(raw as Map<String, dynamic>);
      }
    } catch (_) {}
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 150),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final status = context.orchStatus;
    final spacing = context.orchSpacing;

    final hasActivity = _liveSpans.isNotEmpty || _activitySpans.isNotEmpty;
    final showChain =
        widget.isRunning && !widget.needsRevision && hasActivity;
    final showWaiting = widget.isRunning &&
        !hasActivity &&
        _canPoll &&
        !widget.needsRevision;
    // Transport health (monitoring): map the live connection state to the chip.
    final connLabel = switch (_connState) {
      LiveState.connecting => 'Connecting…',
      LiveState.reconnecting => 'Reconnecting…',
      LiveState.polling => 'Polling',
      _ => 'Live',
    };
    final connLive =
        _connState == LiveState.live || _connState == LiveState.idle;
    final connColor = connLive ? status.running : status.awaiting;
    final connBg = connLive ? status.runningBg : status.awaitingBg;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: EdgeInsets.fromLTRB(
            spacing.lg,
            spacing.md,
            spacing.lg,
            spacing.sm,
          ),
          child: Row(
            children: [
              Icon(Icons.forum_outlined, size: 20, color: scheme.primary),
              SizedBox(width: spacing.sm),
              Text(
                'Conversation',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
              ),
              const Spacer(),
              if (widget.isRunning && _canPoll && !widget.needsRevision)
                _StatusChip(
                  label: connLabel,
                  color: connColor,
                  bg: connBg,
                  pulse: _connState == LiveState.live ||
                      _connState == LiveState.connecting,
                )
              else if (widget.needsRevision)
                _StatusChip(
                  label: 'Revision needed',
                  color: status.error,
                  bg: status.errorBg,
                )
              else if (widget.awaitingApproval)
                _StatusChip(
                  label: 'Ready to approve',
                  color: status.awaiting,
                  bg: status.awaitingBg,
                )
              else if (widget.sessionEnded)
                _StatusChip(
                  label: 'Session ended',
                  color: status.idle,
                  bg: status.idleBg,
                ),
            ],
          ),
        ),
        Expanded(
          child: widget.messages.isEmpty && !showChain && !showWaiting
              ? _EmptyState(
                  canStart: widget.canStartPipeline,
                  onStart: widget.onStartPipeline,
                )
              : ListView.builder(
                  controller: _scroll,
                  padding: EdgeInsets.symmetric(
                    horizontal: spacing.lg,
                    vertical: spacing.sm,
                  ),
                  itemCount: _itemCount(showChain, showWaiting),
                  itemBuilder: (context, index) =>
                      _buildItem(context, index, showChain, showWaiting),
                ),
        ),
      ],
    );
  }

  List<String> get _plainThoughtLines =>
      PlainThoughtFormatter.format(_liveSpans);

  int _itemCount(bool showChain, bool showWaiting) {
    var n = widget.messages.length;
    if (showChain) {
      n += 1;
    } else if (showWaiting) {
      n += 1;
    }
    return n;
  }

  Widget _buildItem(
    BuildContext context,
    int index,
    bool showChain,
    bool showWaiting,
  ) {
    if (index < widget.messages.length) {
      return _MessageBubble(message: widget.messages[index]);
    }
    var i = index - widget.messages.length;

    if (showChain && i == 0) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_activitySpans.isNotEmpty)
            LiveActivityList(spans: _activitySpans),
          if (_liveSpans.isNotEmpty)
            PlainThoughtView(
              lines: _plainThoughtLines,
              // During revision gates, avoid an “infinite spinner” feel.
              isLive: widget.isRunning && !widget.needsRevision,
            ),
        ],
      );
    }
    if (showChain) i -= 1;

    if (showWaiting && i == 0) {
      return const _WaitingForThoughts();
    }
    return const SizedBox.shrink();
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({
    required this.label,
    required this.color,
    required this.bg,
    this.pulse = false,
  });

  final String label;
  final Color color;
  final Color bg;
  final bool pulse;

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: pulse
          ? Icon(Icons.fiber_manual_record, size: 10, color: color)
          : null,
      label: Text(label, style: TextStyle(fontSize: 11, color: color)),
      backgroundColor: bg,
      side: BorderSide(color: color.withValues(alpha: 0.4)),
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.zero,
    );
  }
}

class _WaitingForThoughts extends StatefulWidget {
  const _WaitingForThoughts();

  @override
  State<_WaitingForThoughts> createState() => _WaitingForThoughtsState();
}

class _WaitingForThoughtsState extends State<_WaitingForThoughts> {
  bool _showSpinner = true;

  @override
  void initState() {
    super.initState();
    Future<void>.delayed(const Duration(seconds: 8), () {
      if (mounted) setState(() => _showSpinner = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final status = context.orchStatus;
    final color = status.running;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.auto_awesome_outlined, size: 18, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              _showSpinner
                  ? 'ADF is working on your feature…'
                  : 'Still working — this can take up to a minute. Your message is saved; you can send another or cancel the run.',
              style: TextStyle(fontSize: 12, color: color),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({this.canStart = false, this.onStart});

  final bool canStart;
  final VoidCallback? onStart;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.chat_outlined, size: 56, color: scheme.outline),
            const SizedBox(height: 16),
            Text(
              'Ready to build',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              'Describe what you want — ADF will spec, plan, test, and build it, '
              'narrating each step here.',
              textAlign: TextAlign.center,
              style: TextStyle(color: scheme.onSurfaceVariant),
            ),
            if (canStart && onStart != null) ...[
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: onStart,
                icon: const Icon(Icons.play_arrow),
                label: const Text('Start pipeline'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message});

  final Map<String, dynamic> message;

  @override
  Widget build(BuildContext context) {
    final role = message['role'] as String? ?? 'assistant';
    final type = message['type'] as String? ?? 'message';
    final text = message['text'] as String? ?? '';
    final ts = message['timestamp'] as String?;
    final time = ts != null && ts.length >= 19 ? ts.substring(11, 19) : '';

    final isUser = role == 'user';
    final latencyMs = (message['latency_ms'] as num?)?.toInt();
    final llmSource = message['llm_source'] as String?;
    final caption = isUser ? null : _replyCaption(latencyMs, llmSource);
    final isError = type == 'error';
    final isSystem = role == 'system' || (type == 'command' && !isUser);

    final status = context.orchStatus;
    final radii = context.orchRadii;

    Color bg;
    Color fg;
    IconData icon;
    String label;

    if (isError) {
      bg = status.errorBg;
      fg = status.error;
      icon = Icons.error_outline;
      label = 'Error';
    } else if (isUser) {
      bg = Theme.of(context).colorScheme.primaryContainer;
      fg = Theme.of(context).colorScheme.onPrimaryContainer;
      icon = Icons.person_outline;
      label = 'You';
    } else if (isSystem) {
      bg = status.idleBg;
      fg = status.idle;
      icon = Icons.terminal;
      label = type == 'command' ? 'Command' : 'System';
    } else if (type == 'orchestrator') {
      bg = status.awaitingBg;
      fg = status.awaiting;
      icon = Icons.auto_awesome_outlined;
      label = 'Orchestrator';
    } else {
      bg = status.successBg;
      fg = status.success;
      icon = Icons.smart_toy_outlined;
      label = type == 'result' ? 'Agent' : 'Agent';
    }

    final bubble = Container(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.sizeOf(context).width * 0.75,
      ),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(radii.bubble),
        border: Border.all(color: fg.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 14, color: fg),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 11,
                  color: fg,
                ),
              ),
              if (time.isNotEmpty) ...[
                const SizedBox(width: 8),
                Text(
                  time,
                  style: TextStyle(
                    fontSize: 10,
                    color: fg.withValues(alpha: 0.7),
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: 8),
          MarkdownBody(
            data: text.isEmpty ? '_(empty)_' : text,
            selectable: true,
            styleSheet: MarkdownStyleSheet(
              p: TextStyle(fontSize: 14, height: 1.45, color: fg),
            ),
          ),
          if (caption != null) ...[
            const SizedBox(height: 6),
            Text(
              caption,
              style: TextStyle(
                fontSize: 10,
                color: fg.withValues(alpha: 0.7),
              ),
            ),
          ],
        ],
      ),
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            CircleAvatar(
              radius: 14,
              backgroundColor: fg.withValues(alpha: 0.15),
              child: Icon(icon, size: 16, color: fg),
            ),
            const SizedBox(width: 8),
          ],
          Flexible(child: bubble),
          if (isUser) ...[
            const SizedBox(width: 8),
            CircleAvatar(
              radius: 14,
              backgroundColor: fg.withValues(alpha: 0.15),
              child: Icon(icon, size: 16, color: fg),
            ),
          ],
        ],
      ),
    );
  }
}

/// Caption like "12 ms · instant" for assistant replies; null when the
/// message carries no latency/source metadata.
String? _replyCaption(int? latencyMs, String? llmSource) {
  final parts = <String>[
    if (latencyMs != null) _formatLatency(latencyMs),
    if (llmSource != null && llmSource.isNotEmpty) _formatLlmSource(llmSource),
  ];
  return parts.isEmpty ? null : parts.join(' · ');
}

/// Sub-second latencies as "N ms", longer ones as "X.Y s".
String _formatLatency(int ms) =>
    ms < 1000 ? '$ms ms' : '${(ms / 1000).toStringAsFixed(1)} s';

/// Human label for a reply source: 'state' → "instant",
/// `ollama:<model>` → "model short-name (local)" (hf.co/... paths are
/// trimmed to the last segment, quant tags dropped),
/// 'cursor_agent' → "cursor agent"; anything else renders as-is.
String _formatLlmSource(String source) {
  if (source == 'state') return 'instant';
  if (source == 'cursor_agent') return 'cursor agent';
  if (source.startsWith('ollama:')) {
    var model = source.substring('ollama:'.length);
    final slash = model.lastIndexOf('/');
    if (slash != -1) model = model.substring(slash + 1);
    final tag = model.indexOf(':');
    if (tag != -1) model = model.substring(0, tag);
    return '$model (local)';
  }
  return source;
}
