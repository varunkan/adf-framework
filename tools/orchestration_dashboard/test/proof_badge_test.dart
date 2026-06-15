import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/services/api_client.dart';
import 'package:orchestration_dashboard/widgets/proof_badge.dart';

ApiClient _api(Map<String, dynamic> proof) => ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async => http.Response(jsonEncode(proof), 200)),
    );

Widget _wrap(ApiClient api) => MaterialApp(
      home: Scaffold(body: ProofBadge(api: api, featureId: 'demo')),
    );

void main() {
  testWidgets('shows VERIFIED with the seal when the proof holds', (tester) async {
    await tester.pumpWidget(_wrap(_api({
      'has_proof': true,
      'ok': true,
      'status': 'VERIFIED',
      'seal': 'adf1:521bbfe29991',
      'n_files': 17,
      'files': [],
    })));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byKey(const Key('proof-badge')), findsOneWidget);
    expect(find.textContaining('Verified'), findsOneWidget);
    expect(find.textContaining('adf1:521bbfe29991'), findsOneWidget);
    expect(find.byIcon(Icons.verified_user), findsOneWidget);
  });

  testWidgets('shows TAMPERED when a file diverges from the seal', (tester) async {
    await tester.pumpWidget(_wrap(_api({
      'has_proof': true,
      'ok': false,
      'status': 'TAMPERED',
      'seal': 'adf1:521bbfe29991',
      'files': [
        {'path': 'src/App.tsx', 'status': 'modified'},
      ],
    })));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('TAMPERED'), findsOneWidget);
    expect(find.byIcon(Icons.gpp_bad), findsOneWidget);
  });

  testWidgets('shows "No proof yet" when the app carries no seal', (tester) async {
    await tester.pumpWidget(_wrap(_api({'has_proof': false})));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.textContaining('No proof'), findsOneWidget);
  });
}
