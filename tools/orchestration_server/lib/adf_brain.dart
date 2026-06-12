import 'dart:convert';
import 'dart:io';

/// Pluggable intelligence for the ADF harness.
///
/// Brains are ordered by cost: deterministic templates (0 tokens, always
/// available) -> local Ollama model ($0 marginal cost) -> cloud LLM ->
/// cursor-agent. The harness always has a working brain because the
/// deterministic tier can never fail or cost anything.
abstract class AdfBrain {
  String get name;

  /// True when this brain consumes paid API tokens.
  bool get billsTokens;

  /// Returns enriched prose, or null when this brain cannot answer
  /// (callers fall back to the deterministic template output).
  Future<String?> complete({required String system, required String user});
}

/// Tier 0: pure templates. Never calls a model; signals callers to use
/// their deterministic generators. 0 tokens, 100% availability.
class DeterministicBrain implements AdfBrain {
  @override
  String get name => 'deterministic';

  @override
  bool get billsTokens => false;

  @override
  Future<String?> complete({required String system, required String user}) async =>
      null;
}

/// Tier 1: local Ollama model. $0 marginal cost — inference runs on this
/// machine. Used to enrich prose sections when available.
class OllamaBrain implements AdfBrain {
  OllamaBrain({String? host, String? model})
      : host = host ??
            Platform.environment['ORCH_OLLAMA_HOST'] ??
            'http://127.0.0.1:11434',
        model = model ??
            Platform.environment['ORCH_OLLAMA_MODEL'] ??
            'llama3.2';

  final String host;
  final String model;

  @override
  String get name => 'ollama:$model';

  @override
  bool get billsTokens => false;

  Future<bool> available() async {
    try {
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 2);
      final req = await client.getUrl(Uri.parse('$host/api/tags'));
      final res = await req.close().timeout(const Duration(seconds: 2));
      await res.drain<void>();
      client.close();
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String?> complete({
    required String system,
    required String user,
  }) async {
    try {
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 3);
      final req = await client.postUrl(Uri.parse('$host/api/chat'));
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode({
        'model': model,
        'stream': false,
        'messages': [
          {'role': 'system', 'content': system},
          {'role': 'user', 'content': user},
        ],
      }));
      final res = await req.close().timeout(const Duration(seconds: 60));
      final body = await res.transform(utf8.decoder).join();
      client.close();
      if (res.statusCode != 200) return null;
      final obj = jsonDecode(body) as Map<String, dynamic>;
      final msg = obj['message'] as Map<String, dynamic>?;
      final text = (msg?['content'] as String?)?.trim();
      return (text == null || text.isEmpty) ? null : text;
    } catch (_) {
      return null;
    }
  }
}

/// Picks the cheapest capable brain. `ORCH_BRAIN` forces a tier:
/// `deterministic` | `ollama` | `auto` (default).
class BrainSelector {
  BrainSelector({OllamaBrain? ollama}) : _ollama = ollama ?? OllamaBrain();

  final OllamaBrain _ollama;
  AdfBrain? _cached;

  String get mode => Platform.environment['ORCH_BRAIN'] ?? 'auto';

  Future<AdfBrain> select() async {
    if (_cached != null) return _cached!;
    switch (mode) {
      case 'deterministic':
        _cached = DeterministicBrain();
      case 'ollama':
        _cached = _ollama;
      default:
        _cached =
            await _ollama.available() ? _ollama : DeterministicBrain();
    }
    return _cached!;
  }

  Future<Map<String, dynamic>> describe() async {
    final brain = await select();
    return {
      'mode': mode,
      'active': brain.name,
      'bills_tokens': brain.billsTokens,
      'token_cost': brain.billsTokens ? 'metered' : 'zero',
    };
  }
}
