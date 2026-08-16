import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/models/trace_span.dart';
import 'package:orchestration_dashboard/utils/plain_thought_formatter.dart';

void main() {
  test('merges reasoning into plain sentences', () {
    final spans = [
      TraceSpan(
        timestamp: '2026-01-01T00:00:01Z',
        name: 'agent.stream',
        status: 'OK',
        attributes: {
          'agent.reasoning':
              'Exploring how judge recommendations are stored and how the clarify/redo flow works',
        },
      ),
      TraceSpan(
        timestamp: '2026-01-01T00:00:02Z',
        name: 'agent.stream',
        status: 'OK',
        attributes: {
          'agent.reasoning':
              ' so we can wire combined recommendations into the orchestrator feedback loop.',
        },
      ),
    ];

    final lines = PlainThoughtFormatter.format(spans);
    expect(lines.length, 1);
    expect(
      lines.first,
      contains('Exploring how judge recommendations'),
    );
    expect(lines.first, contains('feedback loop'));
  });

  test('hides runner cancel/supersede control spans from thought lines', () {
    final spans = [
      TraceSpan(
        timestamp: '2026-01-01T00:00:01Z',
        name: 'runner.cancelled',
        status: 'OK',
        attributes: {
          'runner.message': 'Run cancelled by user',
        },
      ),
      TraceSpan(
        timestamp: '2026-01-01T00:00:02Z',
        name: 'agent.stream',
        status: 'OK',
        attributes: {
          'agent.reasoning': 'Updating requirement.md for standalone product.',
        },
      ),
    ];

    final lines = PlainThoughtFormatter.format(spans);
    expect(lines, isNot(contains('runner.cancelled')));
    expect(lines, isNot(contains('Run cancelled by user')));
    expect(lines.length, 1);
    expect(lines.first, contains('standalone product'));
  });

  test('renders crew narration spans from orch.message (no dead-air)', () {
    final spans = [
      TraceSpan(
        timestamp: '2026-01-01T00:00:01Z',
        name: 'crew.wave_start',
        status: 'OK',
        attributes: {
          'hook.event': 'crew',
          'orch.message': 'Wave 1: product-analyst',
        },
      ),
      TraceSpan(
        timestamp: '2026-01-01T00:00:02Z',
        name: 'crew.agent_done',
        status: 'OK',
        attributes: {
          'hook.event': 'crew',
          'orch.phase': 2,
          'orch.message': 'spec-writer — EARS requirements',
        },
      ),
    ];

    final lines = PlainThoughtFormatter.format(spans);
    final joined = lines.join(' | ');
    expect(joined, contains('Wave 1: product-analyst'));
    expect(joined, contains('spec-writer'));
    // The raw span name must never leak into the user-facing narration.
    expect(joined, isNot(contains('crew.wave_start')));
  });

  test('hides runner.superseded control spans from thought lines', () {
    final spans = [
      TraceSpan(
        timestamp: '2026-01-01T00:00:01Z',
        name: 'runner.superseded',
        status: 'OK',
        attributes: {
          'runner.message': 'Previous run stopped for a newer client message',
        },
      ),
    ];

    expect(PlainThoughtFormatter.format(spans), isEmpty);
  });
}
