import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/services/api_client.dart';
import 'package:orchestration_dashboard/widgets/export_button.dart';

ApiClient _api(Map<String, dynamic> resp) => ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async => http.Response(jsonEncode(resp), 200)),
    );

Widget _wrap(ApiClient api) => MaterialApp(
      home: Scaffold(body: ExportButton(api: api, featureId: 'demo')),
    );

void main() {
  testWidgets('exports and reports the portable zip', (tester) async {
    await tester.pumpWidget(_wrap(_api({
      'ok': true,
      'out': '/repo/.adf-exports/demo.zip',
      'files': 18,
      'bytes': 40960,
    })));
    expect(find.byKey(const Key('export-button')), findsOneWidget);
    expect(find.textContaining('Export'), findsOneWidget);

    await tester.tap(find.text('Export (own your code)'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.textContaining('Exported 18 files'), findsOneWidget);
    expect(find.textContaining('demo.zip'), findsOneWidget);
  });
}
