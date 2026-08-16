import 'dart:convert';
import 'dart:io';

import 'adf_brain.dart';

/// Cloud tier: the Anthropic Messages API over raw HTTP.
///
/// There is no official Anthropic SDK for Dart, so this speaks the wire
/// protocol directly: `POST /v1/messages` with `x-api-key`,
/// `anthropic-version: 2023-06-01` and `content-type: application/json`
/// headers. Adaptive thinking is sent only for the deep-tier Opus model;
/// sampling parameters (`temperature`/`top_p`/`top_k`) are never sent —
/// they 400 on Opus 4.7+.
///
/// Every failure path — missing key, timeout, non-200, malformed body —
/// returns null so callers fall through to the next tier, matching the
/// [AdfBrain] contract.
class ClaudeApiBrain implements AdfBrain {
  ClaudeApiBrain({
    required this.model,
    String? baseUrl,
    Map<String, String>? env,
    this.onUsage,
  })  : baseUrl = baseUrl ?? _envBaseUrl(env ?? Platform.environment),
        _env = env ?? Platform.environment;

  static const defaultBaseUrl = 'https://api.anthropic.com';

  /// Honors `ANTHROPIC_BASE_URL` (Anthropic SDK convention) so calls can be
  /// routed through a local proxy (e.g. the headroom context-compression
  /// proxy) without code changes. Falls back to the public API.
  static String _envBaseUrl(Map<String, String> env) {
    final v = env['ANTHROPIC_BASE_URL']?.trim();
    return (v == null || v.isEmpty) ? defaultBaseUrl : v;
  }
  static const apiVersion = '2023-06-01';

  /// Chat-sized default; callers raise it for artifact-sized completions.
  static const defaultMaxTokens = 1024;

  /// `ORCH_AGENT_TIMEOUT_SEC` fallback per the timeout contract.
  static const defaultTimeoutSec = 30;

  /// USD per million tokens as (input, output) — 2026-06 price table.
  static const pricePerMTok = <String, (double, double)>{
    'claude-haiku-4-5': (1.0, 5.0),
    'claude-sonnet-4-6': (3.0, 15.0),
    'claude-opus-4-8': (5.0, 25.0),
  };

  final String model;
  final String baseUrl;
  final Map<String, String> _env;

  /// Receives a stream-json style result event after every billed call:
  /// `{"type":"result","total_cost_usd":X,"usage":{"input_tokens":N,
  /// "output_tokens":M}}` — the exact shape
  /// `CostMeter.recordFromResultEvent` consumes. `total_cost_usd` is
  /// omitted for models outside [pricePerMTok] so the meter can fall back
  /// to its env per-MTok rates.
  final void Function(Map<String, dynamic> event)? onUsage;

  @override
  String get name => 'claude:$model';

  @override
  bool get billsTokens => true;

  /// True when `ANTHROPIC_API_KEY` is present — without it [chat] returns
  /// null immediately and the router degrades to local-only.
  bool get hasApiKey => _apiKey != null;

  @override
  Future<String?> complete({required String system, required String user}) =>
      chat([
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
      ]);

  /// Multi-turn chat via `POST /v1/messages`. System-role messages are
  /// hoisted into the API's top-level `system` field. Returns the first
  /// text block of the reply, or null on any failure. The whole call —
  /// connect, write, read — is capped at [timeout] (default
  /// `ORCH_AGENT_TIMEOUT_SEC`, 30s).
  Future<String?> chat(
    List<Map<String, String>> messages, {
    int maxTokens = defaultMaxTokens,
    Duration? timeout,
  }) async {
    final key = _apiKey;
    if (key == null) return null;
    final budget = timeout ?? _envTimeout;
    final client = HttpClient()..connectionTimeout = budget;
    try {
      return await _post(client, key, messages, maxTokens).timeout(budget);
    } catch (_) {
      return null;
    } finally {
      client.close(force: true);
    }
  }

  String? get _apiKey {
    final key = _env['ANTHROPIC_API_KEY']?.trim();
    return (key == null || key.isEmpty) ? null : key;
  }

  Duration get _envTimeout {
    final secs = int.tryParse(_env['ORCH_AGENT_TIMEOUT_SEC'] ?? '');
    return Duration(
        seconds: (secs == null || secs <= 0) ? defaultTimeoutSec : secs);
  }

  /// Adaptive thinking is supported on the deep-tier Opus models only;
  /// sending it to Haiku/Sonnet tiers is out of contract for the router.
  bool get _sendsAdaptiveThinking => model.startsWith('claude-opus');

  /// Prompt caching is ON by default (`ORCH_PROMPT_CACHE=0` to disable). The
  /// system prefix (constitution/spec/context) is byte-identical across the
  /// many parallel agent turns and self-heal retries, so caching it turns N
  /// re-transmissions into 1 write (~1.25x) + (N-1) reads (~0.1x).
  bool get _promptCacheOn {
    final v = _env['ORCH_PROMPT_CACHE'];
    return v != '0' && v != 'false' && v != 'off';
  }

  /// Below the provider's cacheable minimum (~1024 tokens) `cache_control` is
  /// ignored, so only mark prompts worth caching. ~4 chars/token heuristic.
  int get _promptCacheMinChars =>
      int.tryParse(_env['ORCH_PROMPT_CACHE_MIN_CHARS'] ?? '') ?? 4096;

  Future<String?> _post(
    HttpClient client,
    String key,
    List<Map<String, String>> messages,
    int maxTokens,
  ) async {
    final system = messages
        .where((m) => m['role'] == 'system')
        .map((m) => m['content'] ?? '')
        .where((c) => c.isNotEmpty)
        .join('\n\n');
    final turns = messages.where((m) => m['role'] != 'system').toList();
    if (turns.isEmpty) return null;

    // Mark the stable system prefix as an ephemeral cache breakpoint when it is
    // large enough to cache; otherwise send the plain string (no benefit, and
    // keeps tiny prompts byte-compatible with the legacy request shape).
    final cacheSystem =
        system.isNotEmpty && _promptCacheOn && system.length >= _promptCacheMinChars;

    final req = await client.postUrl(Uri.parse('$baseUrl/v1/messages'));
    req.headers
      ..set('x-api-key', key)
      ..set('anthropic-version', apiVersion)
      ..contentType = ContentType.json;
    req.write(jsonEncode({
      'model': model,
      'max_tokens': maxTokens,
      if (system.isNotEmpty)
        'system': cacheSystem
            ? [
                {
                  'type': 'text',
                  'text': system,
                  'cache_control': {'type': 'ephemeral'},
                }
              ]
            : system,
      'messages': turns,
      // Never add temperature/top_p/top_k here — they 400 on Opus 4.7+.
      if (_sendsAdaptiveThinking) 'thinking': {'type': 'adaptive'},
    }));
    final res = await req.close();
    final body = await res.transform(utf8.decoder).join();
    if (res.statusCode != 200) return null;
    return _parse(body);
  }

  String? _parse(String body) {
    try {
      final obj = jsonDecode(body) as Map<String, dynamic>;
      // Tokens were billed even when the text turns out unusable.
      _reportUsage(obj['usage']);
      final content = obj['content'] as List? ?? const [];
      final block = content.whereType<Map>().firstWhere(
            (b) => b['type'] == 'text',
            orElse: () => const <String, dynamic>{},
          );
      final text = (block['text'] as String?)?.trim();
      return (text == null || text.isEmpty) ? null : text;
    } catch (_) {
      return null;
    }
  }

  void _reportUsage(Object? usage) {
    final report = onUsage;
    if (report == null || usage is! Map) return;
    final inputTokens = _toInt(usage['input_tokens']);
    final outputTokens = _toInt(usage['output_tokens']);
    // Cache tokens are reported separately from input_tokens by Anthropic:
    // writes bill ~1.25x input, reads ~0.10x input. This is where the prompt
    // cache pays off — a cache_read is ~10x cheaper than re-sending the prefix.
    final cacheWrite = _toInt(usage['cache_creation_input_tokens']);
    final cacheRead = _toInt(usage['cache_read_input_tokens']);
    final price = pricePerMTok[model];
    report({
      'type': 'result',
      if (price != null)
        'total_cost_usd':
            (inputTokens + cacheWrite * 1.25 + cacheRead * 0.10) * price.$1 / 1e6 +
                outputTokens * price.$2 / 1e6,
      'usage': {
        'input_tokens': inputTokens,
        'output_tokens': outputTokens,
        if (cacheWrite > 0) 'cache_creation_input_tokens': cacheWrite,
        if (cacheRead > 0) 'cache_read_input_tokens': cacheRead,
      },
    });
  }

  static int _toInt(Object? v) => v is num ? v.toInt() : 0;
}
