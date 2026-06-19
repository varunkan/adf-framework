import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/services/live_trace_client.dart';

/// A controllable [LiveSource] for driving the self-healing state machine.
class FakeSource implements LiveSource {
  final _m = StreamController<LiveMessage>.broadcast();
  final _e = StreamController<Object>.broadcast();
  bool closed = false;

  @override
  Stream<LiveMessage> get messages => _m.stream;
  @override
  Stream<Object> get errors => _e.stream;
  @override
  Future<void> close() async {
    closed = true;
    await _m.close();
    await _e.close();
  }

  void msg(String data, [String? id]) => _m.add(LiveMessage(data, id));
  void err() => _e.add('boom');
}

LiveTraceClient build(
  FakeSource fake, {
  required void Function(Map<String, dynamic>) onSpan,
  PollFn? poll,
  int maxSseErrors = 3,
  Duration pollInterval = const Duration(milliseconds: 20),
}) =>
    LiveTraceClient(
      uri: Uri.parse('http://x/features/demo/events'),
      connect: (uri, {since}) => fake,
      poll: poll ?? ({since}) async => [],
      onSpan: onSpan,
      maxSseErrors: maxSseErrors,
      pollInterval: pollInterval,
    );

void main() {
  test('SSE messages decode to spans; state → live; cursor advances', () async {
    final fake = FakeSource();
    final spans = <Map<String, dynamic>>[];
    final c = build(fake, onSpan: spans.add);
    c.start();
    expect(c.currentState, LiveState.connecting);

    fake.msg(jsonEncode({'timestamp': 't1', 'name': 'runner.generating'}), 'sid1');
    await Future<void>.delayed(Duration.zero);

    expect(c.currentState, LiveState.live);
    expect(spans, hasLength(1));
    expect(spans.first['name'], 'runner.generating');
    expect(c.since, 't1'); // cursor advanced from the span timestamp
    await c.stop();
  });

  test('a transient error then a good frame self-heals (stays live)', () async {
    final fake = FakeSource();
    final c = build(fake, onSpan: (_) {}, maxSseErrors: 3);
    c.start();

    fake.err(); // 1 failure
    await Future<void>.delayed(Duration.zero);
    expect(c.currentState, LiveState.reconnecting);

    fake.msg(jsonEncode({'timestamp': 't', 'name': 'runner.x'}));
    await Future<void>.delayed(Duration.zero);
    expect(c.currentState, LiveState.live); // recovered → failure count reset

    fake.err();
    fake.err(); // only 2 since reset (< 3) → must NOT degrade
    await Future<void>.delayed(Duration.zero);
    expect(c.currentState, LiveState.reconnecting);
    expect(fake.closed, isFalse);
    await c.stop();
  });

  test('maxSseErrors consecutive failures degrade to the poll fallback', () async {
    final fake = FakeSource();
    final spans = <Map<String, dynamic>>[];
    var polls = 0;
    final c = build(
      fake,
      onSpan: spans.add,
      maxSseErrors: 2,
      poll: ({since}) async {
        polls++;
        return [
          {'timestamp': 'p1', 'name': 'runner.polled'}
        ];
      },
    );
    c.start();

    fake.err();
    fake.err(); // reaches 2 → degrade
    await Future<void>.delayed(const Duration(milliseconds: 40));

    expect(c.currentState, LiveState.polling);
    expect(fake.closed, isTrue); // SSE torn down
    expect(polls, greaterThanOrEqualTo(1));
    expect(spans.any((s) => s['name'] == 'runner.polled'), isTrue);
    expect(c.since, 'p1'); // cursor advanced from the poll
    await c.stop();
  });

  test('empty keep-alive and malformed frames are ignored, no crash', () async {
    final fake = FakeSource();
    final spans = <Map<String, dynamic>>[];
    final c = build(fake, onSpan: spans.add);
    c.start();

    fake.msg('   '); // whitespace keep-alive
    fake.msg('not json {'); // malformed
    fake.msg(jsonEncode({'name': 'runner.ok', 'timestamp': 't'})); // real
    await Future<void>.delayed(Duration.zero);

    expect(spans, hasLength(1));
    expect(spans.first['name'], 'runner.ok');
    await c.stop();
  });

  test('stop() tears down the source and goes idle', () async {
    final fake = FakeSource();
    final c = build(fake, onSpan: (_) {});
    c.start();
    await c.stop();
    expect(c.currentState, LiveState.idle);
    expect(fake.closed, isTrue);
  });
}
