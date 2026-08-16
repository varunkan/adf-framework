import 'dart:io';

/// Keys (beyond any containing `KEY`) that repo-local env files may carry into
/// the server: LLM endpoint/model selection, chat + runner mode, and the
/// model-router tier/provider overrides.
const _allowExactKeys = {
  'ORCH_LLM_API_URL',
  'ORCH_LLM_MODEL',
  'ORCH_CHAT_LLM',
  'ORCH_OLLAMA_MODEL',
  'ORCH_OLLAMA_HOST',
  'ORCH_ROUTER',
  'ADF_RUNNER',
};

/// Prefixes whose keys are also loadable (model-router overrides).
const _allowPrefixes = ['ORCH_MODEL_', 'ORCH_NVIDIA_', 'ORCH_PROVIDER_'];

bool _isLoadableKey(String key) =>
    key.contains('KEY') ||
    _allowExactKeys.contains(key) ||
    _allowPrefixes.any(key.startsWith);

List<String> _candidateEnvFiles(String repoRoot) => [
      '$repoRoot/.env.groq.local',
      '$repoRoot/.env',
      '$repoRoot/adf-framework/.env',
      '$repoRoot/adf-framework/.env.groq.local',
    ];

/// Reads repo-local env files and returns the loadable keys as a map. Does
/// NOT mutate `Platform.environment` (which is unmodifiable) — callers merge
/// this OVER the process environment where they need the values, e.g.
/// `{...Platform.environment, ...readOrchEnv(root)}`. Earlier files in the
/// candidate list win, and an explicit process-env value always wins over a
/// file (so exported keys are never overridden).
Map<String, String> readOrchEnv(String repoRoot) {
  final out = <String, String>{};
  for (final path in _candidateEnvFiles(repoRoot)) {
    final file = File(path);
    if (!file.existsSync()) continue;
    for (final line in file.readAsLinesSync()) {
      final trimmed = line.trim();
      if (trimmed.isEmpty || trimmed.startsWith('#')) continue;
      final eq = trimmed.indexOf('=');
      if (eq <= 0) continue;
      final key = trimmed.substring(0, eq).trim();
      if (!_isLoadableKey(key)) continue;
      var value = trimmed.substring(eq + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))) {
        value = value.substring(1, value.length - 1);
      }
      if (value.isEmpty) continue;
      // First file wins; an exported process-env value always wins over files.
      final existing = Platform.environment[key];
      if (existing != null && existing.isNotEmpty) continue;
      out.putIfAbsent(key, () => value);
    }
  }
  return out;
}

/// Back-compat shim. `Platform.environment` cannot be mutated, so the historic
/// in-place loader was a silent no-op whenever a key was missing (and crashed
/// if it tried to assign). Kept as a harmless call site; callers that need the
/// values should use [readOrchEnv] and merge the result.
void loadOrchLlmEnvFiles(String repoRoot) {
  // Intentionally does nothing: env mutation is impossible. See [readOrchEnv].
}

/// True when an OpenAI-compatible HTTP LLM key is configured. Defaults to the
/// process environment; pass a merged env (process + [readOrchEnv]) to honour
/// keys that live only in a repo-local .env file.
bool orchLlmConfigured([Map<String, String>? env]) {
  final e = env ?? Platform.environment;
  final k = e['ORCH_LLM_API_KEY'] ?? e['OPENAI_API_KEY'] ?? e['GROQ_API_KEY'];
  return k != null && k.isNotEmpty;
}
