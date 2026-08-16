@Timeout(Duration(seconds: 30))
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/trace_writer.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as io;
import 'package:shelf_router/shelf_router.dart';
import 'package:test/test.dart';

/// Proves the SSE route works over a REAL socket: shelf streams the response with
/// buffering OFF (so each frame flushes immediately), and the live broadcast tail
/// reaches the client filtered by feature_id. If buffer_output weren't honored the
/// frame would never arrive and the 10s firstWhere timeout would fail this fast.
void main() {
  test('GET /events flushes live spans over HTTP, filtered by feature', () async {
    final router = Router();
    router.get('/features/<id>/events', (Request req, String id) {
      final controller = StreamController<List<int>>();
      // Flush headers immediately (shelf sends headers only on the first body byte).
      controller.add(utf8.encode('retry: 3000\n: connected\n\n'));
      final sub = TraceWriter.events
          .where((r) => (r['attributes'] as Map?)?['orch.feature_id'] == id)
          .listen((r) {
        if (!controller.isClosed) controller.add(TraceWriter.sseEvent(r));
      });
      controller.onCancel = sub.cancel;
      return Response.ok(
        controller.stream,
        headers: {'Content-Type': 'text/event-stream'},
        context: const {'shelf.io.buffer_output': false},
      );
    });

    final server = await io.serve(router.call, '127.0.0.1', 0);
    addTearDown(() => server.close(force: true));
    final client = HttpClient();
    addTearDown(() => client.close(force: true));

    final resp = await (await client.getUrl(Uri.parse(
            'http://127.0.0.1:${server.port}/features/demo/events')))
        .close();
    expect(resp.headers.contentType.toString(), contains('text/event-stream'));

    // Subscribe for the first matching frame BEFORE appending.
    final firstFrame = resp
        .transform(utf8.decoder)
        .firstWhere((c) => c.contains('verify_result'))
        .timeout(const Duration(seconds: 10));

    await Future<void>.delayed(const Duration(milliseconds: 150));
    final tmp = Directory.systemTemp.createTempSync('adf-sse-http');
    addTearDown(() => tmp.deleteSync(recursive: true));
    final tw = TraceWriter(tmp.path);
    tw.append(
        featureId: 'other', name: 'runner.noise', event: 'runner', message: 'nope');
    tw.append(
        featureId: 'demo',
        name: 'runner.verify_result',
        event: 'runner',
        message: 'Verification passed OK');

    final frame = await firstFrame;
    expect(frame, contains('data: '));
    expect(frame, contains('Verification passed'));
    expect(frame, isNot(contains('noise'))); // feature filter held
  });
}
