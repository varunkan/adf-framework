import 'dart:io';

import 'package:orchestration_server/conversation_builder.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  late ConversationBuilder builder;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_conv_test_');
    store = FeatureStore(tmp.path);
    builder = ConversationBuilder(store);
    store.createFeature(
      id: 'demo',
      requirement: 'Test feature',
      track: 'S',
    );
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  test('merges user commands and last agent response', () {
    store.appendCommand(
      'demo',
      prompt: '@orch-orchestrator resume demo',
      execute: true,
    );
    store.writeLastAgentResponse('demo', '## Phase complete\n\nPlease review.');

    final messages = builder.build('demo');
    expect(messages.any((m) => m['role'] == 'user'), isTrue);
    expect(
      messages.any((m) => m['type'] == 'result' && (m['text'] as String).contains('Phase complete')),
      isTrue,
    );
  });

  test('skips truncated result placeholder in run log', () {
    store.appendRunLog('demo', {
      'timestamp': '2026-01-01T00:00:00Z',
      'stream': 'stdout',
      'message': '[result event — see last-agent-response.md]',
    });
    store.writeLastAgentResponse('demo', 'Full readable response.');

    final messages = builder.build('demo');
    expect(messages.where((m) => m['type'] == 'result').length, 1);
    expect(messages.last['text'], 'Full readable response.');
  });
}
