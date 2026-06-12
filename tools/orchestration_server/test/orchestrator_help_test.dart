import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  late OrchestratorChatProcessor processor;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_help_');
    store = FeatureStore(tmp.path);
    processor = OrchestratorChatProcessor(store);
    store.createFeature(id: 'h1', requirement: 'Help test', track: 'S');
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  test('stateOnly help explains ADF chat commands', () async {
    final r = await processor.process('h1', 'help', mode: ChatProcessMode.stateOnly);
    expect(r.source, 'state');
    expect(r.assistantReply.toLowerCase(), contains('phase'));
  });

  test('filter skips pending thinking messages in history path', () async {
    final r = await processor.process(
      'h1',
      'what phase?',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.shouldRunAgent, isFalse);
  });
}
