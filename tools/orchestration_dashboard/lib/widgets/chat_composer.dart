import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../main.dart';
import '../theme/orchestration_colors.dart';

class ChatComposer extends StatefulWidget {
  const ChatComposer({
    super.key,
    required this.runnerReady,
    required this.onSend,
    this.initialPrompt,
    this.quickActions = const [],
    this.enabled = true,
    this.hintText = 'Message the orchestrator…',
  });

  final bool runnerReady;
  final Future<void> Function(String prompt) onSend;
  final String? initialPrompt;
  final List<Map<String, String>> quickActions;
  final bool enabled;
  final String hintText;

  @override
  State<ChatComposer> createState() => _ChatComposerState();
}

class _ChatComposerState extends State<ChatComposer> {
  late final TextEditingController _controller;
  final FocusNode _focusNode = FocusNode();
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialPrompt ?? '');
  }

  @override
  void didUpdateWidget(ChatComposer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialPrompt != null &&
        widget.initialPrompt != oldWidget.initialPrompt &&
        _controller.text.isEmpty) {
      _controller.text = widget.initialPrompt!;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty) {
      showMessage(context, 'Enter a message');
      return;
    }
    if (!widget.runnerReady) {
      showMessage(context, 'Complete Cursor agent setup first');
      return;
    }
    final sent = text;
    _controller.clear();
    setState(() => _sending = true);
    try {
      await widget.onSend(sent);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _applyQuickAction(String prompt) {
    _controller.text = prompt;
    _focusNode.requestFocus();
  }

  KeyEventResult _handleKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) return KeyEventResult.ignored;
    if (event.logicalKey == LogicalKeyboardKey.enter &&
        !HardwareKeyboard.instance.isShiftPressed) {
      _send();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final spacing = context.orchSpacing;

    return Material(
      elevation: 8,
      color: scheme.surface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: EdgeInsets.fromLTRB(spacing.lg, spacing.sm, spacing.lg, spacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (widget.quickActions.isNotEmpty)
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (final action in widget.quickActions.take(6))
                        Padding(
                          padding: EdgeInsets.only(right: spacing.sm),
                          child: ActionChip(
                            label: Text(
                              action['label'] ?? '',
                              style: const TextStyle(fontSize: 12),
                            ),
                            onPressed: widget.enabled && !_sending
                                ? () => _applyQuickAction(action['prompt'] ?? '')
                                : null,
                          ),
                        ),
                    ],
                  ),
                ),
              if (widget.quickActions.isNotEmpty) SizedBox(height: spacing.sm),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: Focus(
                      onKeyEvent: _handleKey,
                      child: TextField(
                        controller: _controller,
                        focusNode: _focusNode,
                        enabled: widget.enabled && !_sending,
                        maxLines: 5,
                        minLines: 1,
                        decoration: InputDecoration(
                          hintText: widget.hintText,
                          helperText: 'Enter to send · Shift+Enter for newline',
                          helperStyle: TextStyle(
                            fontSize: 11,
                            color: scheme.onSurfaceVariant,
                          ),
                        ),
                      ),
                    ),
                  ),
                  SizedBox(width: spacing.sm),
                  IconButton(
                    tooltip: 'Copy',
                    onPressed: () async {
                      final t = _controller.text.trim();
                      if (t.isEmpty) return;
                      await Clipboard.setData(ClipboardData(text: t));
                      if (context.mounted) showMessage(context, 'Copied');
                    },
                    icon: const Icon(Icons.copy_outlined),
                  ),
                  FilledButton(
                    onPressed: widget.enabled && !_sending && widget.runnerReady
                        ? _send
                        : null,
                    child: _sending
                      ? Icon(Icons.hourglass_top_outlined, size: 20, color: scheme.onPrimary)
                      : const Icon(Icons.send_rounded),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
