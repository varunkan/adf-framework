import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/live_span_cap.dart';

void main() {
  group('capLiveSpans (MEMORY/COMPACTION)', () {
    test('keeps the most recent [max], drops the oldest', () {
      final spans = List<int>.generate(1000, (i) => i);
      capLiveSpans(spans, max: 400);
      expect(spans.length, 400);
      expect(spans.first, 600); // oldest 600 dropped
      expect(spans.last, 999); // newest kept
    });

    test('under the cap is untouched', () {
      final spans = [1, 2, 3];
      capLiveSpans(spans, max: 400);
      expect(spans, [1, 2, 3]);
    });

    test('a 90-heartbeat + thousands-event build stays bounded', () {
      final spans = List<int>.generate(5000, (i) => i);
      capLiveSpans(spans);
      expect(spans.length, kMaxLiveSpans);
    });
  });
}
