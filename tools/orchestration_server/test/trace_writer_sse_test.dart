import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/trace_writer.dart';
import 'package:test/test.dart';

void main() {
  group('TraceWriter.sseEvent (pure framing)', () {
    test('the SSE id is the TIMESTAMP (one cursor space with `since`)', () {
      final frame = utf8.decode(TraceWriter.sseEvent({
        'span_id': 'abc123',
        'timestamp': '2026-06-19T12:00:00.000Z',
        'name': 'runner.verify_stage',
        'attributes': {
          'orch.feature_id': 'demo',
          'orch.message': 'Running vitest…',
        },
      }));
      // MUST be the timestamp, NOT span_id: Last-Event-ID is re-sent on reconnect
      // and fed into the `since` backfill cursor, which readTraces compares as an
      // ISO timestamp. A hex span_id here breaks reconnect backfill. (layer-4 major)
      expect(frame, startsWith('id: 2026-06-19T12:00:00.000Z\n'));
      expect(frame, isNot(contains('id: abc123')));
      expect(frame, contains('data: '));
      expect(frame, endsWith('\n\n'));
      final dataLine =
          frame.split('\n').firstWhere((l) => l.startsWith('data: '));
      final rec = jsonDecode(dataLine.substring('data: '.length)) as Map;
      expect(rec['span_id'], 'abc123'); // span_id is still in the payload
      expect((rec['attributes'] as Map)['orch.message'], 'Running vitest…');
    });

    test('missing timestamp yields an empty id line (no crash)', () {
      final frame =
          utf8.decode(TraceWriter.sseEvent({'name': 'x', 'attributes': {}}));
      expect(frame, startsWith('id: \n'));
    });
  });

  test('append() broadcasts the span live to TraceWriter.events', () async {
    final repo = Directory.systemTemp.createTempSync('adf-sse');
    addTearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);
    final tw = TraceWriter(repo.path);

    // Subscribe BEFORE appending (a broadcast stream drops events with no listener).
    final received = <Map<String, dynamic>>[];
    final sub = TraceWriter.events.listen(received.add);
    addTearDown(sub.cancel);

    tw.append(
      featureId: 'demo',
      name: 'runner.verify_result',
      event: 'runner',
      phase: 7,
      message: 'Verification passed ✓',
    );
    await Future<void>.delayed(Duration.zero); // let the broadcast deliver

    expect(received, hasLength(1));
    expect(received.first['name'], 'runner.verify_result');
    expect((received.first['attributes'] as Map)['orch.feature_id'], 'demo');
    expect((received.first['attributes'] as Map)['orch.message'],
        'Verification passed ✓');
  });

  test('events stream filters by feature_id (per-feature SSE)', () async {
    final repo = Directory.systemTemp.createTempSync('adf-sse2');
    addTearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);
    final tw = TraceWriter(repo.path);
    final demoOnly = <Map<String, dynamic>>[];
    final sub = TraceWriter.events
        .where((r) => (r['attributes'] as Map?)?['orch.feature_id'] == 'demo')
        .listen(demoOnly.add);
    addTearDown(sub.cancel);

    tw.append(featureId: 'other', name: 'a', event: 'runner');
    tw.append(featureId: 'demo', name: 'b', event: 'runner');
    await Future<void>.delayed(Duration.zero);

    expect(demoOnly.map((r) => r['name']), ['b']);
  });

  test('append() increments the spansPushed metric (observability)', () {
    final repo = Directory.systemTemp.createTempSync('adf-metric');
    addTearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);
    final before = TraceWriter.spansPushed;
    TraceWriter(repo.path)
        .append(featureId: 'demo', name: 'runner.x', event: 'runner');
    TraceWriter(repo.path)
        .append(featureId: 'demo', name: 'runner.y', event: 'runner');
    expect(TraceWriter.spansPushed, before + 2);
  });
}
