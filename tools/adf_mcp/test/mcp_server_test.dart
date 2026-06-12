import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:adf_mcp/http_proxy.dart';
import 'package:adf_mcp/mcp_server.dart';
import 'package:test/test.dart';

const _allToolNames = [
  'adf_list_features',
  'adf_create_feature',
  'adf_feature_status',
  'adf_run_autopilot',
  'adf_approve',
  'adf_runner_health',
  'adf_feature_cost',
  'adf_cost_summary',
  'adf_integrity_verify',
  'adf_audit_bundle',
];

/// StringSink that re-emits complete lines as a stream, so tests can read the
/// server's newline-delimited replies.
class _LineSink implements StringSink {
  final _controller = StreamController<String>();
  final _buffer = StringBuffer();

  Stream<String> get lines => _controller.stream;

  @override
  void write(Object? object) {
    _buffer.write(object);
    _emitCompleteLines();
  }

  @override
  void writeln([Object? object = '']) => write('$object\n');

  @override
  void writeAll(Iterable<Object?> objects, [String separator = '']) =>
      write(objects.join(separator));

  @override
  void writeCharCode(int charCode) => write(String.fromCharCode(charCode));

  void _emitCompleteLines() {
    final pending = _buffer.toString();
    final lastNewline = pending.lastIndexOf('\n');
    if (lastNewline < 0) return;
    _buffer.clear();
    _buffer.write(pending.substring(lastNewline + 1));
    for (final line in pending.substring(0, lastNewline).split('\n')) {
      if (line.isNotEmpty) _controller.add(line);
    }
  }
}

/// Drives an [AdfMcpServer] over in-memory streams with simple
/// request/response matching (the server replies in order).
class _Harness {
  _Harness(String baseUrl) {
    _server = AdfMcpServer(
      input: _input.stream,
      output: _sink,
      api: OrchHttpProxy(baseUrl: baseUrl),
    );
    _done = _server.serve();
    _sink.lines.listen((line) {
      final message = jsonDecode(line) as Map<String, dynamic>;
      if (_waiting.isNotEmpty) {
        _waiting.removeAt(0).complete(message);
      } else {
        _unclaimed.add(message);
      }
    });
  }

  final _input = StreamController<String>();
  final _sink = _LineSink();
  final _waiting = <Completer<Map<String, dynamic>>>[];
  final _unclaimed = <Map<String, dynamic>>[];
  late final AdfMcpServer _server;
  late final Future<void> _done;
  var _nextId = 0;

  Future<Map<String, dynamic>> request(String method,
      [Map<String, dynamic>? params]) {
    _input.add(jsonEncode({
      'jsonrpc': '2.0',
      'id': ++_nextId,
      'method': method,
      if (params != null) 'params': params,
    }));
    return nextMessage();
  }

  Future<Map<String, dynamic>> callTool(String name,
          [Map<String, dynamic>? arguments]) =>
      request('tools/call', {
        'name': name,
        if (arguments != null) 'arguments': arguments,
      });

  void notify(String method) =>
      _input.add(jsonEncode({'jsonrpc': '2.0', 'method': method}));

  Future<Map<String, dynamic>> nextMessage() {
    if (_unclaimed.isNotEmpty) {
      return Future.value(_unclaimed.removeAt(0));
    }
    final completer = Completer<Map<String, dynamic>>();
    _waiting.add(completer);
    return completer.future.timeout(const Duration(seconds: 10));
  }

  Future<void> close() async {
    await _input.close();
    await _done;
  }
}

/// Decodes the single text content block of a tools/call result.
Object? _toolPayload(Map<String, dynamic> response) {
  final result = response['result'] as Map<String, dynamic>;
  final content = result['content'] as List<dynamic>;
  final block = content.single as Map<String, dynamic>;
  expect(block['type'], 'text');
  return jsonDecode(block['text'] as String);
}

void main() {
  late HttpServer fakeApi;
  late _Harness harness;
  final createdBodies = <Map<String, dynamic>>[];

  Future<void> handle(HttpRequest request) async {
    final key = '${request.method} ${request.uri.path}';
    Object? payload;
    var status = HttpStatus.ok;
    switch (key) {
      case 'GET /features':
        payload = [
          {'id': 'F0001', 'requirement': 'Dark mode', 'status': 'running'},
        ];
      case 'POST /features':
        final body = jsonDecode(await utf8.decoder.bind(request).join())
            as Map<String, dynamic>;
        createdBodies.add(body);
        payload = {'id': 'F0002', ...body};
      case 'GET /features/F0001':
        payload = {'id': 'F0001', 'phase': 'build'};
      case 'GET /features/F0001/pipeline':
        payload = {
          'phases': ['plan', 'build', 'verify'],
        };
      case 'GET /features/F0001/integrity':
        payload = {
          'ok': true,
          'strict': request.uri.queryParameters['strict'] == 'true',
        };
      default:
        status = HttpStatus.notFound;
        payload = {'error': 'not found'};
    }
    request.response
      ..statusCode = status
      ..headers.contentType = ContentType.json
      ..write(jsonEncode(payload));
    await request.response.close();
  }

  setUp(() async {
    createdBodies.clear();
    fakeApi = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    fakeApi.listen(handle);
    harness = _Harness('http://127.0.0.1:${fakeApi.port}');
  });

  tearDown(() async {
    await harness.close();
    await fakeApi.close(force: true);
  });

  test('initialize handshake echoes the protocol version', () async {
    final response = await harness.request('initialize', {
      'protocolVersion': '2025-03-26',
      'capabilities': <String, dynamic>{},
      'clientInfo': {'name': 'test-client', 'version': '0.0.1'},
    });

    final result = response['result'] as Map<String, dynamic>;
    expect(result['protocolVersion'], '2025-03-26');
    expect(result['capabilities'], containsPair('tools', isA<Map<String, dynamic>>()));
    expect(result['serverInfo'], {'name': 'adf-mcp', 'version': '3.2.0'});

    // notifications/initialized must produce no reply: the very next message
    // the server emits is the ping response.
    harness.notify('notifications/initialized');
    final ping = await harness.request('ping');
    expect(ping['id'], 2);
    expect(ping['result'], isEmpty);
  });

  test('tools/list advertises all 10 tools with object schemas', () async {
    final response = await harness.request('tools/list');
    final tools = (response['result']
        as Map<String, dynamic>)['tools'] as List<dynamic>;

    expect(
      tools.map((tool) => (tool as Map<String, dynamic>)['name']),
      unorderedEquals(_allToolNames),
    );
    for (final tool in tools.cast<Map<String, dynamic>>()) {
      expect(tool['description'], isA<String>());
      final schema = tool['inputSchema'] as Map<String, dynamic>;
      expect(schema['type'], 'object', reason: '${tool['name']} schema');
      expect(schema['properties'], isA<Map<String, dynamic>>());
    }
  });

  test('adf_create_feature round-trips the request body', () async {
    final response = await harness.callTool('adf_create_feature', {
      'requirement': 'Add a tip screen to checkout',
      'autopilot': true,
    });

    expect((response['result'] as Map<String, dynamic>)['isError'], isFalse);
    expect(createdBodies, [
      {'requirement': 'Add a tip screen to checkout', 'autopilot': true},
    ]);
    final payload = _toolPayload(response) as Map<String, dynamic>;
    expect(payload['id'], 'F0002');
    expect(payload['requirement'], 'Add a tip screen to checkout');
  });

  test('adf_feature_status merges the pipeline plan into the detail',
      () async {
    final response = await harness.callTool('adf_feature_status', {
      'id': 'F0001',
    });

    final payload = _toolPayload(response) as Map<String, dynamic>;
    expect(payload['phase'], 'build');
    expect(payload['pipeline'], {
      'phases': ['plan', 'build', 'verify'],
    });
  });

  test('adf_integrity_verify forwards the strict flag', () async {
    final strictOn = await harness.callTool('adf_integrity_verify', {
      'id': 'F0001',
      'strict': true,
    });
    expect(_toolPayload(strictOn), {'ok': true, 'strict': true});

    final strictOff = await harness.callTool('adf_integrity_verify', {
      'id': 'F0001',
    });
    expect(_toolPayload(strictOff), {'ok': true, 'strict': false});
  });

  test('tools/call with the API down returns isError with recovery hint',
      () async {
    // Bind-then-close guarantees a port with nothing listening.
    final dead = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final deadPort = dead.port;
    await dead.close(force: true);
    final offline = _Harness('http://127.0.0.1:$deadPort');
    addTearDown(offline.close);

    final response = await offline.callTool('adf_list_features');

    final result = response['result'] as Map<String, dynamic>;
    expect(result['isError'], isTrue);
    final content = result['content'] as List<dynamic>;
    final text = (content.single as Map<String, dynamic>)['text'] as String;
    expect(text, contains('adf start api'));
  });

  test('unknown method gets JSON-RPC -32601, unknown tool -32602', () async {
    final unknownMethod = await harness.request('resources/list');
    expect(
      unknownMethod['error'],
      containsPair('code', -32601),
    );

    final unknownTool = await harness.callTool('adf_does_not_exist');
    expect(unknownTool['error'], containsPair('code', -32602));

    final missingId = await harness.callTool('adf_feature_status');
    expect(missingId['error'], containsPair('code', -32602));
  });
}
