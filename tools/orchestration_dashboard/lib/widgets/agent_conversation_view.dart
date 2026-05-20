import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../models/trace_span.dart';
import '../services/api_client.dart';
import '../theme/orchestration_colors.dart';
import '../utils/plain_thought_formatter.dart';
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
  final Set<String> _seenKeys = {};
  Timer? _pollTimer;
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
    _startPolling();
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
      _startPolling();
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    if (widget.scrollController == null) {
      _internalScroll.dispose();
    }
    super.dispose();
  }

  void _resetLiveStream() {
    setState(() {
      _liveSpans.clear();
      _seenKeys.clear();
      _since = widget.liveTraceSince;
    });
  }

  void _startPolling() {
    _pollTimer?.cancel();
    if (!_canPoll) return;

    if (_shouldPollLive) {
      _pollTraces();
      _pollTimer = Timer.periodic(
        const Duration(milliseconds: 400),
        (_) => _pollTraces(),
      );
    } else {
      if (_wasRunning) {
        _pollTraces();
      }
    }
    _wasRunning = _shouldPollLive;
  }

  Future<void> _pollTraces({bool initial = false}) async {
    if (!_canPoll) return;
    try {
      final data = await widget.api!.fetchTraces(
        widget.featureId!,
        since: initial ? null : _since,
        limit: initial ? 80 : 300,
      );
      final raw = data['traces'] as List<dynamic>? ?? [];
      final incoming =
          raw.cast<Map<String, dynamic>>().map(TraceSpan.fromJson).toList();
      final novel = <TraceSpan>[];
      for (final span in incoming) {
        if (span.isRunnerControlEvent) continue;
        final key = '${span.timestamp}|${span.name}|${span.body.hashCode}';
        if (_seenKeys.add(key)) novel.add(span);
      }
      if (novel.isNotEmpty && mounted) {
        setState(() {
          _liveSpans.addAll(novel);
          _since = data['last_timestamp'] as String? ?? novel.last.timestamp;
        });
        _scrollToBottom();
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

    final showChain = widget.isRunning &&
        !widget.needsRevision &&
        _liveSpans.isNotEmpty;
    final showWaiting = widget.isRunning &&
        _liveSpans.isEmpty &&
        _canPoll &&
        !widget.needsRevision;

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
                  label: 'Live',
                  color: status.running,
                  bg: status.runningBg,
                  pulse: true,
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
      return PlainThoughtView(
        lines: _plainThoughtLines,
        // During revision gates, avoid “infinite spinner” feel while agent works.
        isLive: widget.isRunning && !widget.needsRevision,
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
          Icon(Icons.hourglass_empty_outlined, size: 18, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              _showSpinner
                  ? 'Waiting for trace output from the agent…'
                  : 'Agent is working (stream quiet). Your message is already saved — you can send another or use Cancel run.',
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
              'No messages yet',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              'Send a message — reasoning and tool steps appear here live.',
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
