import '../models/trace_span.dart';

/// Formats trace spans as plain Cursor-style thought lines (no badges/cards).
class PlainThoughtFormatter {
  /// One line per thought paragraph or tool action.
  static List<String> format(List<TraceSpan> spans) {
    final lines = <String>[];
    final reasoningAcc = StringBuffer();

    void flushReasoning() {
      final raw = reasoningAcc.toString();
      reasoningAcc.clear();
      final normalized = raw.replaceAll(RegExp(r'\s+'), ' ').trim();
      if (normalized.length < 8) return;

      for (final part in _splitIntoThoughts(normalized)) {
        _addLine(lines, part);
      }
    }

    for (final span in spans) {
      if (span.isRunnerControlEvent) continue;

      final kind = span.displayKind;

      if (kind == 'REASONING') {
        final text = (span.reasoning ?? '').trim();
        if (text.isEmpty) continue;
        reasoningAcc.write(text);
        continue;
      }

      if (kind == 'RESPONSE') {
        final text = (span.reasoning ?? span.body).trim();
        if (text.length > 400) continue;
        flushReasoning();
        _addLine(lines, text);
        continue;
      }

      if (kind == 'TOOL') {
        flushReasoning();
        _addLine(lines, _toolLine(span));
        continue;
      }

      if (kind == 'SESSION') continue;

      final body = span.body.trim();
      if (body.isNotEmpty && body.length < 200 && kind == 'EVENT') {
        flushReasoning();
        _addLine(lines, body);
      }
    }

    flushReasoning();
    return lines;
  }

  static List<String> _splitIntoThoughts(String text) {
    if (text.length < 100) return [text];

    final parts = <String>[];
    final re = RegExp(r'(?<=[.!?])\s+(?=[A-Z])');
    var start = 0;
    for (final m in re.allMatches(text)) {
      final chunk = text.substring(start, m.start).trim();
      if (chunk.length >= 12) parts.add(chunk);
      start = m.end;
    }
    final tail = text.substring(start).trim();
    if (tail.length >= 12) parts.add(tail);

    if (parts.isEmpty) return [text];
    return parts;
  }

  static String _toolLine(TraceSpan span) {
    final name = span.toolName ?? 'tool';
    final input = span.toolInput;
    if (input != null && input.isNotEmpty) {
      final short = _shortToolInput(input);
      if (short != null) return 'Using $name · $short';
    }
    return 'Using $name';
  }

  static String? _shortToolInput(String input) {
    try {
      final m = RegExp(r'"file_path"\s*:\s*"([^"]+)"').firstMatch(input);
      if (m != null) {
        final path = m.group(1)!;
        final parts = path.split('/');
        return parts.length > 3 ? '…/${parts.sublist(parts.length - 3).join('/')}' : path;
      }
    } catch (_) {}
    if (input.length <= 60) return input;
    return '${input.substring(0, 57)}…';
  }

  static void _addLine(List<String> lines, String line) {
    var t = line.trim();
    if (t.isEmpty) return;

    t = t.replaceAll(RegExp(r'\s+'), ' ');

    if (lines.isNotEmpty) {
      final last = lines.last;
      if (t == last) return;
      if (last.startsWith(t) && last.length > t.length) return;
      if (t.startsWith(last)) {
        lines[lines.length - 1] = t;
        return;
      }
    }
    lines.add(t);
  }
}
