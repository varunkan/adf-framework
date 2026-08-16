import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/widgets/prompt_hero.dart';

void main() {
  testWidgets('PromptHero submits trimmed prompt and clears field',
      (tester) async {
    String? submitted;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PromptHero(onSubmit: (p) async => submitted = p),
        ),
      ),
    );

    expect(find.text('Describe it — ADF builds it'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '  add tip screen  ');
    await tester.tap(find.text('Build it'));
    await tester.pumpAndSettle();

    expect(submitted, 'add tip screen');
    expect(
      tester.widget<TextField>(find.byType(TextField)).controller!.text,
      isEmpty,
    );
  });

  testWidgets('PromptHero ignores empty prompt', (tester) async {
    var called = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PromptHero(onSubmit: (_) async => called = true),
        ),
      ),
    );
    await tester.tap(find.text('Build it'));
    await tester.pumpAndSettle();
    expect(called, isFalse);
  });
}
