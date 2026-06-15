import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestration_paths.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

void main() {
  group('fileWriteNarration (pure)', () {
    test('with index/total reads "Writing <path> (i/n)"', () {
      expect(
        PhaseRunner.fileWriteNarration(
            {'path': 'src/App.tsx', 'index': 1, 'total': 5}),
        'Writing src/App.tsx (1/5)',
      );
    });
    test('without counts, just the path', () {
      expect(
        PhaseRunner.fileWriteNarration({'path': 'server/index.mjs'}),
        'Writing server/index.mjs',
      );
    });
  });

  test('a file_write event becomes a live trace span (kills dead-air)', () {
    final repo = Directory.systemTemp.createTempSync('adf-filewrite');
    addTearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);
    final store = FeatureStore(repo.path);
    final runner = PhaseRunner(store);

    runner.ingestAgentLine(
      'demo',
      7,
      jsonEncode(
          {'type': 'file_write', 'path': 'src/App.tsx', 'index': 2, 'total': 4}),
    );

    final file = File(OrchestrationPaths(repo.path).otelTracesFile);
    expect(file.existsSync(), isTrue, reason: 'a span must be written');
    final spans = file
        .readAsLinesSync()
        .where((l) => l.trim().isNotEmpty)
        .map((l) => jsonDecode(l) as Map<String, dynamic>)
        .toList();
    final fw = spans.where((s) => s['name'] == 'file.write').toList();
    expect(fw, hasLength(1));
    expect((fw.first['attributes'] as Map)['orch.message'],
        'Writing src/App.tsx (2/4)');
  });
}
