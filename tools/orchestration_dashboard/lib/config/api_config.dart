import 'package:flutter/foundation.dart';

/// Web dashboard runs at http://localhost:3848 — API must use **localhost** (not
/// 127.0.0.1) or the browser blocks requests (CORS / mixed origin).
String defaultOrchestrationApiUrl() {
  const fromEnv = String.fromEnvironment('ORCH_API_URL');
  if (fromEnv.isNotEmpty) return fromEnv;
  if (kIsWeb) return 'http://localhost:3847';
  return 'http://127.0.0.1:3847';
}
