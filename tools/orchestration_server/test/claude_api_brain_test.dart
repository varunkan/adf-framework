import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/claude_api_brain.dart';
import 'package:orchestration_server/cost_meter.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

/// Minimal fake Anthropic Messages API: records each request's headers and
/// body, replies with a canned message + usage.
class FakeAnthropic {
  FakeAnthropic(this.server) {
    server.listen(_handle);
  }

  final HttpServer server;

  int statusCode = 200;
  Duration delay = Duration.zero;
  int inputTokens = 1000;
  int outputTokens = 500;
  String replyText = 'hello from claude';

  int hits = 0;
  String? lastPath;
  String? lastApiKey;
  String? lastVersion;
  String? lastContentType;
  Map<String, dynamic>? lastBody;

  static Future<FakeAnthropic> start() async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    return FakeAnthropic(server);
  }

  String get host => 'http://127.0.0.1:${server.port}';

  Future<void> _handle(HttpRequest req) async {
    hits++;
    lastPath = req.uri.path;
    lastApiKey = req.headers.value('x-api-key');
    lastVersion = req.headers.value('anthropic-version');
    lastContentType = req.headers.contentType?.mimeType;
    try {
      lastBody = jsonDecode(await utf8.decoder.bind(req).join())
          as Map<String, dynamic>;
    } catch (_) {
      lastBody = null;
    }
    if (delay > Duration.zero) await Future<void>.delayed(delay);
    try {
      req.response
        ..statusCode = statusCode
        ..headers.contentType = ContentType.json
        ..write(jsonEncode({
          'id': 'msg_test',
          'type': 'message',
          'role': 'assistant',
          'content': [
            {'type': 'text', 'text': replyText},
          ],
          'usage': {
            'input_tokens': inputTokens,
            'output_tokens': outputTokens,
          },
        }));
      await req.response.close();
    } catch (_) {
      // Client force-closed the socket (timeout tests) — fine.
    }
  }

  Future<void> close() => server.close(force: true);
}

void main() {
  ClaudeApiBrain brainFor(
    FakeAnthropic fake, {
    String model = 'claude-haiku-4-5',
    Map<String, String> env = const {'ANTHROPIC_API_KEY': 'test-key'},
    void Function(Map<String, dynamic> event)? onUsage,
  }) =>
      ClaudeApiBrain(
        model: model,
        baseUrl: fake.host,
        env: env,
        onUsage: onUsage,
      );

  const userTurn = [
    {'role': 'user', 'content': 'hi'},
  ];

  test('sends the exact Anthropic headers and parses the first text block',
      () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    final brain = brainFor(fake);

    final reply = await brain.complete(system: 'be brief', user: 'hi');

    expect(reply, 'hello from claude');
    expect(fake.lastPath, '/v1/messages');
    expect(fake.lastApiKey, 'test-key');
    expect(fake.lastVersion, '2023-06-01');
    expect(fake.lastContentType, 'application/json');
    expect(fake.lastBody!['model'], 'claude-haiku-4-5');
    expect(fake.lastBody!['max_tokens'], 1024);
    // System role is hoisted to the API's top-level system field.
    expect(fake.lastBody!['system'], 'be brief');
    expect((fake.lastBody!['messages'] as List).single,
        {'role': 'user', 'content': 'hi'});
    expect(brain.name, 'claude:claude-haiku-4-5');
    expect(brain.billsTokens, isTrue);
  });

  test('adaptive thinking is sent only for the deep-tier opus model',
      () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);

    await brainFor(fake, model: 'claude-opus-4-8').chat(userTurn);
    expect(fake.lastBody!['thinking'], {'type': 'adaptive'});

    for (final model in ['claude-haiku-4-5', 'claude-sonnet-4-6']) {
      await brainFor(fake, model: model).chat(userTurn);
      expect(fake.lastBody!.containsKey('thinking'), isFalse, reason: model);
    }
  });

  test('never sends sampling parameters (they 400 on opus 4.7+)', () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);

    await brainFor(fake, model: 'claude-opus-4-8').chat(userTurn);

    for (final banned in ['temperature', 'top_p', 'top_k']) {
      expect(fake.lastBody!.containsKey(banned), isFalse, reason: banned);
    }
  });

  test('usage prices against the table: 1000 in + 500 out on haiku == 0.0035',
      () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    final events = <Map<String, dynamic>>[];
    final brain = brainFor(fake, onUsage: events.add);

    await brain.complete(system: 's', user: 'u');

    final event = events.single;
    expect(event['type'], 'result');
    expect(event['total_cost_usd'], closeTo(0.0035, 1e-12));
    expect(event['usage'], {'input_tokens': 1000, 'output_tokens': 500});
  });

  test('opus pricing: 1000 in + 500 out == 0.0175', () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    final events = <Map<String, dynamic>>[];

    await brainFor(fake, model: 'claude-opus-4-8', onUsage: events.add)
        .chat(userTurn);

    // 1000 * $5/MTok + 500 * $25/MTok = 0.005 + 0.0125.
    expect(events.single['total_cost_usd'], closeTo(0.0175, 1e-12));
  });

  test('unknown model omits total_cost_usd so CostMeter can estimate',
      () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    final events = <Map<String, dynamic>>[];

    await brainFor(fake, model: 'claude-opus-99', onUsage: events.add)
        .chat(userTurn);

    final event = events.single;
    expect(event.containsKey('total_cost_usd'), isFalse);
    expect(event['usage'], {'input_tokens': 1000, 'output_tokens': 500});
  });

  test('onUsage event feeds CostMeter.recordFromResultEvent unchanged',
      () async {
    final tmp = Directory.systemTemp.createTempSync('claude_brain_cost_');
    addTearDown(() => tmp.deleteSync(recursive: true));
    final store = FeatureStore(tmp.path);
    store.createFeature(
      id: 'claude-cost',
      requirement: 'Meter cloud brain spend.',
      track: 'S',
    );
    final meter = CostMeter(store, env: const {});

    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    final brain = brainFor(
      fake,
      onUsage: (event) =>
          meter.recordFromResultEvent('claude-cost', event, phase: 3),
    );

    await brain.complete(system: 's', user: 'u');

    final cost = meter.featureCost('claude-cost');
    expect(cost['total_usd'], closeTo(0.0035, 1e-9));
    expect(cost['total_input_tokens'], 1000);
    expect(cost['total_output_tokens'], 500);
    expect(cost['zero_cost'], isFalse);
    final run = (cost['runs'] as List).single as Map<String, dynamic>;
    expect(run['source'], CostMeter.sourceReported);
    expect(run['phase'], 3);
  });

  test('timeout returns null within the budget', () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    fake.delay = const Duration(seconds: 3);
    final brain = brainFor(fake);

    final sw = Stopwatch()..start();
    final reply = await brain.chat(
      userTurn,
      timeout: const Duration(milliseconds: 250),
    );
    sw.stop();

    expect(reply, isNull);
    expect(sw.elapsedMilliseconds, lessThan(2000));
  });

  test('ORCH_AGENT_TIMEOUT_SEC caps chat when no timeout is passed',
      () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    fake.delay = const Duration(seconds: 3);
    final brain = brainFor(fake, env: const {
      'ANTHROPIC_API_KEY': 'test-key',
      'ORCH_AGENT_TIMEOUT_SEC': '1',
    });

    final sw = Stopwatch()..start();
    final reply = await brain.chat(userTurn);
    sw.stop();

    expect(reply, isNull);
    expect(sw.elapsedMilliseconds, lessThan(2500));
  });

  test('non-200 returns null and reports no usage', () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    fake.statusCode = 500;
    final events = <Map<String, dynamic>>[];
    final brain = brainFor(fake, onUsage: events.add);

    expect(await brain.complete(system: 's', user: 'u'), isNull);
    expect(events, isEmpty);
    expect(fake.hits, 1);
  });

  test('missing ANTHROPIC_API_KEY returns null without calling the API',
      () async {
    final fake = await FakeAnthropic.start();
    addTearDown(fake.close);
    final brain = brainFor(fake, env: const {});

    expect(await brain.complete(system: 's', user: 'u'), isNull);
    expect(brain.hasApiKey, isFalse);
    expect(fake.hits, 0);
  });
}
