import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/screens/feature_list_screen.dart';
import 'package:orchestration_dashboard/services/api_client.dart';
import 'package:orchestration_dashboard/theme/studio_theme.dart';

void main() {
  testWidgets('FeatureListScreen shows ADF Studio branding', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: StudioTheme.dark(),
        home: FeatureListScreen(
          api: ApiClient(baseUrl: 'http://127.0.0.1:1'),
        ),
      ),
    );
    await tester.pump();
    expect(find.text('ADF Studio'), findsWidgets);
  });
}
