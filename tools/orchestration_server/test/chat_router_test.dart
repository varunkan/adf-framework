import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/cost_meter.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:test/test.dart';

/// Minimal fake Ollama: GET /api/tags (reachability probe) + POST /api/chat.
class FakeOllama {
  FakeOllama(this.server, {required this.reply}) {
    server.listen(_handle);
  }

  final HttpServer server;
  final String reply;
  int tagsHits = 0;
  int chatHits = 0;

  static Future<FakeOllama> start({required String reply}) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    return FakeOllama(server, reply: reply);
  }

  String get host => 'http://127.0.0.1:${server.port}';

  int get hits => tagsHits + chatHits;

  Future<void> _handle(HttpRequest req) async {
    if (req.method == 'GET' && req.uri.path == '/api/tags') {
      tagsHits++;
      req.response
        ..statusCode = 200
        ..headers.contentType = ContentType.json
        ..write(jsonEncode({'models': []}));
    } else if (req.method == 'POST' && req.uri.path == '/api/chat') {
      chatHits++;
      await utf8.decoder.bind(req).join();
      req.response
        ..statusCode = 200
        ..headers.contentType = ContentType.json
        ..write(jsonEncode({
          'message': {'role': 'assistant', 'content': reply},
          'done': true,
        }));
    } else {
      req.response.statusCode = 404;
    }
    await req.response.close();
  }

  Future<void> close() => server.close(force: true);
}

/// In-process fake Anthropic API: POST /v1/messages with contract headers,
/// replying with one text block and fixed usage (1000 in / 500 out tokens).
class FakeAnthropic {
  FakeAnthropic(this.server, {required this.reply, required this.status}) {
    server.listen(_handle);
  }

  final HttpServer server;
  final String reply;
  final int status;
  int hits = 0;
  String? lastApiKey;
  String? lastVersion;
  Map<String, dynamic>? lastBody;

  static Future<FakeAnthropic> start({
    required String reply,
    int status = 200,
  }) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    return FakeAnthropic(server, reply: reply, status: status);
  }

  Uri get messagesUrl => Uri.parse('http://127.0.0.1:${server.port}/v1/messages');

  Future<void> _handle(HttpRequest req) async {
    if (req.method == 'POST' && req.uri.path == '/v1/messages') {
      hits++;
      lastApiKey = req.headers.value('x-api-key');
      lastVersion = req.headers.value('anthropic-version');
      lastBody =
          jsonDecode(await utf8.decoder.bind(req).join()) as Map<String, dynamic>;
      req.response
        ..statusCode = status
        ..headers.contentType = ContentType.json
        ..write(jsonEncode({
          'id': 'msg_test',
          'type': 'message',
          'role': 'assistant',
          'model': lastBody!['model'],
          'content': [
            {'type': 'text', 'text': reply},
          ],
          'usage': {'input_tokens': 1000, 'output_tokens': 500},
        }));
    } else {
      req.response.statusCode = 404;
    }
    await req.response.close();
  }

  Future<void> close() => server.close(force: true);
}

/// Test-local stand-in for the ClaudeApiBrain the production router supplies
/// (model_router.dart is owned elsewhere): POSTs /v1/messages with the
/// contract headers, parses the first text block, prices usage from the tier
/// table, and fires [onUsage] with a CostMeter-compatible result event.
class TestClaudeBrain {
  TestClaudeBrain(this.endpoint, this.model, this.apiKey, {this.onUsage});

  final Uri endpoint;
  final String model;
  final String apiKey;
  final void Function(Map<String, dynamic> event)? onUsage;

  /// [input, output] USD per MTok — the fixed tier price table.
  static const pricePerMTok = {
    'claude-haiku-4-5': [1.00, 5.00],
    'claude-sonnet-4-6': [3.00, 15.00],
    'claude-opus-4-8': [5.00, 25.00],
  };

  Future<String?> complete({
    required String system,
    required String user,
  }) async {
    final client = HttpClient();
    try {
      final req = await client.postUrl(endpoint);
      req.headers.set('x-api-key', apiKey);
      req.headers.set('anthropic-version', '2023-06-01');
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode({
        'model': model,
        'max_tokens': 1024,
        'system': system,
        'messages': [
          {'role': 'user', 'content': user},
        ],
      }));
      final res = await req.close();
      final body = await res.transform(utf8.decoder).join();
      if (res.statusCode != 200) return null;
      final obj = jsonDecode(body) as Map<String, dynamic>;
      String? text;
      for (final block in obj['content'] as List<dynamic>? ?? const []) {
        if (block is Map && block['type'] == 'text') {
          text = block['text'] as String?;
          break;
        }
      }
      final usage = obj['usage'] as Map<String, dynamic>? ?? const {};
      final inTok = (usage['input_tokens'] as num? ?? 0).toInt();
      final outTok = (usage['output_tokens'] as num? ?? 0).toInt();
      final price = pricePerMTok[model] ?? const [0.0, 0.0];
      onUsage?.call({
        'type': 'result',
        'total_cost_usd': inTok * price[0] / 1e6 + outTok * price[1] / 1e6,
        'usage': {'input_tokens': inTok, 'output_tokens': outTok},
      });
      return text;
    } catch (_) {
      return null;
    } finally {
      client.close(force: true);
    }
  }
}

/// Forces a tier/model decision and supplies the test Claude brain — the
/// loose-coupled shape OrchestratorChatProcessor consults in auto mode.
class FakeRouter {
  FakeRouter({
    required this.tier,
    required this.model,
    this.anthropic,
    this.apiKey = 'test-key',
  });

  final String tier;
  final String model;
  final FakeAnthropic? anthropic;
  final String apiKey;
  int routeCalls = 0;
  int brainForCalls = 0;
  String? lastTask;
  String? lastKind;

  Map<String, String> route(String task, {String kind = 'chat', int? phase}) {
    routeCalls++;
    lastTask = task;
    lastKind = kind;
    return {'tier': tier, 'model': model, 'reason': 'forced by test'};
  }

  TestClaudeBrain brainFor(
    Object? decision, {
    void Function(Map<String, dynamic> event)? onUsage,
  }) {
    brainForCalls++;
    return TestClaudeBrain(anthropic!.messagesUrl, model, apiKey,
        onUsage: onUsage);
  }
}

void main() {
  late Directory tmp;
  late FeatureStore store;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('chat_router_');
    store = FeatureStore(tmp.path);
    store.createFeature(
      id: 'chat1',
      requirement: 'Chat about anything',
      track: 'M',
    );
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  OrchestratorChatProcessor processorWith(
    Map<String, String> env, {
    Object? router,
    void Function(String featureId, Map<String, dynamic> event)? onUsage,
  }) =>
      OrchestratorChatProcessor(store,
          env: env, router: router, onUsage: onUsage);

  // Free-form: matches no instant-tier pattern, so it must reach a model.
  const freeForm = 'tell me something interesting about this project';

  test('fast decision answers via Claude, stamps llm_source, meters usage',
      () async {
    final anthropic = await FakeAnthropic.start(
      reply: 'Claude answer here. [ACTION:answer_only]',
    );
    addTearDown(anthropic.close);
    final ollama = await FakeOllama.start(reply: 'should never be used');
    addTearDown(ollama.close);
    final router = FakeRouter(
      tier: 'fast',
      model: 'claude-haiku-4-5',
      anthropic: anthropic,
    );
    final usageEvents = <Map<String, dynamic>>[];
    final usageFeatures = <String>[];
    final processor = processorWith(
      {'ANTHROPIC_API_KEY': 'test-key', 'ORCH_OLLAMA_HOST': ollama.host},
      router: router,
      onUsage: (id, event) {
        usageFeatures.add(id);
        usageEvents.add(event);
      },
    );

    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'claude:claude-haiku-4-5');
    expect(r.assistantReply, contains('Claude answer here'));
    expect(r.assistantReply, isNot(contains('[ACTION')));
    expect(r.action, OrchestratorAction.answerOnly);
    expect(r.latencyMs, isNotNull);
    expect(router.routeCalls, 1);
    expect(router.lastTask, freeForm);
    expect(router.lastKind, 'chat');
    expect(router.brainForCalls, 1);
    expect(ollama.chatHits, 0);

    // The Claude call followed the API contract against the fake server.
    expect(anthropic.hits, 1);
    expect(anthropic.lastApiKey, 'test-key');
    expect(anthropic.lastVersion, '2023-06-01');
    expect(anthropic.lastBody!['model'], 'claude-haiku-4-5');
    expect(anthropic.lastBody!['system'], contains('chat1'));

    // onUsage fired once with a CostMeter-compatible cost event:
    // 1000 in + 500 out at $1.00/$5.00 per MTok = $0.0035.
    expect(usageFeatures, ['chat1']);
    final event = usageEvents.single;
    expect(event['type'], 'result');
    expect(event['total_cost_usd'], closeTo(0.0035, 1e-9));
    final run = CostMeter(store, env: const {})
        .recordFromResultEvent('chat1', event);
    expect(run['usd'], closeTo(0.0035, 1e-9));
    expect(run['source'], CostMeter.sourceReported);
  });

  for (final (tier, model) in [
    ('balanced', 'claude-sonnet-4-6'),
    ('deep', 'claude-opus-4-8'),
  ]) {
    test('$tier decision stamps llm_source claude:$model', () async {
      final anthropic = await FakeAnthropic.start(
        reply: 'Deeper answer. [ACTION:answer_only]',
      );
      addTearDown(anthropic.close);
      final router =
          FakeRouter(tier: tier, model: model, anthropic: anthropic);
      final processor = processorWith(
        {'ANTHROPIC_API_KEY': 'test-key'},
        router: router,
      );

      final r = await processor.process(
        'chat1',
        freeForm,
        mode: ChatProcessMode.httpOnly,
      );

      expect(r.source, 'claude:$model');
      expect(anthropic.hits, 1);
      expect(anthropic.lastBody!['model'], model);
    });
  }

  test('local decision stays on the free Ollama path', () async {
    final anthropic = await FakeAnthropic.start(reply: 'should never be used');
    addTearDown(anthropic.close);
    final ollama = await FakeOllama.start(
      reply: 'local reply [ACTION:answer_only]',
    );
    addTearDown(ollama.close);
    final router = FakeRouter(
      tier: 'local',
      model: 'nemo-test',
      anthropic: anthropic,
    );
    // Key present: the router decision, not the key, keeps this local.
    final processor = processorWith(
      {
        'ANTHROPIC_API_KEY': 'test-key',
        'ORCH_OLLAMA_HOST': ollama.host,
        'ORCH_OLLAMA_MODEL': 'nemo-test',
      },
      router: router,
    );

    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'ollama:nemo-test');
    expect(r.assistantReply, contains('local reply'));
    expect(router.routeCalls, 1);
    expect(router.brainForCalls, 0);
    expect(anthropic.hits, 0);
    expect(ollama.chatHits, 1);
  });

  test('no ANTHROPIC_API_KEY: cloud tiers never attempted, falls to Ollama',
      () async {
    final anthropic = await FakeAnthropic.start(reply: 'should never be used');
    addTearDown(anthropic.close);
    final ollama = await FakeOllama.start(
      reply: 'free local fallback [ACTION:answer_only]',
    );
    addTearDown(ollama.close);
    final router = FakeRouter(
      tier: 'deep',
      model: 'claude-opus-4-8',
      anthropic: anthropic,
    );
    final processor = processorWith(
      {'ORCH_OLLAMA_HOST': ollama.host, 'ORCH_OLLAMA_MODEL': 'm1'},
      router: router,
    );

    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'ollama:m1');
    expect(router.routeCalls, 1);
    expect(router.brainForCalls, 0);
    expect(anthropic.hits, 0);
    expect(ollama.chatHits, 1);
  });

  test('Claude failure falls back to the Ollama chain', () async {
    final anthropic =
        await FakeAnthropic.start(reply: 'overloaded', status: 529);
    addTearDown(anthropic.close);
    final ollama = await FakeOllama.start(
      reply: 'rescued locally [ACTION:answer_only]',
    );
    addTearDown(ollama.close);
    final router = FakeRouter(
      tier: 'fast',
      model: 'claude-haiku-4-5',
      anthropic: anthropic,
    );
    final processor = processorWith(
      {
        'ANTHROPIC_API_KEY': 'test-key',
        'ORCH_OLLAMA_HOST': ollama.host,
        'ORCH_OLLAMA_MODEL': 'm1',
      },
      router: router,
    );

    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );

    expect(anthropic.hits, 1);
    expect(r.source, 'ollama:m1');
    expect(r.assistantReply, contains('rescued locally'));
  });

  test('instant tier answers state questions without touching the router',
      () async {
    final anthropic = await FakeAnthropic.start(reply: 'should never be used');
    addTearDown(anthropic.close);
    final router = FakeRouter(
      tier: 'fast',
      model: 'claude-haiku-4-5',
      anthropic: anthropic,
    );
    final processor = processorWith(
      {'ANTHROPIC_API_KEY': 'test-key'},
      router: router,
    );

    final r = await processor.process(
      'chat1',
      'what does this feature do?',
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'state');
    expect(r.assistantReply, contains('Chat about anything'));
    expect(router.routeCalls, 0);
    expect(anthropic.hits, 0);
  });

  test('ORCH_CHAT_LLM=ollama bypasses the router entirely', () async {
    final anthropic = await FakeAnthropic.start(reply: 'should never be used');
    addTearDown(anthropic.close);
    final ollama = await FakeOllama.start(
      reply: 'forced local [ACTION:answer_only]',
    );
    addTearDown(ollama.close);
    final router = FakeRouter(
      tier: 'deep',
      model: 'claude-opus-4-8',
      anthropic: anthropic,
    );
    final processor = processorWith(
      {
        'ORCH_CHAT_LLM': 'ollama',
        'ANTHROPIC_API_KEY': 'test-key',
        'ORCH_OLLAMA_HOST': ollama.host,
        'ORCH_OLLAMA_MODEL': 'm1',
      },
      router: router,
    );

    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'ollama:m1');
    expect(router.routeCalls, 0);
    expect(anthropic.hits, 0);
  });
}
