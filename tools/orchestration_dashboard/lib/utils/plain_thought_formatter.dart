import '../models/trace_span.dart';
import 'thought_sanitizer.dart';
import 'tool_narration.dart';

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
        // Cursor-style: keep prose, rewrite raw code/SQL/shell to plain English.
        final clean = ThoughtSanitizer.clean(part);
        if (clean != null) _addLine(lines, clean);
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
        final clean = ThoughtSanitizer.clean(text);
        if (clean == null) continue;
        flushReasoning();
        _addLine(lines, clean);
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

  static String _toolLine(TraceSpan span) =>
      ToolNarration.humanize(span.toolName, span.toolInput);

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
