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

  /// Canonical human-readable message attribute written by `TraceWriter`
  /// (`message:` → `orch.message`), e.g. the crew's "Wave 1: …" narration.
  String? get orchMessage => attributes['orch.message'] as String?;

  bool get isRunnerControlEvent => name.startsWith('runner.');

  // --- typed runner-event accessors (Layer 4) -------------------------------
  // Bind the live UI to the runner's STRUCTURED truth, never a string match.

  /// The runner event subtype, e.g. 'verify_stage_result' from
  /// 'runner.verify_stage_result'. Null for non-runner spans.
  String? get runnerType =>
      isRunnerControlEvent ? name.substring('runner.'.length) : null;

  /// The runner's real ok flag for a verdict event; null when absent/not a verdict.
  bool? get runnerOk =>
      attributes['runner.ok'] is bool ? attributes['runner.ok'] as bool : null;

  String? get runnerStage => attributes['runner.stage'] as String?;
  String? get runnerSeal => attributes['runner.seal'] as String?;
  String? get runnerPath => attributes['runner.path'] as String?;

  /// Typed kind for the Studio's live cards/pills. Additive — distinct from the
  /// legacy [displayKind] (kept intact for existing views). HONESTY: verdict kinds
  /// bind to [runnerOk] — a result is VERIFY_OK / POLICY_OK / DONE_OK only when
  /// runnerOk == true, so a missing or false flag can NEVER render as positive
  /// (green / sealed). A `sealed` span (SEAL) is only ever emitted by the runner
  /// after a real seal, and is never reachable on a policy-blocked build.
  String get cardKind {
    if (name == 'file.write') return 'FILE_WRITE';
    final t = runnerType;
    if (t == null) return displayKind;
    switch (t) {
      case 'verifying':
      case 'verify_stage':
        return 'VERIFY_RUN';
      case 'verify_stage_result':
      case 'verify_result':
        return runnerOk == true ? 'VERIFY_OK' : 'VERIFY_FAIL';
      case 'policy_gate':
        return runnerOk == true ? 'POLICY_OK' : 'POLICY_WARN';
      case 'policy_blocked':
        return 'BLOCKED';
      case 'sealing':
        return 'SEALING';
      case 'sealed':
        return 'SEAL';
      case 'generating':
      case 'generated':
        return 'GENERATE';
      case 'scaffolding':
      case 'scaffolded':
        return 'SCAFFOLD';
      case 'warming_deps':
      case 'deps_warm':
        return 'DEPS';
      case 'self_heal':
        return 'HEAL';
      case 'completion_audit':
        return 'AUDIT';
      case 'build_complete':
        return runnerOk == true ? 'DONE_OK' : 'DONE_FAIL';
      case 'building_apk':
      case 'emulator_preview':
        return 'MOBILE_RUN';
      case 'apk_built':
      case 'emulator_running':
        return 'MOBILE_OK';
      case 'apk_failed':
        return 'MOBILE_FAIL';
      case 'feature_resolved':
      case 'planning':
      case 'reading_files':
      case 'files_read':
      case 'writing_files':
      case 'files_written':
      case 'recall_injected':
      case 'component_manifest':
        return 'STEP';
      default:
        // Unknown runner control event (e.g. runner.superseded / cancel) — HIDDEN,
        // matching what the prose formatter already filters out. Never shown.
        return 'HIDDEN';
    }
  }

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
    if (orchMessage != null && orchMessage!.trim().isNotEmpty) {
      return orchMessage!.trim();
    }
    return name;
  }

  String get shortTime {
    if (timestamp.length < 19) return timestamp;
    return timestamp.substring(11, 19);
  }
}
