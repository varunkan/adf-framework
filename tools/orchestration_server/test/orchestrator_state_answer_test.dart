import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  late OrchestratorChatProcessor processor;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_state_');
    store = FeatureStore(tmp.path);
    processor = OrchestratorChatProcessor(store);
    store.createFeature(id: 'pay1', requirement: 'Payment form', track: 'M');
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  test('stateOnly answers phase questions', () async {
    final r = await processor.process(
      'pay1',
      'what phase are we on?',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.source, 'state');
    expect(r.action, OrchestratorAction.answerOnly);
    expect(r.assistantReply.toLowerCase(), contains('phase'));
  });

  test('stateOnly answers URL questions', () async {
    final r = await processor.process(
      'pay1',
      'what is the url for this feature?',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.source, 'state');
    expect(r.assistantReply, contains('3847'));
  });
}
