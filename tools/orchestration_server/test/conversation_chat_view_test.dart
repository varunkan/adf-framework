import 'dart:io';

import 'package:orchestration_server/conversation_builder.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  late ConversationBuilder builder;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_chatview_');
    store = FeatureStore(tmp.path);
    builder = ConversationBuilder(store);
    store.createFeature(id: 'f1', requirement: 'Demo', track: 'S');
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  test('buildChatView returns only command chat without run log', () {
    store.appendRunLog('f1', {
      'timestamp': '2026-01-01T00:00:00Z',
      'stream': 'stdout',
      'message': '{"type":"result","result":"agent noise"}',
    });
    store.appendCommand(
      'f1',
      prompt: 'hello',
      execute: true,
    );
    store.updateCommandMeta(
      'f1',
      store.listCommands('f1').first['id'] as String,
      assistantReply: 'Hi there',
      llmSource: 'state',
    );

    final chat = builder.buildChatView('f1');
    expect(chat.length, 2);
    expect(chat[0]['role'], 'user');
    expect(chat[1]['role'], 'assistant');
    expect(chat[1]['llm_source'], 'state');
    expect(chat.any((m) => m['type'] == 'result'), isFalse);
  });

  test('C1: internalTriggerLabel classifies machine triggers vs human prompts',
      () {
    expect(ConversationBuilder.internalTriggerLabel('crew'), isNotNull);
    expect(ConversationBuilder.internalTriggerLabel('@orch-orchestrator resume x'),
        isNotNull);
    expect(ConversationBuilder.internalTriggerLabel('resume my-feature'), isNotNull);
    expect(ConversationBuilder.internalTriggerLabel('# Builder: speckit phase 7'),
        isNotNull);
    expect(ConversationBuilder.internalTriggerLabel('Add a dark mode toggle'),
        isNull);
  });

  test('C1: internal triggers render as system status, not "You" bubbles', () {
    store.appendCommand('f1', prompt: 'crew', execute: false);
    store.appendCommand('f1', prompt: '@orch-orchestrator resume f1', execute: false);
    store.appendCommand('f1', prompt: 'Add a dark mode toggle', execute: false); // human
    final chat = builder.buildChatView('f1');
    final userTexts =
        chat.where((m) => m['role'] == 'user').map((m) => '${m['text']}').toList();
    expect(userTexts, isNot(contains('crew')),
        reason: 'an internal trigger must never be a user bubble');
    expect(userTexts.any((t) => t.contains('@orch-orchestrator')), isFalse);
    expect(userTexts, contains('Add a dark mode toggle'),
        reason: 'a genuine human prompt is still a user bubble');
    final statusTexts = chat
        .where((m) => m['role'] == 'system' && m['type'] == 'status')
        .map((m) => '${m['text']}')
        .toList();
    expect(statusTexts.any((t) => t.contains('Crew building')), isTrue);
  });
}
