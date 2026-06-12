import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/main.dart';
import 'package:orchestration_dashboard/services/api_client.dart';

void main() {
  testWidgets('dashboard app loads feature list shell', (tester) async {
    await tester.pumpWidget(
      OrchestrationDashboardApp(
        api: ApiClient(baseUrl: 'http://127.0.0.1:3847'),
      ),
    );
    await tester.pump();
    expect(find.text('ADF Studio'), findsOneWidget);
  });
}
