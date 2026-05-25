import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  late OrchestratorChatProcessor processor;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_chat_test_');
    store = FeatureStore(tmp.path);
    processor = OrchestratorChatProcessor(store);
    store.createFeature(
      id: 'chat-test',
      requirement: 'Build a URL shortener API',
      track: 'S',
    );
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  test('passes through direct orchestrator commands', () async {
    final r = await processor.process(
      'chat-test',
      '@orch-orchestrator sync chat-test',
    );
    expect(r.source, 'direct');
    expect(r.orchestratorCommand, contains('@orch-orchestrator sync'));
    expect(r.shouldRunAgent, isTrue);
  });

  test('fallback LLM produces assistant reply and agent prompt', () async {
    final r = await processor.process(
      'chat-test',
      'Please add OAuth login and proceed to planning',
    );
    expect(r.assistantReply, isNotEmpty);
    expect(r.orchestratorCommand, startsWith('@orch-orchestrator'));
    expect(r.agentPrompt, contains('OAuth'));
    expect(r.source, anyOf('fallback', 'llm'));
  });

  test('sync intent maps to sync command', () async {
    final r = await processor.process(
      'chat-test',
      'looks good, please sync and approve',
    );
    expect(r.orchestratorCommand, contains('sync'));
  });
}
