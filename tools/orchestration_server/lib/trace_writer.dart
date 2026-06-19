import 'orchestration_paths.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

/// Appends OpenTelemetry-style JSONL spans for orchestration runner events.
class TraceWriter {
  TraceWriter(this.repoRoot);

  final String repoRoot;
  static final _rnd = Random();

  /// Live push channel: every appended span is broadcast here so an SSE endpoint
  /// (GET /features/<id>/events) can tail spans in real time. The durable JSONL
  /// stays the source of truth + reconnect backfill; this push is fire-and-forget
  /// and process-wide (broadcast → any number of SSE clients, dropped if none).
  /// Records carry attributes['orch.feature_id'] for per-feature filtering.
  static final StreamController<Map<String, dynamic>> _events =
      StreamController<Map<String, dynamic>>.broadcast();
  static Stream<Map<String, dynamic>> get events => _events.stream;

  /// Format one span record as a Server-Sent-Events frame (id + data lines). The
  /// span_id doubles as the SSE Last-Event-ID so a reconnecting client can resume.
  static List<int> sseEvent(Map<String, dynamic> record) {
    final id = record['span_id'] ?? '';
    return utf8.encode('id: $id\ndata: ${jsonEncode(record)}\n\n');
  }

  void append({
    required String featureId,
    required String name,
    required String event,
    int? phase,
    String? message,
    String? reasoning,
    Map<String, dynamic>? extra,
  }) {
    final now = DateTime.now().toUtc().toIso8601String();
    final spanId = _hexId(16);
    final attrs = <String, dynamic>{
      'orch.feature_id': featureId,
      'hook.event': event,
      if (phase != null) 'orch.phase': phase,
      if (message != null && message.isNotEmpty) 'orch.message': message,
      if (reasoning != null && reasoning.isNotEmpty)
        'agent.reasoning': reasoning,
      if (extra != null) ...extra,
    };

    final record = <String, dynamic>{
      'timestamp': now,
      'trace_id': _hexId(32),
      'span_id': spanId,
      'name': name,
      'kind': 'INTERNAL',
      'status': 'OK',
      'attributes': attrs,
    };

    final line = '${jsonEncode(record)}\n';
    _appendLine(
      OrchestrationPaths(repoRoot).otelTracesFile,
      line,
    );
    _appendLine(
      OrchestrationPaths(repoRoot).featureOtelTracesFile(featureId),
      line,
    );
    // Push the span live to any SSE subscriber (broadcast → dropped if none).
    _events.add(record);
  }

  void _appendLine(String path, String line) {
    final file = File(path);
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(line, mode: FileMode.append);
  }

  String _hexId(int length) {
    const chars = '0123456789abcdef';
    return List.generate(length, (_) => chars[_rnd.nextInt(16)]).join();
  }
}
