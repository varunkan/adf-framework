import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/screens/new_feature_screen.dart';
import 'package:orchestration_dashboard/services/api_client.dart';

/// N8 (stack-select) — the dashboard's New-feature flow defaults to the real
/// React+Vite+SQLite stack and sends the chosen stack to POST /features so the
/// runner builds with the matching StackProfile (contract C5).
void main() {
  testWidgets('New-feature picker defaults to React+Vite+SQLite', (tester) async {
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((_) async => http.Response('{}', 200)),
    );
    await tester.pumpWidget(MaterialApp(home: NewFeatureScreen(api: api)));

    expect(find.byKey(const Key('stack-picker')), findsOneWidget);
    // The default selection is the modern stack, not the single-file fallback.
    expect(find.text('React + Vite + Tailwind + SQLite'), findsOneWidget);
  });

  testWidgets('Creating a feature sends the selected stack in the request body',
      (tester) async {
    final bodies = <Map<String, dynamic>>[];
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        bodies.add(jsonDecode(req.body) as Map<String, dynamic>);
        return http.Response(jsonEncode({'id': 'demo', 'mode': 'ide_only'}), 201);
      }),
    );
    await tester.pumpWidget(MaterialApp(home: NewFeatureScreen(api: api)));

    await tester.enterText(find.byType(TextField).first, 'demo-app');
    await tester.enterText(find.byType(TextField).last, 'A demo requirement');
    await tester.tap(find.text('Create feature'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(bodies, isNotEmpty);
    expect(bodies.first['stack'], 'react-vite-sqlite');
  });

  test('ApiClient.createFeature passes an explicit stack through', () async {
    Map<String, dynamic>? body;
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        body = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'id': 'x'}), 201);
      }),
    );
    await api.createFeature(
      id: 'x',
      requirement: 'r',
      track: 'S',
      stack: 'stdlib',
    );
    expect(body?['stack'], 'stdlib');
  });
}
