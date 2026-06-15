import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiClient {
  ApiClient({
    this.baseUrl = 'http://127.0.0.1:3847',
    this.timeout = const Duration(seconds: 8),
    http.Client? client,
  }) : _client = client ?? http.Client();

  final String baseUrl;
  final Duration timeout;
  final http.Client _client;

  // ETag cache: unchanged polls cost a 304 with zero payload bytes.
  final Map<String, String> _etags = {};
  final Map<String, Map<String, dynamic>> _bodyCache = {};

  Future<http.Response> _get(String path, {Map<String, String>? headers}) async {
    try {
      return await _client
          .get(Uri.parse('$baseUrl$path'), headers: headers)
          .timeout(timeout);
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
      return await _client
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

  /// Lovable-style: create a feature from a single prompt (server generates id).
  Future<Map<String, dynamic>> createFromPrompt(
    String prompt, {
    String track = 'M',
    bool autopilot = true,
  }) async {
    final r = await _post('/features', {
      'prompt': prompt,
      'track': track,
      if (autopilot) 'autopilot': true,
    });
    if (r.statusCode != 201 && r.statusCode != 200) {
      throw Exception('create failed (${r.statusCode}): ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchHealth() async {
    final r = await _get('/health');
    if (r.statusCode != 200) {
      throw Exception('health failed (${r.statusCode}): ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
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
    final path = '/features/$id';
    final etag = _etags[path];
    final r = await _get(
      path,
      headers: etag != null ? {'If-None-Match': etag} : null,
    );
    if (r.statusCode == 304 && _bodyCache[path] != null) {
      _lastNotModified.add(id);
      return _bodyCache[path]!;
    }
    _lastNotModified.remove(id);
    if (r.statusCode == 404) throw Exception('Feature not found: $id');
    if (r.statusCode != 200) throw Exception(r.body);
    final body = jsonDecode(r.body) as Map<String, dynamic>;
    final newTag = r.headers['etag'];
    if (newTag != null) {
      _etags[path] = newTag;
      _bodyCache[path] = body;
    }
    return body;
  }

  /// True when the last [getFeature] for [id] was served from the 304 cache.
  bool wasNotModified(String id) => _lastNotModified.contains(id);
  final Set<String> _lastNotModified = {};

  /// Recompute the app's Proof of Build seal offline. Returns
  /// `{has_proof, ok, status:'VERIFIED'|'TAMPERED', seal, files, ...}`.
  Future<Map<String, dynamic>> getProof(String id) async {
    final r = await _get('/features/$id/proof');
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// The app's context budget: `{has_app, tokens, budget, over, n_files}`.
  Future<Map<String, dynamic>> getContext(String id) async {
    final r = await _get('/features/$id/context');
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Run the `/compact` fold over the app's context; returns the engine report.
  Future<Map<String, dynamic>> compact(String id) async {
    final r = await _post('/features/$id/compact', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Export the app as a portable, self-verifying zip (source + audit bundle +
  /// proof). Returns `{ok, out, files, bytes}`.
  Future<Map<String, dynamic>> exportApp(String id) async {
    final r = await _post('/features/$id/export', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// The app's live SQLite tables: `{has_db, tables:[{name, rows}]}`.
  Future<Map<String, dynamic>> getData(String id) async {
    final r = await _get('/features/$id/data');
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// One table's rows: `{columns:[...], rows:[[...]], truncated}`.
  Future<Map<String, dynamic>> getTableRows(String id, String table) async {
    final r = await _get('/features/$id/data/${Uri.encodeComponent(table)}');
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createFeature({
    required String id,
    required String requirement,
    required String track,
    String stack = 'react-vite-sqlite',
  }) async {
    final r = await _post('/features', {
      'id': id,
      'requirement': requirement,
      'track': track,
      'stack': stack,
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
    final r = await _client.get(uri).timeout(timeout);
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

  /// Zero-token autopilot: deterministic engine runs phases 1-6.

  Future<Map<String, dynamic>> getStudioPreview(String id, {int? phase}) async {
    final q = phase != null ? '?phase=$phase' : '';
    final r = await _get('/features/$id/studio-preview$q');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getIntegrity(String id, {bool strict = false}) async {
    final q = strict ? '?strict=true' : '';
    final r = await _get('/features/$id/integrity$q');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getFeatureCost(String id) async {
    final r = await _get('/features/$id/cost');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getCostSummary() async {
    final r = await _get('/cost/summary');
    if (r.statusCode != 200) throw Exception(r.body);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> getCrewLog(String id) async {
    final r = await _get('/features/$id/crew-log');
    if (r.statusCode != 200) throw Exception(r.body);
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return (data['agents'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ?? [];
  }

  /// Live build log lines (runner stdout: which model, attempts, tests).
  Future<List<Map<String, dynamic>>> getRunLog(String id, {int limit = 60}) async {
    final r = await _get('/features/$id/run-log?limit=$limit');
    if (r.statusCode != 200) throw Exception(r.body);
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return (data['entries'] as List<dynamic>?)?.cast<Map<String, dynamic>>() ?? [];
  }

  /// Reviewable artifacts grouped as {spec: [...], code: [...]}.
  Future<Map<String, dynamic>> listArtifacts(String id) async {
    final r = await _get('/features/$id/artifacts');
    if (r.statusCode != 200) throw Exception(r.body);
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return (data['artifacts'] as Map<String, dynamic>?) ?? {};
  }

  /// Text content of one artifact (path is the server-relative path).
  Future<String> getArtifact(String id, String path) async {
    final r = await _get('/features/$id/artifact?path=${Uri.encodeQueryComponent(path)}');
    if (r.statusCode != 200) throw Exception(_formatError(r));
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return (data['content'] as String?) ?? '';
  }

  Future<Map<String, dynamic>> runAutopilot(String id) async {
    final r = await _post('/features/$id/autopilot', {});
    if (r.statusCode != 200) {
      throw Exception('autopilot failed (${r.statusCode}): ${r.body}');
    }
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
    final r = await _client
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

  /// Live preview metadata: spec, integrity, crew, build status (ETag-aware).
  Future<Map<String, dynamic>> fetchPreview(String id, {int? phase}) async {
    final path = phase != null
        ? '/features/$id/preview?phase=$phase'
        : '/features/$id/preview';
    final etag = _etags[path];
    final r = await _get(
      path,
      headers: etag != null ? {'If-None-Match': etag} : null,
    );
    if (r.statusCode == 304 && _bodyCache[path] != null) {
      _lastPreviewNotModified.add(id);
      return _bodyCache[path]!;
    }
    _lastPreviewNotModified.remove(id);
    if (r.statusCode == 404) throw Exception('Feature not found: $id');
    if (r.statusCode != 200) throw Exception(r.body);
    final body = jsonDecode(r.body) as Map<String, dynamic>;
    final newTag = r.headers['etag'];
    if (newTag != null) {
      _etags[path] = newTag;
      _bodyCache[path] = body;
    }
    return body;
  }

  bool wasPreviewNotModified(String id) => _lastPreviewNotModified.contains(id);
  final Set<String> _lastPreviewNotModified = {};

  /// Kick off a background flutter web build (server feature-flagged).
  Future<Map<String, dynamic>> buildPreview(String id) async {
    final r = await _post('/features/$id/preview/build', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Launch (lazily) the built app's own server and return its live localhost
  /// URL so the dashboard can iframe the REAL running app.
  Future<Map<String, dynamic>> getAppPreview(String id) async {
    final r = await _get('/features/$id/app-preview');
    if (r.statusCode == 404) throw Exception('Feature not found: $id');
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Restart the live app after a rebuild so the preview reflects fresh code.
  Future<Map<String, dynamic>> restartAppPreview(String id) async {
    final r = await _post('/features/$id/app-preview/restart', {});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// One-box iteration: apply a free-text change to the built app and rebuild.
  /// Throws on 409 when there is no built app yet (caller falls back to chat).
  Future<Map<String, dynamic>> editApp(String id, String instruction) async {
    final r = await _post('/features/$id/edit', {'instruction': instruction});
    if (r.statusCode != 200) throw Exception(_formatError(r));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> sendCommand(
    String id, {
    required String prompt,
    String? stepId,
    bool execute = true,
  }) async {
    final r = await _client
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
