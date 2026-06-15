import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/services/api_client.dart';
import 'package:orchestration_dashboard/utils/message_classifier.dart';
import 'package:orchestration_dashboard/widgets/context_chip.dart';

ApiClient _api(Map<String, dynamic> context) => ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        if (req.url.path.endsWith('/compact')) {
          return http.Response(
              jsonEncode({...context, 'did_compact': true}), 200);
        }
        return http.Response(jsonEncode(context), 200);
      }),
    );

Widget _wrap(ApiClient api) => MaterialApp(
      home: Scaffold(body: ContextChip(api: api, featureId: 'demo')),
    );

void main() {
  group('isCompactCommand', () {
    test('exactly /compact (any case / padding) is the command', () {
      expect(isCompactCommand('/compact'), isTrue);
      expect(isCompactCommand('  /COMPACT '), isTrue);
    });
    test('ordinary chat + edits are NOT the command', () {
      expect(isCompactCommand('compact the layout'), isFalse);
      expect(isCompactCommand('make the header blue'), isFalse);
      expect(isCompactCommand(''), isFalse);
    });
  });

  testWidgets('chip shows the context size against the budget', (tester) async {
    await tester.pumpWidget(_wrap(_api({
      'has_app': true,
      'tokens': 12000,
      'budget': 120000,
      'over': false,
      'n_files': 9,
    })));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byKey(const Key('context-chip')), findsOneWidget);
    expect(find.textContaining('12'), findsOneWidget); // ~12k shown
  });

  testWidgets('over budget, the chip flags it and offers Compact',
      (tester) async {
    await tester.pumpWidget(_wrap(_api({
      'has_app': true,
      'tokens': 240000,
      'budget': 120000,
      'over': true,
      'n_files': 40,
    })));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.textContaining('Compact'), findsOneWidget);
    // Tapping triggers a compaction without throwing.
    await tester.tap(find.byKey(const Key('context-chip')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  });
}
