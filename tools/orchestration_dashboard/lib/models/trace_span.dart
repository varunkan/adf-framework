/// OTEL-shaped span from orchestration telemetry ingest.
class TraceSpan {
  TraceSpan({
    required this.timestamp,
    required this.name,
    required this.status,
    required this.attributes,
  });

  factory TraceSpan.fromJson(Map<String, dynamic> json) {
    return TraceSpan(
      timestamp: json['timestamp'] as String? ?? '',
      name: json['name'] as String? ?? 'unknown',
      status: json['status'] as String? ?? 'OK',
      attributes: Map<String, dynamic>.from(
        json['attributes'] as Map<String, dynamic>? ?? {},
      ),
    );
  }

  final String timestamp;
  final String name;
  final String status;
  final Map<String, dynamic> attributes;

  String? get hookEvent => attributes['hook.event'] as String?;
  int? get phase => (attributes['orch.phase'] as num?)?.toInt();
  String? get reasoning => attributes['agent.reasoning'] as String?;
  String? get response => attributes['agent.response'] as String?;
  String? get toolName => attributes['tool.name'] as String?;
  String? get toolInput => attributes['tool.input'] as String?;
  String? get toolOutput => attributes['tool.output'] as String?;
  String? get runnerMessage => attributes['runner.message'] as String?;

  bool get isRunnerControlEvent => name.startsWith('runner.');

  String get displayKind {
    if (reasoning != null && reasoning!.isNotEmpty) return 'REASONING';
    if (response != null && response!.isNotEmpty) return 'RESPONSE';
    if (toolName != null) return 'TOOL';
    if (name.startsWith('subagent.')) return 'SUBAGENT';
    if (hookEvent == 'sessionStart' || hookEvent == 'sessionEnd') {
      return 'SESSION';
    }
    return 'EVENT';
  }

  String get body {
    if (reasoning != null && reasoning!.isNotEmpty) return reasoning!;
    if (response != null && response!.isNotEmpty) return response!;
    if (toolName != null) {
      final buf = StringBuffer('Tool: $toolName');
      if (toolInput != null && toolInput!.isNotEmpty) {
        buf.writeln('\nInput: ${toolInput!.length > 500 ? '${toolInput!.substring(0, 500)}…' : toolInput}');
      }
      if (toolOutput != null && toolOutput!.isNotEmpty) {
        buf.writeln('Output: ${toolOutput!.length > 500 ? '${toolOutput!.substring(0, 500)}…' : toolOutput}');
      }
      return buf.toString();
    }
    if (runnerMessage != null && runnerMessage!.trim().isNotEmpty) {
      return runnerMessage!.trim();
    }
    return name;
  }

  String get shortTime {
    if (timestamp.length < 19) return timestamp;
    return timestamp.substring(11, 19);
  }
}
