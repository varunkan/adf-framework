import 'dart:convert';

import 'http_proxy.dart';

/// Thrown by tool handlers when `tools/call` arguments are malformed; surfaces
/// to the client as JSON-RPC error -32602 (invalid params).
class McpInvalidParams implements Exception {
  const McpInvalidParams(this.message);

  final String message;

  @override
  String toString() => message;
}

/// One MCP tool: its advertised schema plus the orchestration-API call that
/// implements it.
class _ToolSpec {
  const _ToolSpec({
    required this.name,
    required this.description,
    required this.inputSchema,
    required this.call,
  });

  final String name;
  final String description;
  final Map<String, dynamic> inputSchema;
  final Future<Object?> Function(OrchHttpProxy api, Map<String, dynamic> args)
      call;

  Map<String, dynamic> toJson() => {
        'name': name,
        'description': description,
        'inputSchema': inputSchema,
      };
}

/// MCP server (stdio flavour) that exposes the ADF orchestration pipeline as
/// tools any MCP client can call.
///
/// Transport is newline-delimited JSON-RPC 2.0: one message per line on
/// [input], one reply per line on [output]. The class takes plain streams and
/// sinks (rather than touching stdin/stdout itself) so tests can drive it
/// fully in-memory without spawning a process.
class AdfMcpServer {
  AdfMcpServer({
    required Stream<String> input,
    required StringSink output,
    OrchHttpProxy? api,
  })  : _input = input,
        _output = output,
        api = api ?? OrchHttpProxy();

  final Stream<String> _input;
  final StringSink _output;

  /// HTTP proxy for the orchestration API; injectable for tests.
  final OrchHttpProxy api;

  /// Version offered when the client does not request one.
  static const fallbackProtocolVersion = '2025-06-18';

  static const serverName = 'adf-mcp';
  static const serverVersion = '3.2.0';

  /// Processes messages until [_input] closes.
  Future<void> serve() async {
    await for (final line in _input) {
      if (line.trim().isEmpty) continue;
      await _handleLine(line);
    }
  }

  Future<void> _handleLine(String line) async {
    Object? decoded;
    try {
      decoded = jsonDecode(line);
    } on FormatException catch (e) {
      _sendError(null, -32700, 'Parse error: ${e.message}');
      return;
    }
    if (decoded is! Map<String, dynamic>) {
      _sendError(null, -32600, 'Invalid request: expected a JSON-RPC object');
      return;
    }

    final id = decoded['id'];
    final isNotification = !decoded.containsKey('id');
    final method = decoded['method'];
    if (method is! String) {
      if (!isNotification) {
        _sendError(id, -32600, 'Invalid request: missing method');
      }
      return;
    }
    // Notifications (notifications/initialized, notifications/cancelled, ...)
    // never get a reply.
    if (method.startsWith('notifications/')) return;

    final params = decoded['params'] is Map<String, dynamic>
        ? decoded['params'] as Map<String, dynamic>
        : const <String, dynamic>{};

    Object? result;
    try {
      switch (method) {
        case 'initialize':
          result = _initialize(params);
        case 'ping':
          result = const <String, dynamic>{};
        case 'tools/list':
          result = {'tools': [for (final tool in _tools) tool.toJson()]};
        case 'tools/call':
          result = await _toolsCall(params);
        default:
          if (!isNotification) {
            _sendError(id, -32601, 'Method not found: $method');
          }
          return;
      }
    } on McpInvalidParams catch (e) {
      if (!isNotification) _sendError(id, -32602, e.message);
      return;
    }
    if (!isNotification) _sendResult(id, result);
  }

  Map<String, dynamic> _initialize(Map<String, dynamic> params) {
    final requested = params['protocolVersion'];
    return {
      'protocolVersion':
          requested is String ? requested : fallbackProtocolVersion,
      'capabilities': {'tools': <String, dynamic>{}},
      'serverInfo': {'name': serverName, 'version': serverVersion},
    };
  }

  Future<Map<String, dynamic>> _toolsCall(Map<String, dynamic> params) async {
    final name = params['name'];
    if (name is! String || name.isEmpty) {
      throw const McpInvalidParams("tools/call requires a string 'name'");
    }
    final spec = _toolIndex[name];
    if (spec == null) {
      throw McpInvalidParams(
          "Unknown tool '$name'. Call tools/list for the available adf_* tools.");
    }
    final rawArgs = params['arguments'];
    final args =
        rawArgs is Map<String, dynamic> ? rawArgs : const <String, dynamic>{};
    try {
      final payload = await spec.call(api, args);
      return _toolResult(jsonEncode(payload), isError: false);
    } on OrchApiException catch (e) {
      return _toolResult(e.message, isError: true);
    }
  }

  static Map<String, dynamic> _toolResult(String text,
          {required bool isError}) =>
      {
        'content': [
          {'type': 'text', 'text': text},
        ],
        'isError': isError,
      };

  void _sendResult(Object? id, Object? result) =>
      _send({'jsonrpc': '2.0', 'id': id, 'result': result});

  void _sendError(Object? id, int code, String message) => _send({
        'jsonrpc': '2.0',
        'id': id,
        'error': {'code': code, 'message': message},
      });

  void _send(Map<String, dynamic> message) =>
      _output.writeln(jsonEncode(message));

  // --- Tool definitions -----------------------------------------------------

  static const _emptySchema = <String, dynamic>{
    'type': 'object',
    'properties': <String, dynamic>{},
  };

  static Map<String, dynamic> _idSchema(String idDescription) => {
        'type': 'object',
        'properties': {
          'id': {'type': 'string', 'description': idDescription},
        },
        'required': ['id'],
      };

  static String _requireId(Map<String, dynamic> args) {
    final id = args['id'];
    if (id is! String || id.trim().isEmpty) {
      throw const McpInvalidParams(
          "Missing required string argument 'id' (a feature id, as returned "
          'by adf_list_features or adf_create_feature).');
    }
    return Uri.encodeComponent(id.trim());
  }

  static bool _optionalBool(
      Map<String, dynamic> args, String key, bool fallback) {
    final value = args[key];
    if (value == null) return fallback;
    if (value is bool) return value;
    throw McpInvalidParams("Argument '$key' must be a boolean.");
  }

  static final Map<String, _ToolSpec> _toolIndex = {
    for (final tool in _tools) tool.name: tool,
  };

  static final List<_ToolSpec> _tools = [
    _ToolSpec(
      name: 'adf_list_features',
      description:
          'List every feature in the ADF orchestration pipeline with its id, '
          'requirement, phase, and status. Call this first to discover the '
          'feature ids the other adf_* tools expect.',
      inputSchema: _emptySchema,
      call: (api, args) => api.getJson('/features'),
    ),
    _ToolSpec(
      name: 'adf_create_feature',
      description:
          'Create a new feature from a natural-language requirement and '
          'return its record, including the new feature id. Set '
          'autopilot=true to start the automated build pipeline immediately; '
          'with the default false the feature waits until you call '
          'adf_run_autopilot.',
      inputSchema: const {
        'type': 'object',
        'properties': {
          'requirement': {
            'type': 'string',
            'description':
                'What to build, in plain language (one feature per call).',
          },
          'autopilot': {
            'type': 'boolean',
            'description':
                'Start the pipeline immediately after creation. Default false.',
            'default': false,
          },
        },
        'required': ['requirement'],
      },
      call: (api, args) {
        final requirement = args['requirement'];
        if (requirement is! String || requirement.trim().isEmpty) {
          throw const McpInvalidParams(
              "Missing required string argument 'requirement'.");
        }
        return api.postJson('/features', {
          'requirement': requirement,
          'autopilot': _optionalBool(args, 'autopilot', false),
        });
      },
    ),
    _ToolSpec(
      name: 'adf_feature_status',
      description:
          'Fetch the full detail for one feature with its pipeline plan '
          "merged in under the 'pipeline' key: phases, gates, artifacts, and "
          'current run state. Poll this to track progress after '
          'adf_run_autopilot.',
      inputSchema: _idSchema('Feature id, as returned by adf_list_features.'),
      call: (api, args) async {
        final id = _requireId(args);
        final detail = await api.getJson('/features/$id');
        Object? pipeline;
        try {
          pipeline = await api.getJson('/features/$id/pipeline');
        } on OrchApiException catch (e) {
          pipeline = {'error': e.message};
        }
        if (detail is Map<String, dynamic>) {
          return {...detail, 'pipeline': pipeline};
        }
        return {'feature': detail, 'pipeline': pipeline};
      },
    ),
    _ToolSpec(
      name: 'adf_run_autopilot',
      description:
          'Start (or resume) the automated pipeline for an existing feature. '
          'Returns as soon as the run is kicked off; poll adf_feature_status '
          'to follow progress and spot gates that need adf_approve.',
      inputSchema: _idSchema('Feature id to run.'),
      call: (api, args) => api.postJson('/features/${_requireId(args)}/autopilot'),
    ),
    _ToolSpec(
      name: 'adf_approve',
      description:
          "Approve a feature's pending human gate so the pipeline can "
          'continue past it. Check adf_feature_status first to see which gate '
          'is waiting.',
      inputSchema: _idSchema('Feature id whose pending gate to approve.'),
      call: (api, args) => api.postJson('/features/${_requireId(args)}/approve'),
    ),
    _ToolSpec(
      name: 'adf_runner_health',
      description:
          'Check whether the underlying agent runner (Cursor, Claude, or a '
          'custom CLI) is installed and authenticated. Returns ready plus '
          'recovery steps — call this before autopilot runs, or whenever runs '
          'start failing.',
      inputSchema: _emptySchema,
      call: (api, args) => api.getJson('/runner/health'),
    ),
    _ToolSpec(
      name: 'adf_feature_cost',
      description:
          "One feature's spend: token usage and estimated cost across its "
          'pipeline runs.',
      inputSchema: _idSchema('Feature id to cost.'),
      call: (api, args) => api.getJson('/features/${_requireId(args)}/cost'),
    ),
    _ToolSpec(
      name: 'adf_cost_summary',
      description:
          'Aggregate spend across all features: totals plus the per-feature '
          'breakdown. Use it to watch budget while autopilot runs.',
      inputSchema: _emptySchema,
      call: (api, args) => api.getJson('/cost/summary'),
    ),
    _ToolSpec(
      name: 'adf_integrity_verify',
      description:
          "Verify a feature's tamper-evident integrity chain. The default "
          'fast path checks the recorded chain; strict=true re-hashes raw '
          'artifact bytes for adversarial audits (slower).',
      inputSchema: const {
        'type': 'object',
        'properties': {
          'id': {'type': 'string', 'description': 'Feature id to verify.'},
          'strict': {
            'type': 'boolean',
            'description':
                'Re-hash artifact bytes instead of trusting recorded hashes. '
                'Default false.',
            'default': false,
          },
        },
        'required': ['id'],
      },
      call: (api, args) {
        final id = _requireId(args);
        final strict = _optionalBool(args, 'strict', false);
        return api.getJson('/features/$id/integrity?strict=$strict');
      },
    ),
    _ToolSpec(
      name: 'adf_audit_bundle',
      description:
          'Export a self-contained adf-audit-bundle/1 JSON document for a '
          'feature: integrity chain, artifact hashes, gate states, cost, and '
          'a bundle_digest for offline verification. chain is null when the '
          'feature was never sealed.',
      inputSchema: _idSchema('Feature id to bundle.'),
      call: (api, args) =>
          api.getJson('/features/${_requireId(args)}/audit-bundle'),
    ),
  ];
}
