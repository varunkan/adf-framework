import 'dart:convert';
import 'dart:io';

import 'model_router.dart';

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
/// machine. Used to enrich prose sections and answer free-form dashboard chat.
class OllamaBrain implements AdfBrain {
  OllamaBrain({String? host, String? model, Map<String, String>? env})
      : host = host ??
            (env ?? Platform.environment)['ORCH_OLLAMA_HOST'] ??
            'http://127.0.0.1:11434',
        model = model ??
            (env ?? Platform.environment)['ORCH_OLLAMA_MODEL'] ??
            defaultModel;

  /// Nemotron Nano runs comfortably on laptop-class hardware and follows
  /// the chat instructions well — override via `ORCH_OLLAMA_MODEL`.
  static const defaultModel =
      'hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M';

  final String host;
  final String model;

  bool? _reachableCache;
  DateTime _reachableCheckedAt = DateTime.fromMillisecondsSinceEpoch(0);

  @override
  String get name => 'ollama:$model';

  @override
  bool get billsTokens => false;

  Future<bool> available() => _probe(const Duration(seconds: 2));

  /// Cached reachability for latency-sensitive callers (dashboard chat).
  /// The probe is capped at [probeTimeout] so an unreachable host can never
  /// stall a chat message, and the verdict is reused for [ttl] so the probe
  /// does not add a round-trip to every message.
  Future<bool> availableCached({
    Duration ttl = const Duration(seconds: 30),
    Duration probeTimeout = const Duration(milliseconds: 500),
  }) async {
    final cached = _reachableCache;
    if (cached != null &&
        DateTime.now().difference(_reachableCheckedAt) < ttl) {
      return cached;
    }
    final ok = await _probe(probeTimeout);
    _reachableCache = ok;
    _reachableCheckedAt = DateTime.now();
    return ok;
  }

  Future<bool> _probe(Duration timeout) async {
    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final req =
          await client.getUrl(Uri.parse('$host/api/tags')).timeout(timeout);
      final res = await req.close().timeout(timeout);
      await res.drain<void>();
      return res.statusCode == 200;
    } catch (_) {
      return false;
    } finally {
      client.close(force: true);
    }
  }

  @override
  Future<String?> complete({
    required String system,
    required String user,
  }) =>
      chat([
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
      ]);

  /// Multi-turn chat completion via `/api/chat`. Returns the assistant text,
  /// or null on any failure so callers fall through to the next tier.
  Future<String?> chat(
    List<Map<String, String>> messages, {
    Duration timeout = const Duration(seconds: 60),
    int? maxTokens,
    bool? think,
  }) async {
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 3);
    try {
      final res = await _postChat(client, messages, timeout, maxTokens, think);
      if (res == null && think != null) {
        // Some models reject the `think` field — retry once without it.
        return _extractContent(
            await _postChat(client, messages, timeout, maxTokens, null));
      }
      return _extractContent(res);
    } catch (_) {
      return null;
    } finally {
      client.close(force: true);
    }
  }

  Future<String?> _postChat(
    HttpClient client,
    List<Map<String, String>> messages,
    Duration timeout,
    int? maxTokens,
    bool? think,
  ) async {
    final req = await client.postUrl(Uri.parse('$host/api/chat'));
    req.headers.contentType = ContentType.json;
    req.write(jsonEncode({
      'model': model,
      'stream': false,
      'messages': messages,
      // Keep the model resident between questions; a cold load costs ~3s.
      'keep_alive': '30m',
      // Reasoning models burn the whole token budget on hidden thinking
      // unless it's disabled — chat needs the answer, not the chain.
      if (think != null) 'think': think,
      if (maxTokens != null) 'options': {'num_predict': maxTokens},
    }));
    final res = await req.close().timeout(timeout);
    final body = await res.transform(utf8.decoder).join();
    if (res.statusCode != 200) return null;
    return body;
  }

  String? _extractContent(String? body) {
    if (body == null) return null;
    try {
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
/// `deterministic` | `ollama` | `claude-fast` | `claude-balanced` |
/// `claude-deep` | `auto` (default).
class BrainSelector {
  BrainSelector({
    OllamaBrain? ollama,
    ModelRouter? router,
    Map<String, String>? env,
  })  : _ollama = ollama ?? OllamaBrain(env: env),
        _router = router,
        _env = env ?? Platform.environment;

  final OllamaBrain _ollama;
  final Map<String, String> _env;
  ModelRouter? _router;
  AdfBrain? _cached;

  /// Built lazily so deterministic/ollama selections never construct cloud
  /// plumbing.
  ModelRouter get router => _router ??= ModelRouter(env: _env, ollama: _ollama);

  String get mode => _env['ORCH_BRAIN'] ?? 'auto';

  Future<AdfBrain> select() async {
    if (_cached != null) return _cached!;
    switch (mode) {
      case 'deterministic':
        _cached = DeterministicBrain();
      case 'ollama':
        _cached = _ollama;
      // Cloud pins resolve through the router so the per-model
      // ClaudeApiBrain instances (and ORCH_MODEL_* overrides) are shared.
      case 'claude-fast' || 'claude-balanced' || 'claude-deep':
        _cached = router.brainForTier(mode.substring('claude-'.length));
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
