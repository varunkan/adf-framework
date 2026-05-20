import 'orchestration_paths.dart';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

/// Appends OpenTelemetry-style JSONL spans for orchestration runner events.
class TraceWriter {
  TraceWriter(this.repoRoot);

  final String repoRoot;
  static final _rnd = Random();

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
