import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/theme/studio_theme.dart';
import 'package:orchestration_dashboard/widgets/cost_badge.dart';

void main() {
  testWidgets('CostBadge shows green zero-cost local chip', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: const Scaffold(
          body: CostBadge(
            cost: {
              'feature_id': 'demo',
              'total_usd': 0,
              'total_input_tokens': 0,
              'total_output_tokens': 0,
              'zero_cost': true,
              'runs': [],
            },
          ),
        ),
      ),
    );
    expect(find.text(r'LLM cost: $0.00 · local'), findsOneWidget);
    final text = tester.widget<Text>(find.text(r'LLM cost: $0.00 · local'));
    expect(text.style?.color, Colors.greenAccent);
  });

  testWidgets('CostBadge shows metered amount with token tooltip', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: const Scaffold(
          body: CostBadge(
            cost: {
              'feature_id': 'demo',
              'total_usd': 1.2345,
              'total_input_tokens': 12345,
              'total_output_tokens': 678,
              'zero_cost': false,
              'runs': [
                {
                  'at': '2026-06-12T00:00:00Z',
                  'phase': 7,
                  'usd': 1.2345,
                  'input_tokens': 12345,
                  'output_tokens': 678,
                  'source': 'reported',
                },
              ],
            },
          ),
        ),
      ),
    );
    expect(find.text(r'LLM cost: $1.23'), findsOneWidget);
    final tooltip = tester.widget<Tooltip>(find.byType(Tooltip));
    expect(tooltip.message, '12,345 in · 678 out tokens');
  });

  testWidgets('CostBadge renders nothing without a payload', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: const Scaffold(body: CostBadge()),
      ),
    );
    expect(find.textContaining('LLM cost'), findsNothing);
  });
}
