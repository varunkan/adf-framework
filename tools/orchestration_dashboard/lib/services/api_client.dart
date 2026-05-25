import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiClient {
  ApiClient({
    this.baseUrl = 'http://127.0.0.1:3847',
    this.timeout = const Duration(seconds: 8),
  });

  final String baseUrl;
  final Duration timeout;

  Future<http.Response> _get(String path) async {
    try {
      return await http.get(Uri.parse('$baseUrl$path')).timeout(timeout);
    } catch (e) {
      throw Exception(
        'Cannot reach API at $baseUrl$path — is the server running?\n'
        'Start: dart run tools/orchestration_server/bin/server.dart\n'
        '($e)',
      );
    }
  }

  Future<http.Response> _post(String path, Map<String, dynamic> body) async {
    try {
      return await http
          .post(
            Uri.parse('$baseUrl$path'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(timeout);
    } catch (e) {
      throw Exception(
        'Cannot reach API at $baseUrl$path — is the server running?\n'
        '($e)',
      );
    }
  }

  Future<bool> health() async {
    try {
      final r = await _get('/health');
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Returns features from REST plus [count] from the API response body.
  Future<({List<Map<String, dynamic>> features, int count})> listFeatures() async {
    final r = await _get('/features');
    if (r.statusCode != 200) {
      throw Exception('list features failed (${r.statusCode}): ${r.body}');
    }
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    final list = (data['features'] as List<dynamic>?)
            ?.cast<Map<String, dynamic>>() ??
        [];
    final count = (data['count'] as num?)?.toInt() ?? list.length;
    return (features: list, count: count);
  }

  Future<Map<String, dynamic>> getFeature(String id) async {
    final r = await _get('/features/$id');
    if (r.statusCode == 404) throw Exception('Feature not found: $id');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createFeature({
    required String id,
    required String requirement,
    required String track,
  }) async {
    final r = await _post('/features', {
      'id': id,
      'requirement': requirement,
      'track': track,
    });
    if (r.statusCode != 201 && r.statusCode != 200) {
      throw Exception(_formatError(r));
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> approve({
    required String id,
    required int phase,
    required String decision,
    String notes = '',
    bool judgeWaiver = false,
    bool artifactWaiver = false,
    bool clientConfirmed = false,
  }) async {
    final r = await _post('/features/$id/approve', {
      'phase': phase,
      'decision': decision,
      'notes': notes,
      'source': 'dashboard',
      'judge_waiver': judgeWaiver,
      if (artifactWaiver) 'artifact_waiver': true,
      if (clientConfirmed) 'client_confirmed': true,
    });
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchTraces(
    String id, {
    String? since,
    int limit = 100,
    String? event,
    int? phase,
    bool reasoningOnly = false,
  }) async {
    final q = <String, String>{
      'limit': '$limit',
      if (since != null && since.isNotEmpty) 'since': since,
      if (event != null) 'event': event,
      if (phase != null) 'phase': '$phase',
      if (reasoningOnly) 'reasoning_only': 'true',
    };
    final uri = Uri.parse('$baseUrl/features/$id/traces')
        .replace(queryParameters: q);
    final r = await http.get(uri).timeout(timeout);
    if (r.statusCode == 404) throw Exception('Feature not found');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<String> requestPhase(String id, {int? phase}) async {
    final r = await _post('/features/$id/request-phase', {
      if (phase != null) 'phase': phase,
      'auto_run': true,
    });
    if (r.statusCode != 200) throw Exception(_formatError(r));
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return data['cursor_prompt'] as String? ?? '@orch-orchestrator resume $id';
  }

  /// Start (or queue) headless phase execution via cursor-agent.
  Future<Map<String, dynamic>> runFeature(String id, {int? phase}) async {
    final r = await _post('/features/$id/run', {
      if (phase != null) 'phase': phase,
    });
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> syncState(String id) async {
    final r = await _post('/features/$id/sync-state', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> getConversation(String id) async {
    final r = await _get('/features/$id/conversation?limit=50');
    if (r.statusCode != 200) throw Exception(r.body);
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return (data['messages'] as List<dynamic>?)
            ?.cast<Map<String, dynamic>>() ??
        [];
  }

  Future<Map<String, dynamic>> triggerHeal(String id) async {
    final r = await _post('/features/$id/heal', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> retryRun(String id) async {
    final r = await _post('/features/$id/retry', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> cancelRun(String id) async {
    final r = await _post('/features/$id/cancel', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Clear phantom agent_active, stuck commands, and rejected+awaiting state.
  Future<Map<String, dynamic>> unstickFeature(String id) async {
    final r = await _post('/features/$id/unstick', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getRunnerHealth({bool refresh = false}) async {
    final path = refresh ? '/runner/health?refresh=true' : '/runner/health';
    final r = await http
        .get(Uri.parse('$baseUrl$path'))
        .timeout(const Duration(seconds: 30));
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getPipeline(String id) async {
    final r = await _get('/features/$id/pipeline');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getArtifactChecklist(
    String id, {
    int? phase,
  }) async {
    final q = phase != null ? '?phase=$phase' : '';
    final r = await _get('/features/$id/artifact-checklist$q');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> sendCommand(
    String id, {
    required String prompt,
    String? stepId,
    bool execute = true,
  }) async {
    final r = await http
        .post(
          Uri.parse('$baseUrl/features/$id/commands'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'prompt': prompt,
            if (stepId != null) 'step_id': stepId,
            'execute': execute,
          }),
        )
        .timeout(const Duration(seconds: 180));
    if (r.statusCode == 409) {
      final data = jsonDecode(r.body) as Map<String, dynamic>;
      throw Exception(data['error'] as String? ?? 'Runner not ready');
    }
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  String _formatError(http.Response r) {
    try {
      final data = jsonDecode(r.body) as Map<String, dynamic>;
      final err = data['error'] as String?;
      if (err != null) return err;
    } catch (_) {}
    return 'HTTP ${r.statusCode}: ${r.body}';
  }
}
