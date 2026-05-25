import 'dart:convert';

import 'feature_store.dart';

/// Builds human-readable conversation from run-log, commands, and last-agent-response.
class ConversationBuilder {
  ConversationBuilder(this.store);

  final FeatureStore store;

  List<Map<String, dynamic>> build(String featureId, {int limit = 100}) {
    final messages = <Map<String, dynamic>>[];
    final lastResponse = store.readLastAgentResponse(featureId);

    final entries = store.readRunLog(featureId, limit: 500);

    for (final entry in entries) {
      final stream = entry['stream'] as String?;
      final raw = entry['message'] as String? ?? '';
      final ts = entry['timestamp'] as String?;

      if (stream == 'command') {
        messages.add({
          'role': 'system',
          'type': 'command',
          'text': raw,
          'timestamp': ts,
        });
        continue;
      }

      if (stream == 'stderr' || entry['level'] == 'error') {
        messages.add({
          'role': 'system',
          'type': 'error',
          'text': raw,
          'timestamp': ts,
        });
        continue;
      }

      if (stream != 'stdout' && stream != 'self_heal') continue;

      if (raw.contains('last-agent-response.md')) continue;

      Map<String, dynamic>? obj;
      try {
        obj = jsonDecode(raw) as Map<String, dynamic>;
      } catch (_) {
        continue;
      }

      final type = obj['type'] as String?;

      if (type == 'result') {
        final resultText = obj['result'] as String? ?? '';
        final isError = obj['is_error'] == true || obj['subtype'] == 'error';
        if (resultText.trim().isNotEmpty) {
          messages.add({
            'role': 'assistant',
            'type': isError ? 'error' : 'result',
            'text': resultText.trim(),
            'timestamp': ts,
            'duration_ms': obj['duration_ms'],
          });
        }
        continue;
      }

      if (type == 'assistant') continue;

      if (type == 'tool_call' || type == 'tool_result') {
        messages.add({
          'role': 'tool',
          'type': type,
          'text': _formatToolEvent(obj),
          'timestamp': ts,
        });
        continue;
      }

      if (type == 'system') {
        final text = _extractAssistantText(obj) ?? raw;
        if (text.trim().isNotEmpty) {
          messages.add({
            'role': 'system',
            'type': 'system',
            'text': text.trim(),
            'timestamp': ts,
          });
        }
      }
    }

    for (final cmd in store.listCommands(featureId, limit: 100)) {
      final prompt = cmd['prompt'] as String? ?? '';
      if (prompt.trim().isEmpty) continue;
      messages.add({
        'role': 'user',
        'type': 'command',
        'text': prompt.trim(),
        'timestamp': cmd['created_at'] as String?,
        'command_id': cmd['id'],
        'status': cmd['status'],
      });
      final ar = cmd['assistant_reply'] as String?;
      if (ar != null && ar.trim().isNotEmpty) {
        messages.add({
          'role': 'assistant',
          'type': 'orchestrator',
          'text': ar.trim(),
          'timestamp': cmd['created_at'] as String?,
          'command_id': cmd['id'],
          'llm_source': cmd['llm_source'],
        });
      }
    }

    if (lastResponse != null && lastResponse.isNotEmpty) {
      final hasSame = messages.any(
        (m) =>
            m['role'] == 'assistant' &&
            m['type'] == 'result' &&
            m['text'] == lastResponse,
      );
      if (!hasSame) {
        messages.add({
          'role': 'assistant',
          'type': 'result',
          'text': lastResponse,
          'timestamp': DateTime.now().toUtc().toIso8601String(),
        });
      }
    }

    messages.sort((a, b) {
      final ta = a['timestamp'] as String? ?? '';
      final tb = b['timestamp'] as String? ?? '';
      return ta.compareTo(tb);
    });

    final deduped = <Map<String, dynamic>>[];
    for (final m in messages) {
      if (deduped.isNotEmpty &&
          m['type'] == 'result' &&
          deduped.last['type'] == 'result' &&
          deduped.last['text'] == m['text']) {
        continue;
      }
      if (deduped.isNotEmpty &&
          m['role'] == 'user' &&
          m['type'] == 'command' &&
          deduped.last['role'] == 'user' &&
          deduped.last['text'] == m['text'] &&
          deduped.last['timestamp'] == m['timestamp']) {
        continue;
      }
      deduped.add(m);
    }

    if (deduped.length > limit) {
      return deduped.sublist(deduped.length - limit);
    }
    return deduped;
  }

  String? _extractAssistantText(Map<String, dynamic> obj) {
    if (obj['text'] is String) return obj['text'] as String;
    final msg = obj['message'];
    if (msg is Map) {
      final content = msg['content'];
      if (content is List) {
        final buf = StringBuffer();
        for (final block in content) {
          if (block is Map && block['type'] == 'text' && block['text'] is String) {
            buf.write(block['text']);
          }
        }
        if (buf.isNotEmpty) return buf.toString();
      }
    }
    final delta = obj['delta'];
    if (delta is Map && delta['text'] is String) return delta['text'] as String;
    return null;
  }

  String _formatToolEvent(Map<String, dynamic> obj) {
    final name = obj['tool_name'] ?? obj['name'] ?? 'tool';
    final input = obj['input'] ?? obj['arguments'];
    final output = obj['output'] ?? obj['result'];
    final buf = StringBuffer('Tool: $name');
    if (input != null) {
      buf.writeln('\nInput: ${_truncate('$input', 800)}');
    }
    if (output != null) {
      buf.writeln('Output: ${_truncate('$output', 800)}');
    }
    return buf.toString();
  }

  String _truncate(String s, int max) {
    if (s.length <= max) return s;
    return '${s.substring(0, max)}…';
  }
}
