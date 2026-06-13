import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/model_router.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:test/test.dart';

/// End-to-end proof of the hybrid chat path: a real [ModelRouter] injected
/// into [OrchestratorChatProcessor], routing a code-block question to the
/// free NVIDIA `fast` tier and answering through an in-process fake NVIDIA
/// NIM endpoint. Exercises the same positional/named `route()` contract the
/// production server uses, which a unit test on the router alone cannot.
class FakeNvidia {
  FakeNvidia(this.server, {required this.reply}) {
    server.listen(_handle);
  }

  final HttpServer server;
  final String reply;
  int hits = 0;
  String? lastAuth;
  Map<String, dynamic>? lastBody;

  static Future<FakeNvidia> start({required String reply}) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    return FakeNvidia(server, reply: reply);
  }

  /// OpenAI-compatible API root the brain appends `/chat/completions` to.
  String get baseUrl => 'http://127.0.0.1:${server.port}/v1';

  Future<void> _handle(HttpRequest req) async {
    if (req.method == 'POST' && req.uri.path == '/v1/chat/completions') {
      hits++;
      lastAuth = req.headers.value('authorization');
      lastBody =
          jsonDecode(await utf8.decoder.bind(req).join()) as Map<String, dynamic>;
      req.response
        ..statusCode = 200
        ..headers.contentType = ContentType.json
        ..write(jsonEncode({
          'choices': [
            {
              'message': {'role': 'assistant', 'content': reply},
              'finish_reason': 'stop',
            }
          ],
          'usage': {'prompt_tokens': 800, 'completion_tokens': 200},
        }));
    } else {
      req.response.statusCode = 404;
    }
    await req.response.close();
  }

  Future<void> close() => server.close(force: true);
}

void main() {
  late Directory tmp;
  late FeatureStore store;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('nvidia_chat_');
    store = FeatureStore(tmp.path);
    store.createFeature(
      id: 'chat1',
      requirement: 'Chat about anything',
      track: 'M',
    );
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  test('a code-block question routes to the free NVIDIA fast tier', () async {
    final nvidia = await FakeNvidia.start(
      reply: 'NVIDIA says hi. [ACTION:answer_only]',
    );
    addTearDown(nvidia.close);

    final env = {
      'NVIDIA_API_KEY': 'nvapi-test',
      'ORCH_NVIDIA_BASE_URL': nvidia.baseUrl,
    };
    final usageEvents = <Map<String, dynamic>>[];
    final processor = OrchestratorChatProcessor(
      store,
      env: env,
      router: ModelRouter(env: env),
      onUsage: (id, event) => usageEvents.add(event),
    );

    // chat(0) + code block(1) = score 1 -> fast tier -> NVIDIA provider.
    final r = await processor.process(
      'chat1',
      'why does this throw?\n```dart\nvoid main() {}\n```',
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'nvidia:meta/llama-3.3-70b-instruct');
    expect(r.assistantReply, contains('NVIDIA says hi'));
    expect(r.assistantReply, isNot(contains('[ACTION')));
    expect(r.action, OrchestratorAction.answerOnly);

    // The call hit the fake NVIDIA endpoint with bearer auth + right model.
    expect(nvidia.hits, 1);
    expect(nvidia.lastAuth, 'Bearer nvapi-test');
    expect(nvidia.lastBody!['model'], 'meta/llama-3.3-70b-instruct');

    // Usage is metered but free: tokens reported, no cost field.
    final event = usageEvents.single;
    expect(event['type'], 'result');
    expect(event.containsKey('total_cost_usd'), isFalse);
    expect(event['usage'], {'input_tokens': 800, 'output_tokens': 200});
  });

  test('a trivial question stays local and never calls NVIDIA', () async {
    final nvidia = await FakeNvidia.start(reply: 'should not be used');
    addTearDown(nvidia.close);

    final env = {
      'NVIDIA_API_KEY': 'nvapi-test',
      'ORCH_NVIDIA_BASE_URL': nvidia.baseUrl,
      // No Ollama host -> local path is unreachable, routed call returns null
      // and falls through to the deterministic fallback. Either way, the
      // free NVIDIA endpoint must not be billed for a trivial 'local' turn.
      'ORCH_OLLAMA_HOST': 'http://127.0.0.1:1',
    };
    final processor = OrchestratorChatProcessor(
      store,
      env: env,
      router: ModelRouter(env: env),
    );

    final r = await processor.process(
      'chat1',
      'hi',
      mode: ChatProcessMode.httpOnly,
    );

    expect(nvidia.hits, 0);
    expect(r.source, isNot('nvidia:meta/llama-3.3-70b-instruct'));
  });
}
