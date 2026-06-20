import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/widgets/revision_dialog.dart';

void main() {
  group('promptRevisionNote (D5)', () {
    // Each test pumps a button whose async onPressed records the returned note
    // into `captured`, which is asserted AFTER the full dialog interaction.
    Future<void> pumpOpener(WidgetTester tester, void Function(String?) sink) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (ctx) => ElevatedButton(
              onPressed: () async => sink(await promptRevisionNote(ctx)),
              child: const Text('open'),
            ),
          ),
        ),
      ));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
    }

    testWidgets('captures the typed note on submit', (tester) async {
      String? captured;
      await pumpOpener(tester, (v) => captured = v);
      await tester.enterText(find.byType(TextField), 'tighten the validation');
      await tester.tap(find.widgetWithText(FilledButton, 'Request changes'));
      await tester.pumpAndSettle();
      expect(captured, 'tighten the validation');
    });

    testWidgets('returns null on cancel', (tester) async {
      String? captured = 'sentinel';
      await pumpOpener(tester, (v) => captured = v);
      await tester.enterText(find.byType(TextField), 'ignored');
      await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
      await tester.pumpAndSettle();
      expect(captured, isNull);
    });

    testWidgets('empty note == cancelled (no blind submit)', (tester) async {
      String? captured = 'sentinel';
      await pumpOpener(tester, (v) => captured = v);
      await tester.tap(find.widgetWithText(FilledButton, 'Request changes'));
      await tester.pumpAndSettle();
      expect(captured, isNull);
    });
  });
}
