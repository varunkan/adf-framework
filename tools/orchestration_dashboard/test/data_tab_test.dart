import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/services/api_client.dart';
import 'package:orchestration_dashboard/widgets/data_tab.dart';

ApiClient _api({required Map<String, dynamic> tables, Map<String, dynamic>? rows}) =>
    ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        final p = req.url.path;
        if (p.contains('/data/')) {
          return http.Response(jsonEncode(rows ?? {}), 200);
        }
        return http.Response(jsonEncode(tables), 200);
      }),
    );

Widget _wrap(ApiClient api) => MaterialApp(
      home: Scaffold(body: DataTab(api: api, featureId: 'demo')),
    );

void main() {
  testWidgets('no DB -> friendly empty state', (tester) async {
    await tester.pumpWidget(_wrap(_api(tables: {'has_db': false})));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byKey(const Key('data-empty')), findsOneWidget);
  });

  testWidgets('lists tables and renders the first table\'s rows', (tester) async {
    final api = _api(
      tables: {
        'has_db': true,
        'tables': [
          {'name': 'notes', 'rows': 2},
          {'name': 'tags', 'rows': 0},
        ],
      },
      rows: {
        'has_db': true,
        'table': 'notes',
        'columns': ['id', 'body'],
        'rows': [
          [1, 'hello'],
          [2, 'world'],
        ],
        'truncated': false,
      },
    );
    await tester.pumpWidget(_wrap(api));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byKey(const Key('data-tab')), findsOneWidget);
    expect(find.textContaining('notes'), findsWidgets); // table chip
    expect(find.text('hello'), findsOneWidget); // a cell value
    expect(find.text('body'), findsOneWidget); // a column header
  });
}
