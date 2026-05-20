import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'config/api_config.dart';
import 'screens/feature_list_screen.dart';
import 'services/api_client.dart';
import 'theme/app_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final apiUrl = defaultOrchestrationApiUrl();
  runApp(OrchestrationDashboardApp(api: ApiClient(baseUrl: apiUrl)));
}

class OrchestrationDashboardApp extends StatelessWidget {
  const OrchestrationDashboardApp({super.key, required this.api});

  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Orchestration',
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      home: FeatureListScreen(api: api),
    );
  }
}

void showMessage(BuildContext context, String text) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(text), duration: const Duration(seconds: 4)),
  );
}

Future<void> copyCursorPrompt(BuildContext context, String prompt) async {
  await Clipboard.setData(ClipboardData(text: prompt));
  if (context.mounted) {
    showMessage(context, 'Copied to clipboard');
  }
}
