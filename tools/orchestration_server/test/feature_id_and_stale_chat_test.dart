import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  group('generateFeatureId', () {
    test('slugs a prompt into kebab-case dropping stop words', () {
      final id = FeatureStore.generateFeatureId(
        'Please build a tip screen for checkout with presets',
      );
      expect(id, 'tip-screen-checkout-presets');
    });

    test('handles punctuation and casing', () {
      final id = FeatureStore.generateFeatureId('Add: Dark-Mode!! (settings)');
      expect(id, 'dark-mode-settings');
    });

    test('falls back to feature when prompt is all stop words', () {
      expect(FeatureStore.generateFeatureId('please make me an app'), 'feature');
    });

    test('avoids collisions with existing ids', () {
      final id = FeatureStore.generateFeatureId(
        'dark mode settings',
        existing: {'dark-mode-settings', 'dark-mode-settings-2'},
      );
      expect(id, 'dark-mode-settings-3');
    });
  });

  group('repairStaleChatReplies', () {
    late String repoRoot;
    late FeatureStore store;
    const id = 'stale-chat-repair-test';

    setUp(() {
      repoRoot = Directory.current.path;
      while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
        final parent = Directory(repoRoot).parent;
        if (parent.path == repoRoot) throw StateError('repo root not found');
        repoRoot = parent.path;
      }
      store = FeatureStore(repoRoot);
      if (!store.featureExists(id)) {
        store.createFeature(id: id, requirement: 'stale chat test', track: 'M');
      }
    });

    tearDown(() {
      if (store.featureExists(id)) {
        Directory(store.featurePath(id)).deleteSync(recursive: true);
      }
      final specDir = Directory('$repoRoot/specs/$id');
      if (specDir.existsSync()) specDir.deleteSync(recursive: true);
    });

    Map<String, dynamic> writeCommand({
      required String llmSource,
      required DateTime createdAt,
    }) {
      final cmd = store.appendCommand(id, prompt: 'hello?', execute: false);
      final file = File('${store.featurePath(id)}/commands.jsonl');
      final lines = file.readAsLinesSync().map((line) {
        final obj = jsonDecode(line) as Map<String, dynamic>;
        if (obj['id'] == cmd['id']) {
          obj['llm_source'] = llmSource;
          obj['created_at'] = createdAt.toUtc().toIso8601String();
        }
        return jsonEncode(obj);
      }).toList();
      file.writeAsStringSync('${lines.join('\n')}\n');
      return cmd;
    }

    Map<String, dynamic> readCommand(String commandId) {
      final file = File('${store.featurePath(id)}/commands.jsonl');
      return file
          .readAsLinesSync()
          .map((l) => jsonDecode(l) as Map<String, dynamic>)
          .firstWhere((c) => c['id'] == commandId);
    }

    test('old pending chat is closed out with a timeout reply', () {
      final cmd = writeCommand(
        llmSource: 'pending',
        createdAt: DateTime.now().subtract(const Duration(minutes: 30)),
      );
      store.repairStaleChatReplies(id);
      final repaired = readCommand(cmd['id'] as String);
      expect(repaired['llm_source'], 'timeout');
      expect(repaired['assistant_reply'], contains('did not finish'));
    });

    test('fresh streaming chat is left alone', () {
      final cmd = writeCommand(
        llmSource: 'streaming',
        createdAt: DateTime.now(),
      );
      store.repairStaleChatReplies(id);
      final untouched = readCommand(cmd['id'] as String);
      expect(untouched['llm_source'], 'streaming');
    });
  });
}
