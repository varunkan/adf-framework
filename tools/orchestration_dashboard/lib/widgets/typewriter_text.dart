import 'dart:async';

import 'package:flutter/material.dart';

/// Reveals [text] character-by-character for the "watch it type" feel on the live,
/// actively-streaming line. Built for streaming input: when [text] GROWS (the next
/// token batch appends), it keeps the already-revealed prefix and types only the new
/// suffix; when [text] is replaced by an unrelated string (a new line), it retypes
/// from the start. It self-paces — a small steady step normally, a fast catch-up when
/// a burst leaves a large backlog — so the caret never lags far behind real tokens.
class TypewriterText extends StatefulWidget {
  const TypewriterText(
    this.text, {
    super.key,
    this.style,
    this.tick = const Duration(milliseconds: 24),
    this.minStep = 2,
    this.showCaret = true,
  });

  final String text;
  final TextStyle? style;
  final Duration tick;
  final int minStep;
  final bool showCaret;

  @override
  State<TypewriterText> createState() => _TypewriterTextState();
}

class _TypewriterTextState extends State<TypewriterText> {
  int _shown = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _run();
  }

  @override
  void didUpdateWidget(TypewriterText old) {
    super.didUpdateWidget(old);
    if (widget.text != old.text) {
      // A continuation (streaming append) keeps the revealed prefix; an unrelated
      // string (new line) retypes from zero.
      if (!widget.text.startsWith(old.text)) _shown = 0;
      _run();
    }
  }

  void _run() {
    _timer?.cancel();
    if (_shown >= widget.text.length) {
      _shown = widget.text.length;
      return;
    }
    _timer = Timer.periodic(widget.tick, (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      final remaining = widget.text.length - _shown;
      if (remaining <= 0) {
        t.cancel();
        return;
      }
      // Catch up fast when a burst left a big backlog, so we stay near live.
      final step = remaining > 120 ? (remaining ~/ 8) : widget.minStep;
      setState(() => _shown = (_shown + step).clamp(0, widget.text.length));
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final n = _shown.clamp(0, widget.text.length);
    final typing = n < widget.text.length;
    final shown = widget.text.substring(0, n);
    return Text(
      (typing && widget.showCaret) ? '$shown▍' : shown,
      style: widget.style,
    );
  }
}
