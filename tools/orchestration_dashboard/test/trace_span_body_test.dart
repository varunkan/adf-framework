import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/models/trace_span.dart';

void main() {
  test('a tool span body is the NL sentence; raw JSON is not surfaced (D1)', () {
    final span = TraceSpan.fromJson({
      'name': 'tool.use',
      'attributes': {
        'tool.name': 'read_file',
        'tool.input': '{"file_path":"lib/db.dart"}',
      },
    });
    expect(span.body, 'Reading lib/db.dart');
    // No raw JSON / "Tool:" / "Input:" leaks into the rendered body.
    expect(span.body, isNot(contains('Input:')));
    expect(span.body, isNot(contains('{')));
  });

  test('a runner narration span body is its message', () {
    final span = TraceSpan.fromJson({
      'name': 'runner.verify_stage',
      'attributes': {'orch.message': 'Running vitest…'},
    });
    expect(span.body, 'Running vitest…');
  });

  test('generating_progress maps to the GENERATE card (D2 heartbeat, E11)', () {
    final span = TraceSpan.fromJson({
      'name': 'runner.generating_progress',
      'attributes': {'orch.message': 'Generating code… (12s)'},
    });
    expect(span.cardKind, 'GENERATE');
  });
}
