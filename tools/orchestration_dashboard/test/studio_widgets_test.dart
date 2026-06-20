import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/services/api_client.dart';
import 'package:orchestration_dashboard/theme/studio_theme.dart';
import 'package:orchestration_dashboard/widgets/live_preview_panel.dart';
import 'package:orchestration_dashboard/widgets/studio_shell.dart';

void main() {
  testWidgets('LivePreviewPanel shows phase and requirement', (tester) async {
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((_) async => http.Response(
            jsonEncode({
              'integrity': {'valid': true, 'sealed_files': 0, 'breaches': []},
              'crew': {'agents': [], 'completed': 0, 'total': 0, 'running': false},
              'artifacts': [],
              'building': false,
            }),
            200,
            headers: {'content-type': 'application/json'},
          )),
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: Scaffold(
          body: LivePreviewPanel(
            api: api,
            featureId: 'demo',
            phase: 2,
            status: 'active',
            requirement: '# Hello\n\nBuild login.',
            gates: {'spec_ready': true, 'plan_ready': false},
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('Live preview'), findsOneWidget);
    expect(find.textContaining('Phase 2'), findsOneWidget);
    expect(find.text('Run preview'), findsOneWidget);
    // The requirement lives on the Overview tab (the App tab is now the default,
    // showing the live iframe). Switch to it to assert the requirement renders.
    await tester.tap(find.text('Overview'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.textContaining('Build login'), findsOneWidget);
  });

  testWidgets('StudioShell renders chat and preview on wide screen', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1400, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: MediaQuery(
          data: const MediaQueryData(size: Size(1400, 800)),
          child: Scaffold(
            body: StudioShell(
              featureId: 'demo',
              header: const Text('Header'),
              chatContent: const Center(child: Text('ChatArea')),
              composer: const Text('Composer'),
              preview: const Center(child: Text('PreviewArea')),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('ChatArea'), findsOneWidget);
    expect(find.text('PreviewArea'), findsOneWidget);
    expect(find.text('Composer'), findsOneWidget);
  });

  testWidgets('LivePreviewPanel shows integrity badge when preview loads', (tester) async {
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        return http.Response(
          jsonEncode({
            'integrity': {'valid': true, 'sealed_files': 5, 'breaches': []},
            'crew': {'agents': [], 'completed': 0, 'total': 0, 'running': false},
            'artifacts': [],
            'building': false,
          }),
          200,
          headers: {'content-type': 'application/json', 'etag': '"v1"'},
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: Scaffold(
          body: LivePreviewPanel(
            api: api,
            featureId: 'demo',
            phase: 2,
            status: 'active',
            requirement: 'Build login',
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Live preview'), findsOneWidget);
    expect(find.textContaining('Sealed'), findsOneWidget);
  });

  testWidgets('Spec quick-action selects the Spec tab, not Data (D12)', (tester) async {
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((_) async => http.Response(
            jsonEncode({
              'integrity': {'valid': true, 'sealed_files': 0, 'breaches': []},
              'crew': {'agents': [], 'completed': 0, 'total': 0, 'running': false},
              'artifacts': [],
              'building': false,
              'spec_excerpt': '## Spec\n\nBuild the login flow.',
            }),
            200,
            headers: {'content-type': 'application/json'},
          )),
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: Scaffold(
          body: LivePreviewPanel(
            api: api,
            featureId: 'demo',
            phase: 2,
            status: 'active',
            requirement: 'Build login',
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    // Tap the 'Spec' quick-action BUTTON (above the TabBar — `.first`), not the tab.
    await tester.tap(find.text('Spec').first);
    await tester.pump(const Duration(milliseconds: 400)); // tab animation
    final tabBar = tester.widget<TabBar>(find.byType(TabBar));
    expect(tabBar.controller!.index, 3,
        reason: 'Spec is tab index 3; the action used to open Data (2)');
  });

  testWidgets('approval banner surfaces Approve + Request changes and wires them (D5)',
      (tester) async {
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((_) async => http.Response(
            jsonEncode({
              'integrity': {'valid': true, 'sealed_files': 0, 'breaches': []},
              'crew': {'agents': [], 'completed': 0, 'total': 0, 'running': false},
              'artifacts': [],
              'building': false,
            }),
            200,
            headers: {'content-type': 'application/json'},
          )),
    );
    var revised = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: Scaffold(
          body: LivePreviewPanel(
            api: api,
            featureId: 'demo',
            phase: 3,
            status: 'awaiting_approval',
            requirement: 'x',
            awaitingApproval: true,
            onApprove: () {},
            onRevise: () => revised = true,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Approve'), findsOneWidget);
    expect(find.text('Request changes'), findsOneWidget);
    // Request changes routes to onRevise (the screen opens a note dialog — it does
    // NOT blind-submit), not a direct API call.
    await tester.tap(find.text('Request changes'));
    await tester.pump();
    expect(revised, isTrue);
  });
}
