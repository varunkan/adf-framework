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
      id: 'feature2',
      requirement: 'Auth login feature',
      track: 'M',
    );
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  test('passes through direct orchestrator commands', () async {
    final r = await processor.process(
      'feature2',
      '@orch-orchestrator sync feature2',
      mode: ChatProcessMode.httpOnly,
    );
    expect(r.source, 'direct');
    expect(r.orchestratorCommand, contains('@orch-orchestrator sync'));
    expect(r.shouldRunAgent, isTrue);
  });

  test('fallback produces agent prompt for work requests', () async {
    final r = await processor.process(
      'feature2',
      'Please add OAuth login and proceed to planning',
      mode: ChatProcessMode.httpOnly,
    );
    expect(r.assistantReply, isNotEmpty);
    expect(r.orchestratorCommand, startsWith('@orch-orchestrator'));
    expect(r.agentPrompt, contains('OAuth'));
    expect(r.source, anyOf('fallback', 'llm'));
  });

  test('sync intent maps to sync command', () async {
    final r = await processor.process(
      'feature2',
      'looks good, please sync and approve',
      mode: ChatProcessMode.httpOnly,
    );
    expect(r.orchestratorCommand, contains('sync'));
  });

  test('URL questions avoid static templates by default', () async {
    final r = await processor.process(
      'feature2',
      'what is the url for feature 2?',
      mode: ChatProcessMode.httpOnly,
    );
    expect(r.source, isNot('context'));
    expect(r.shouldRunAgent, isFalse);
  });

  test('static context answers URLs when forced', () async {
    final staticProc = OrchestratorChatProcessor(store, forceStaticContext: true);
    final r = await staticProc.process(
      'feature2',
      'what is the url for feature 2?',
      mode: ChatProcessMode.httpOnly,
    );
    expect(r.source, 'context');
    expect(r.assistantReply, contains('http://localhost:3847/features/feature2'));
  });
}
