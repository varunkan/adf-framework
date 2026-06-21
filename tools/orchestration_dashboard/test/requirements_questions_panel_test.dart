import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/widgets/requirements_questions_panel.dart';

void main() {
  group('RequirementsQuestionsPanel (P3)', () {
    testWidgets('renders the numbered questions + the answer hint', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: RequirementsQuestionsPanel(
            questions: ['Which eCTD modules: 1 or 1-5?', 'Single tenant?'],
          ),
        ),
      ));
      expect(find.textContaining('Confirm before building (2)'), findsOneWidget);
      expect(find.textContaining('1. Which eCTD modules'), findsOneWidget);
      expect(find.textContaining('2. Single tenant?'), findsOneWidget);
      expect(find.textContaining('Answer these in chat'), findsOneWidget);
    });

    testWidgets('renders nothing when there are no questions', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: RequirementsQuestionsPanel(questions: [])),
      ));
      expect(find.byType(Card), findsNothing);
    });

    test('fromDetail extracts the questions list, tolerating bad shapes', () {
      expect(
          RequirementsQuestionsPanel.fromDetail(
              {'requirements_open_questions': ['a', 'b']}),
          ['a', 'b']);
      expect(RequirementsQuestionsPanel.fromDetail({}), isEmpty);
      expect(RequirementsQuestionsPanel.fromDetail(null), isEmpty);
      expect(
          RequirementsQuestionsPanel.fromDetail(
              {'requirements_open_questions': 'not-a-list'}),
          isEmpty);
    });
  });
}
