import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/openai_compat_brain.dart';
import 'package:test/test.dart';

/// In-process fake OpenAI-compatible endpoint: POST /v1/chat/completions,
/// echoing one assistant message plus fixed usage (1000 prompt / 500
/// completion tokens). Captures the auth header, model, and request body.
class FakeOpenAi {
  FakeOpenAi(this.server, {required this.reply, required this.status}) {
    server.listen(_handle);
  }

  final HttpServer server;
  final String reply;
  final int status;
  int hits = 0;
  String? lastAuth;
  Map<String, dynamic>? lastBody;

  static Future<FakeOpenAi> start({
    required String reply,
    int status = 200,
  }) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    return FakeOpenAi(server, reply: reply, status: status);
  }

  String get baseUrl => 'http://127.0.0.1:${server.port}/v1';

  Future<void> _handle(HttpRequest req) async {
    if (req.method == 'POST' && req.uri.path == '/v1/chat/completions') {
      hits++;
      lastAuth = req.headers.value('authorization');
      lastBody =
          jsonDecode(await utf8.decoder.bind(req).join()) as Map<String, dynamic>;
      req.response
        ..statusCode = status
        ..headers.contentType = ContentType.json
        ..write(jsonEncode({
          'choices': [
            {
              'message': {'role': 'assistant', 'content': reply},
              'finish_reason': 'stop',
            }
          ],
          'usage': {'prompt_tokens': 1000, 'completion_tokens': 500},
        }));
    } else {
      req.response.statusCode = 404;
    }
    await req.response.close();
  }

  Future<void> close() => server.close(force: true);
}

void main() {
  test('completes against an OpenAI-compatible endpoint with bearer auth',
      () async {
    final api = await FakeOpenAi.start(reply: 'Hello from NVIDIA.');
    addTearDown(api.close);
    final brain = OpenAiCompatBrain(
      model: 'meta/llama-3.3-70b-instruct',
      baseUrl: api.baseUrl,
      apiKey: 'nvapi-secret',
      providerLabel: 'nvidia',
    );

    final out = await brain.complete(system: 'You are helpful.', user: 'Hi');

    expect(out, 'Hello from NVIDIA.');
    expect(api.hits, 1);
    expect(api.lastAuth, 'Bearer nvapi-secret');
    expect(api.lastBody!['model'], 'meta/llama-3.3-70b-instruct');
    expect(api.lastBody!['stream'], isFalse);
    final messages = api.lastBody!['messages'] as List;
    expect(messages.first['role'], 'system');
    expect(messages.last['content'], 'Hi');
  });

  test('name reflects provider and billsTokens defaults false (free)', () {
    final brain = OpenAiCompatBrain(
      model: 'qwen/qwen2.5-coder-32b-instruct',
      baseUrl: OpenAiCompatBrain.nvidiaBaseUrl,
      apiKey: 'nvapi-x',
      providerLabel: 'nvidia',
    );
    expect(brain.name, 'nvidia:qwen/qwen2.5-coder-32b-instruct');
    expect(brain.billsTokens, isFalse);
    expect(brain.hasApiKey, isTrue);
  });

  test('free tier reports token counts with no cost', () async {
    final api = await FakeOpenAi.start(reply: 'ok');
    addTearDown(api.close);
    final events = <Map<String, dynamic>>[];
    final brain = OpenAiCompatBrain(
      model: 'meta/llama-3.3-70b-instruct',
      baseUrl: api.baseUrl,
      apiKey: 'nvapi-x',
      providerLabel: 'nvidia',
      onUsage: events.add,
    );

    await brain.complete(system: 's', user: 'u');

    final event = events.single;
    expect(event['type'], 'result');
    expect(event.containsKey('total_cost_usd'), isFalse); // $0 — free tier
    expect(event['usage'],
        {'input_tokens': 1000, 'output_tokens': 500});
  });

  test('priced endpoint computes cost from the table', () async {
    final api = await FakeOpenAi.start(reply: 'ok');
    addTearDown(api.close);
    final events = <Map<String, dynamic>>[];
    final brain = OpenAiCompatBrain(
      model: 'gpt-x',
      baseUrl: api.baseUrl,
      apiKey: 'sk-x',
      providerLabel: 'openai',
      billsTokens: true,
      pricePerMTok: const {'gpt-x': (1.0, 5.0)},
      onUsage: events.add,
    );

    await brain.complete(system: 's', user: 'u');

    // 1000 in @ $1/MTok + 500 out @ $5/MTok = 0.001 + 0.0025 = 0.0035.
    expect(events.single['total_cost_usd'], closeTo(0.0035, 1e-9));
  });

  test('missing key returns null without calling the endpoint', () async {
    final api = await FakeOpenAi.start(reply: 'should not be used');
    addTearDown(api.close);
    final brain = OpenAiCompatBrain(
      model: 'm',
      baseUrl: api.baseUrl,
      apiKey: '   ',
      providerLabel: 'nvidia',
    );

    expect(await brain.complete(system: 's', user: 'u'), isNull);
    expect(api.hits, 0);
  });

  test('non-200 returns null', () async {
    final api =
        await FakeOpenAi.start(reply: 'rate limited', status: 429);
    addTearDown(api.close);
    final brain = OpenAiCompatBrain(
      model: 'm',
      baseUrl: api.baseUrl,
      apiKey: 'nvapi-x',
      providerLabel: 'nvidia',
    );

    expect(await brain.complete(system: 's', user: 'u'), isNull);
    expect(api.hits, 1);
  });
}
