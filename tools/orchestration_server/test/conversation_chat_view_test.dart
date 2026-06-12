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
}
