import 'dart:io';

/// Loads GROQ/OpenAI keys from repo-local env files (does not override existing env).
void loadOrchLlmEnvFiles(String repoRoot) {
  final candidates = <String>[
    '$repoRoot/.env.groq.local',
    '$repoRoot/.env',
    '$repoRoot/adf-framework/.env',
    '$repoRoot/adf-framework/.env.groq.local',
  ];
  for (final path in candidates) {
    _parseEnvFile(File(path));
  }
}

void _parseEnvFile(File file) {
  if (!file.existsSync()) return;
  for (final line in file.readAsLinesSync()) {
    final trimmed = line.trim();
    if (trimmed.isEmpty || trimmed.startsWith('#')) continue;
    final eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    final key = trimmed.substring(0, eq).trim();
    if (!key.contains('KEY') && key != 'ORCH_LLM_API_URL' && key != 'ORCH_LLM_MODEL') {
      continue;
    }
    var value = trimmed.substring(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.substring(1, value.length - 1);
    }
    if (Platform.environment[key] == null || Platform.environment[key]!.isEmpty) {
      Platform.environment[key] = value;
    }
  }
}

bool orchLlmConfigured() {
  final k = Platform.environment['ORCH_LLM_API_KEY'] ??
      Platform.environment['OPENAI_API_KEY'] ??
      Platform.environment['GROQ_API_KEY'];
  return k != null && k.isNotEmpty;
}
