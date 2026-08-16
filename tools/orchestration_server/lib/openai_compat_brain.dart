import 'dart:convert';
import 'dart:io';

import 'adf_brain.dart';

/// Cloud tier for any OpenAI-compatible Chat Completions endpoint.
///
/// NVIDIA's build.nvidia.com (NIM) catalog, Groq, OpenRouter, Together, vLLM
/// and OpenAI itself all speak the same wire protocol: `POST
/// /v1/chat/completions` with `Authorization: Bearer <key>`, a `messages`
/// array, and a reply in `choices[0].message.content`. This one brain serves
/// all of them — [baseUrl] selects the provider, [model] the model id.
///
/// The default configuration targets NVIDIA NIM, which gives free
/// (rate-limited) access to top open models — Llama 3.3 70B, Qwen2.5-Coder
/// 32B, DeepSeek-R1, Nemotron — so [billsTokens] defaults to false. Set it
/// true (and supply [pricePerMTok]) for a paid endpoint.
///
/// Every failure path — missing key, timeout, non-200, malformed body —
/// returns null so callers fall through to the next tier, matching the
/// [AdfBrain] contract.
class OpenAiCompatBrain implements AdfBrain {
  OpenAiCompatBrain({
    required this.model,
    required this.baseUrl,
    required String apiKey,
    this.providerLabel = 'openai',
    this.billsTokens = false,
    this.pricePerMTok = const {},
    Map<String, String>? env,
    this.onUsage,
  })  : _apiKey = apiKey.trim(),
        _env = env ?? Platform.environment;

  /// NVIDIA's OpenAI-compatible API root (no trailing slash, no path).
  static const nvidiaBaseUrl = 'https://integrate.api.nvidia.com/v1';

  /// Chat-sized default; callers raise it for artifact-sized completions.
  static const defaultMaxTokens = 1024;

  /// `ORCH_AGENT_TIMEOUT_SEC` fallback per the timeout contract.
  static const defaultTimeoutSec = 30;

  final String model;
  final String baseUrl;
  final String providerLabel;

  @override
  final bool billsTokens;

  /// USD per million tokens as (input, output), keyed by model id. Empty for
  /// free endpoints (e.g. NVIDIA NIM) — then [onUsage] reports token counts
  /// with no `total_cost_usd`, so the cost meter records $0.
  final Map<String, (double, double)> pricePerMTok;

  final String _apiKey;
  final Map<String, String> _env;

  /// Receives a stream-json style result event after every call, the exact
  /// shape `CostMeter.recordFromResultEvent` consumes. `total_cost_usd` is
  /// included only when [pricePerMTok] prices [model].
  final void Function(Map<String, dynamic> event)? onUsage;

  @override
  String get name => '$providerLabel:$model';

  bool get hasApiKey => _apiKey.isNotEmpty;

  @override
  Future<String?> complete({required String system, required String user}) =>
      chat([
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
      ]);

  /// Multi-turn chat via `POST /v1/chat/completions`. Returns the assistant
  /// text, or null on any failure. The whole call — connect, write, read — is
  /// capped at [timeout] (default `ORCH_AGENT_TIMEOUT_SEC`, 30s).
  Future<String?> chat(
    List<Map<String, String>> messages, {
    int maxTokens = defaultMaxTokens,
    Duration? timeout,
  }) async {
    if (_apiKey.isEmpty) return null;
    final budget = timeout ?? _envTimeout;
    final client = HttpClient()..connectionTimeout = budget;
    try {
      return await _post(client, messages, maxTokens).timeout(budget);
    } catch (_) {
      return null;
    } finally {
      client.close(force: true);
    }
  }

  Duration get _envTimeout {
    final secs = int.tryParse(_env['ORCH_AGENT_TIMEOUT_SEC'] ?? '');
    return Duration(
        seconds: (secs == null || secs <= 0) ? defaultTimeoutSec : secs);
  }

  Future<String?> _post(
    HttpClient client,
    List<Map<String, String>> messages,
    int maxTokens,
  ) async {
    final turns = messages
        .where((m) => (m['content'] ?? '').trim().isNotEmpty)
        .toList();
    if (turns.isEmpty) return null;

    final url = '${baseUrl.replaceAll(RegExp(r'/+$'), '')}/chat/completions';
    final req = await client.postUrl(Uri.parse(url));
    req.headers
      ..set('Authorization', 'Bearer $_apiKey')
      ..set('Accept', 'application/json')
      ..contentType = ContentType.json;
    req.write(jsonEncode({
      'model': model,
      'max_tokens': maxTokens,
      'temperature': 0.55,
      'messages': turns,
      'stream': false,
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
      final choices = obj['choices'] as List? ?? const [];
      if (choices.isEmpty) return null;
      final message = (choices.first as Map)['message'] as Map?;
      final text = (message?['content'] as String?)?.trim();
      return (text == null || text.isEmpty) ? null : text;
    } catch (_) {
      return null;
    }
  }

  void _reportUsage(Object? usage) {
    final report = onUsage;
    if (report == null || usage is! Map) return;
    // OpenAI-compatible field names (prompt_tokens / completion_tokens).
    final inputTokens = _toInt(usage['prompt_tokens']);
    final outputTokens = _toInt(usage['completion_tokens']);
    final price = pricePerMTok[model];
    report({
      'type': 'result',
      if (price != null)
        'total_cost_usd':
            inputTokens * price.$1 / 1e6 + outputTokens * price.$2 / 1e6,
      'usage': {
        'input_tokens': inputTokens,
        'output_tokens': outputTokens,
      },
    });
  }

  static int _toInt(Object? v) => v is num ? v.toInt() : 0;
}
