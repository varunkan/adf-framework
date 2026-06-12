import 'dart:convert';
import 'dart:io';

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
  String? lastModel;
  List<dynamic> lastMessages = const [];

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
      final body =
          jsonDecode(await utf8.decoder.bind(req).join()) as Map<String, dynamic>;
      lastModel = body['model'] as String?;
      lastMessages = body['messages'] as List<dynamic>? ?? const [];
      req.response
        ..statusCode = 200
        ..headers.contentType = ContentType.json
        ..write(jsonEncode({
          'model': lastModel,
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

void main() {
  late Directory tmp;
  late FeatureStore store;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('ollama_chat_');
    store = FeatureStore(tmp.path);
    store.createFeature(
      id: 'chat1',
      requirement: 'Chat about anything',
      track: 'M',
    );
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  OrchestratorChatProcessor processorWith(Map<String, String> env) =>
      OrchestratorChatProcessor(store, env: env);

  // Free-form: matches no instant-tier pattern, so it must reach a model.
  const freeForm = 'tell me something interesting about this project';

  test('auto mode routes free-form chat to Ollama when reachable', () async {
    final fake = await FakeOllama.start(
      reply: 'It is a friendly local reply. [ACTION:answer_only]',
    );
    addTearDown(fake.close);
    final processor = processorWith({
      'ORCH_OLLAMA_HOST': fake.host,
      'ORCH_OLLAMA_MODEL': 'nemotron-test',
    });

    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'ollama:nemotron-test');
    expect(r.assistantReply, contains('friendly local reply'));
    expect(r.assistantReply, isNot(contains('[ACTION')));
    expect(r.action, OrchestratorAction.answerOnly);
    expect(r.shouldRunAgent, isFalse);
    expect(r.latencyMs, isNotNull);
    expect(fake.chatHits, 1);
    expect(fake.lastModel, 'nemotron-test');
    // System context + user turn reached the model.
    expect(fake.lastMessages.first['role'], 'system');
    expect(fake.lastMessages.last['content'], freeForm);
  });

  test('instant tier answers state questions without touching Ollama',
      () async {
    final fake = await FakeOllama.start(reply: 'should never be used');
    addTearDown(fake.close);
    final processor = processorWith({'ORCH_OLLAMA_HOST': fake.host});

    final r = await processor.process(
      'chat1',
      'what does this feature do?',
      mode: ChatProcessMode.httpOnly,
    );

    expect(r.source, 'state');
    expect(r.assistantReply, contains('Chat about anything'));
    expect(fake.hits, 0);
  });

  test('unreachable Ollama falls back fast without throwing', () async {
    // Bind+close to get a loopback port that is guaranteed closed.
    final placeholder =
        await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final deadPort = placeholder.port;
    await placeholder.close();
    final processor =
        processorWith({'ORCH_OLLAMA_HOST': 'http://127.0.0.1:$deadPort'});

    final sw = Stopwatch()..start();
    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );
    sw.stop();

    expect(r.source, 'fallback');
    expect(r.latencyMs, isNotNull);
    // The reachability probe is capped at 500ms; a refused connection
    // returns nearly instantly, so the whole turn stays under a second.
    expect(sw.elapsedMilliseconds, lessThan(1000));
  });

  test('ORCH_CHAT_LLM=cursor never probes Ollama', () async {
    final fake = await FakeOllama.start(reply: 'should never be used');
    addTearDown(fake.close);
    final processor = processorWith({
      'ORCH_CHAT_LLM': 'cursor',
      'ORCH_OLLAMA_HOST': fake.host,
      'ORCH_CHAT_USE_CURSOR': '0', // keep the test offline: no agent probe
    });

    expect(await processor.ollamaChatReady(), isFalse);
    final r = await processor.process(
      'chat1',
      freeForm,
      mode: ChatProcessMode.httpOnly,
    );

    expect(fake.hits, 0);
    expect(r.source, 'fallback');
  });

  test('reachability probe is cached, not re-run on every message', () async {
    final fake = await FakeOllama.start(
      reply: 'cached reply [ACTION:answer_only]',
    );
    addTearDown(fake.close);
    final processor = processorWith({
      'ORCH_OLLAMA_HOST': fake.host,
      'ORCH_OLLAMA_MODEL': 'm1',
    });

    await processor.process('chat1', 'tell me a story',
        mode: ChatProcessMode.httpOnly);
    await processor.process('chat1', 'tell me another story',
        mode: ChatProcessMode.httpOnly);

    expect(fake.tagsHits, 1); // probed once, verdict cached
    expect(fake.chatHits, 2);
  });
}
