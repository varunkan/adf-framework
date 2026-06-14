import 'dart:io';

import 'package:orchestration_server/conversation_builder.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  const id = 'conversation-system-message-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    if (!store.featureExists(id)) {
      store.createFeature(id: id, requirement: 'x', track: 'S');
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
  });

  test('appendSystemMessage renders as ONE assistant/system bubble, no user',
      () {
    store.appendSystemMessage(
      id,
      'Build complete — Phase 7 finished; the build ran and tests passed.',
      source: 'runner',
    );
    final view = ConversationBuilder(store).buildChatView(id);

    final sys = view
        .where((m) => m['type'] == 'system' && m['role'] == 'assistant')
        .toList();
    expect(sys.length, 1, reason: 'exactly one system/assistant bubble');
    expect(sys.first['text'], contains('Build complete'));
    expect(sys.first['llm_source'], 'runner');
    expect(
      view.where((m) => m['role'] == 'user').length,
      0,
      reason: 'an empty-prompt system entry must NOT create a phantom user bubble',
    );
  });

  test('a normal command still renders a user bubble', () {
    store.appendCommand(id, prompt: 'add a dark mode toggle');
    final view = ConversationBuilder(store).buildChatView(id);
    final users =
        view.where((m) => m['role'] == 'user' && m['type'] == 'command');
    expect(users, isNotEmpty);
    expect(users.first['text'], 'add a dark mode toggle');
  });
}
