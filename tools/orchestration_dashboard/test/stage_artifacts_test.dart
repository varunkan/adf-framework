import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/services/api_client.dart';
import 'package:orchestration_dashboard/widgets/stage_artifacts.dart';

ApiClient _api({required Map<String, dynamic> artifacts, String content = ''}) =>
    ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        if (req.url.path.contains('/artifact') &&
            req.url.queryParameters.containsKey('path')) {
          return http.Response(
              jsonEncode({'path': 'x', 'content': content}), 200);
        }
        return http.Response(jsonEncode({'artifacts': artifacts}), 200);
      }),
    );

Widget _wrap(ApiClient api) => MaterialApp(
      home: Scaffold(body: StageArtifacts(api: api, featureId: 'demo')),
    );

void main() {
  group('phaseForArtifact', () {
    test('maps each artifact filename to its stage', () {
      expect(phaseForArtifact('problem-statement.md'), 1);
      expect(phaseForArtifact('spec.md'), 2);
      expect(phaseForArtifact('plan.md'), 3);
      expect(phaseForArtifact('tasks.md'), 4);
      expect(phaseForArtifact('task-graph.yaml'), 4);
      expect(phaseForArtifact('test-cases.md'), 5);
      expect(phaseForArtifact('test-plan.md'), 5);
      expect(phaseForArtifact('traceability-matrix.md'), 6);
      expect(phaseForArtifact('App.tsx'), 7);
    });
  });

  testWidgets('empty when there are no artifacts', (tester) async {
    await tester.pumpWidget(_wrap(_api(artifacts: {})));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byKey(const Key('stage-artifacts-empty')), findsOneWidget);
  });

  testWidgets('groups artifacts by stage and opens content on tap',
      (tester) async {
    final api = _api(
      artifacts: {
        'spec': [
          {'name': 'spec.md', 'path': 'specs/demo/spec.md', 'bytes': 120},
          {'name': 'plan.md', 'path': 'specs/demo/plan.md', 'bytes': 200},
        ],
        'code': [
          {'name': 'App.tsx', 'path': 'apps/demo/src/App.tsx', 'bytes': 500},
        ],
      },
      content: '# Spec\n\nThe requirements.',
    );
    await tester.pumpWidget(_wrap(api));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byKey(const Key('stage-artifacts')), findsOneWidget);
    // stage sections present (Spec=2, Plan=3, Code=7)
    expect(find.byKey(const Key('stage-2')), findsOneWidget);
    expect(find.byKey(const Key('stage-7')), findsOneWidget);
    expect(find.text('spec.md'), findsOneWidget);

    // tapping an artifact fetches + shows its content in a dialog
    await tester.tap(find.text('spec.md'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.textContaining('requirements'), findsOneWidget);
  });
}
