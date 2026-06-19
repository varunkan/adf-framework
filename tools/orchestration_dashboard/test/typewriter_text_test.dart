import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/widgets/typewriter_text.dart';

String _shown(WidgetTester tester) {
  final t = tester.widget<Text>(find.descendant(
    of: find.byType(TypewriterText),
    matching: find.byType(Text),
  ));
  return (t.data ?? '').replaceAll('▍', '');
}

Widget _wrap(String text, {int minStep = 2}) => MaterialApp(
      home: Scaffold(
        body: TypewriterText(
          text,
          minStep: minStep,
          tick: const Duration(milliseconds: 10),
        ),
      ),
    );

void main() {
  testWidgets('reveals progressively, then settles on the full text',
      (tester) async {
    await tester.pumpWidget(_wrap('hello world'));
    expect(_shown(tester).length, 0); // nothing revealed on first frame

    await tester.pump(const Duration(milliseconds: 30)); // ~3 ticks * 2 chars
    final mid = _shown(tester).length;
    expect(mid, greaterThan(0));
    expect(mid, lessThan('hello world'.length));

    await tester.pump(const Duration(milliseconds: 300)); // finish (cancels timer)
    expect(_shown(tester), 'hello world');
  });

  testWidgets('a streaming append keeps the revealed prefix (no retype)',
      (tester) async {
    await tester.pumpWidget(_wrap('abcdefghij', minStep: 100));
    await tester.pump(const Duration(milliseconds: 10)); // minStep 100 → all shown
    expect(_shown(tester), 'abcdefghij');

    // Grow the text (next token batch appends) — prefix must be preserved.
    await tester.pumpWidget(_wrap('abcdefghijKLMNOP', minStep: 100));
    await tester.pump(); // didUpdateWidget continues from _shown=10
    expect(_shown(tester).startsWith('abcdefghij'), isTrue);
    await tester.pump(const Duration(milliseconds: 10)); // finish
    expect(_shown(tester), 'abcdefghijKLMNOP');
  });

  testWidgets('an unrelated new string retypes from zero', (tester) async {
    await tester.pumpWidget(_wrap('first line done', minStep: 100));
    await tester.pump(const Duration(milliseconds: 10));
    expect(_shown(tester), 'first line done');

    await tester.pumpWidget(_wrap('a totally new line', minStep: 1));
    await tester.pump(const Duration(milliseconds: 10)); // 1 tick, minStep 1
    final after = _shown(tester);
    expect(after.length, lessThan(5)); // retyping from scratch, not jumped to full
    expect('a totally new line'.startsWith(after), isTrue);

    await tester.pump(const Duration(milliseconds: 500)); // finish (cancels timer)
    expect(_shown(tester), 'a totally new line');
  });
}
