import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/orchestration_paths.dart';
import 'package:orchestration_server/trace_tailer.dart';
import 'package:orchestration_server/trace_writer.dart';
import 'package:test/test.dart';

/// S3 — the TraceTailer pushes the OUT-OF-PROCESS build runner's spans (appended
/// directly to the per-feature otel-traces.jsonl) into the live SSE broadcast, so
/// the dashboard streams them continuously instead of seeing them only on the
/// 1.5s /traces poll. Server-side spans (already broadcast by append) are skipped.
void main() {
  group('S3: TraceTailer streams out-of-process runner spans live', () {
    late Directory repo;
    late TraceWriter writer;

    setUp(() {
      repo = Directory.systemTemp.createTempSync('adf-tailer');
      writer = TraceWriter(repo.path);
    });
    tearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);

    String featFile(String id) =>
        OrchestrationPaths(repo.path).featureOtelTracesFile(id);
    void appendRaw(String id, Map<String, dynamic> rec) {
      final f = File(featFile(id))..parent.createSync(recursive: true);
      f.writeAsStringSync('${jsonEncode(rec)}\n', mode: FileMode.append);
    }

    test('an out-of-process span appended to the file is pushed live', () async {
      final got = <String>[];
      final sub = TraceWriter.events
          .where((r) => (r['attributes'] as Map?)?['orch.feature_id'] == 'ofp')
          .listen((r) => got.add(r['span_id'] as String));
      final tailer = TraceTailer(repo.path, 'ofp'); // offset 0
      appendRaw('ofp', {
        'timestamp': 't1',
        'span_id': 'ofp-aaa',
        'name': 'runner.generating',
        'attributes': {'orch.feature_id': 'ofp', 'orch.message': 'Generating…'},
      });
      final n = tailer.pumpOnce();
      await Future<void>.delayed(Duration.zero);
      expect(n, 1);
      expect(got, contains('ofp-aaa'),
          reason: 'the runner span must reach the live broadcast');
      await sub.cancel();
    });

    test('a span the server already broadcast is NOT double-pushed', () async {
      writer.append(featureId: 'dup', name: 'crew.wave', event: 'crew');
      final serverId = (jsonDecode(File(featFile('dup')).readAsLinesSync().first)
          as Map<String, dynamic>)['span_id'] as String;
      final got = <String>[];
      final sub = TraceWriter.events
          .where((r) => (r['attributes'] as Map?)?['orch.feature_id'] == 'dup')
          .listen((r) => got.add(r['span_id'] as String));
      final tailer = TraceTailer(repo.path, 'dup'); // offset 0 → re-reads the server line
      final n = tailer.pumpOnce();
      await Future<void>.delayed(Duration.zero);
      expect(n, 0, reason: 'server-broadcast span must be skipped by the tailer');
      expect(got, isNot(contains(serverId)));
      await sub.cancel();
    });

    test('a half-written trailing line is not pushed until the newline arrives',
        () async {
      final got = <String>[];
      final sub = TraceWriter.events
          .where((r) => (r['attributes'] as Map?)?['orch.feature_id'] == 'prt')
          .listen((r) => got.add(r['span_id'] as String));
      final tailer = TraceTailer(repo.path, 'prt');
      final f = File(featFile('prt'))..parent.createSync(recursive: true);
      f.writeAsStringSync(
          '{"span_id":"prt-1","attributes":{"orch.feature_id":"prt"}',
          mode: FileMode.append); // NO trailing newline yet
      expect(tailer.pumpOnce(), 0, reason: 'no complete line yet → push nothing');
      f.writeAsStringSync('}\n', mode: FileMode.append); // complete it
      final n = tailer.pumpOnce();
      await Future<void>.delayed(Duration.zero);
      expect(n, 1);
      expect(got, contains('prt-1'));
      await sub.cancel();
    });
  });
}
