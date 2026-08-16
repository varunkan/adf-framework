import 'dart:io';

import 'adf_brain.dart';
import 'claude_api_brain.dart';
import 'openai_compat_brain.dart';

/// Outcome of routing one task: which tier, provider and model should handle
/// it plus a one-line human-readable justification, so every decision is
/// loggable.
class RouteDecision {
  const RouteDecision({
    required this.tier,
    required this.model,
    required this.reason,
    this.provider = 'anthropic',
  });

  /// One of [ModelRouter.tiers].
  final String tier;
  final String model;
  final String reason;

  /// Which backend serves [model]: `local` (Ollama), `nvidia` (NIM, free) or
  /// `anthropic` (Claude, paid). Drives the brain choice and the chat source
  /// label.
  final String provider;

  Map<String, dynamic> toJson() =>
      {'tier': tier, 'model': model, 'provider': provider, 'reason': reason};

  @override
  String toString() => '$tier/$model — $reason';
}

/// Complexity-based model selection across the brain tiers.
///
/// Tiers, cheapest first: `local` (Ollama, $0) -> `fast` -> `balanced` ->
/// `deep` (Anthropic Messages API). The zero-model `instant` tier answers
/// state questions before the router is consulted, so it never appears in a
/// decision.
///
/// `ORCH_ROUTER` sets the posture: `auto` (default) routes by complexity,
/// `local-only` pins everything to Ollama, `cloud-only` lifts local picks
/// to `fast`. Cloud tiers require a cloud key (`NVIDIA_API_KEY` and/or
/// `ANTHROPIC_API_KEY`); without either the router silently degrades to
/// local-only — never an error.
///
/// Provider per cloud tier: when `NVIDIA_API_KEY` is set, the `fast` and
/// `balanced` tiers route to NVIDIA's free NIM models; `deep` prefers Claude
/// (`ANTHROPIC_API_KEY`) for top quality and falls back to NVIDIA's strongest
/// model when no Anthropic key exists. Override per tier with
/// `ORCH_PROVIDER_FAST|BALANCED|DEEP=nvidia|anthropic`.
class ModelRouter {
  ModelRouter({
    Map<String, String>? env,
    OllamaBrain? ollama,
    String? claudeBaseUrl,
    void Function(Map<String, dynamic> event)? onUsage,
  })  : _env = env ?? Platform.environment,
        _claudeBaseUrl = claudeBaseUrl,
        _onUsage = onUsage {
    _ollama = ollama ?? OllamaBrain(env: _env);
  }

  /// Cheapest -> most capable; [escalate] walks this list left to right.
  static const tiers = ['local', 'fast', 'balanced', 'deep'];

  /// Current Anthropic model IDs per tier (2026-06); override with
  /// `ORCH_MODEL_FAST` / `ORCH_MODEL_BALANCED` / `ORCH_MODEL_DEEP`.
  static const defaultModels = {
    'fast': 'claude-haiku-4-5',
    'balanced': 'claude-sonnet-4-6',
    'deep': 'claude-opus-4-8',
  };

  /// Free NVIDIA NIM model IDs per tier (build.nvidia.com, OpenAI-compatible);
  /// override with `ORCH_NVIDIA_MODEL_FAST|BALANCED|DEEP`. Verified available
  /// 2026-06 — NVIDIA retires models periodically, so a tier that 410s should
  /// be repointed here (or via the env override) at the next refresh.
  static const nvidiaModels = {
    'fast': 'meta/llama-3.3-70b-instruct',
    'balanced': 'nvidia/llama-3.3-nemotron-super-49b-v1.5',
    'deep': 'qwen/qwen3.5-397b-a17b',
  };

  /// Phrases with which the user explicitly asks for more horsepower.
  static final _escalationWords = RegExp(
    r'\b(think hard(er)?|think deeply|be thorough|carefully|escalate'
    r'|use opus|deep dive|architecture|architectural)\b',
    caseSensitive: false,
  );

  final Map<String, String> _env;
  final String? _claudeBaseUrl;
  final void Function(Map<String, dynamic> event)? _onUsage;
  late final OllamaBrain _ollama;
  final _deterministic = DeterministicBrain();

  /// One cloud brain per `provider:model` key, shared across decisions and
  /// tiers (only for usage-free lookups; per-call metering builds fresh).
  final _cloudBrains = <String, AdfBrain>{};

  String get mode => _envOr('ORCH_ROUTER', 'auto');

  String get _nvidiaKey =>
      (_env['NVIDIA_API_KEY'] ?? _env['ORCH_NVIDIA_API_KEY'] ?? '').trim();

  bool get hasNvidiaKey => _nvidiaKey.isNotEmpty;

  bool get hasAnthropicKey =>
      (_env['ANTHROPIC_API_KEY'] ?? '').trim().isNotEmpty;

  /// True when any cloud tier can be reached — Claude or free NVIDIA.
  bool get hasApiKey => hasAnthropicKey || hasNvidiaKey;

  String get nvidiaBaseUrl =>
      _envOr('ORCH_NVIDIA_BASE_URL', OpenAiCompatBrain.nvidiaBaseUrl);

  /// Which backend serves a cloud [tier]: `nvidia` (free) or `anthropic`
  /// (paid). Free NVIDIA wins `fast`/`balanced`; `deep` prefers Claude for
  /// quality. `ORCH_PROVIDER_<TIER>` forces a provider when its key exists.
  String providerForTier(String tier) {
    final override =
        (_env['ORCH_PROVIDER_${tier.toUpperCase()}'] ?? '').trim().toLowerCase();
    if (override == 'nvidia' && hasNvidiaKey) return 'nvidia';
    if (override == 'anthropic' && hasAnthropicKey) return 'anthropic';
    switch (tier) {
      case 'deep':
        if (hasAnthropicKey) return 'anthropic';
        return hasNvidiaKey ? 'nvidia' : 'anthropic';
      default: // fast, balanced — prefer the free tier
        return hasNvidiaKey ? 'nvidia' : 'anthropic';
    }
  }

  /// Picks a tier for [task] of [kind] (`chat`|`artifact`|`review`|`plan`|
  /// `implement`). [phase] is recorded in the reason for traceability.
  RouteDecision route({required String task, required String kind, int? phase}) {
    final (score, signals) = _complexity(task, kind);
    var tier = _tierForScore(score);
    final notes = <String>[
      ...signals,
      if (phase != null) 'phase=$phase',
      'score=$score -> $tier',
    ];

    switch (mode) {
      case 'local-only':
        if (tier != 'local') notes.add('ORCH_ROUTER=local-only pins local');
        tier = 'local';
      case 'cloud-only':
        if (!hasApiKey) {
          tier = 'local';
          notes.add(
              'cloud-only without ANTHROPIC_API_KEY — degraded to local');
        } else if (tier == 'local') {
          tier = 'fast';
          notes.add('ORCH_ROUTER=cloud-only lifts local to fast');
        }
      default: // auto
        if (tier != 'local' && !hasApiKey) {
          notes.add('no ANTHROPIC_API_KEY — degraded to local');
          tier = 'local';
        }
    }

    return RouteDecision(
      tier: tier,
      model: modelForTier(tier),
      provider: tier == 'local' ? 'local' : providerForTier(tier),
      reason: notes.join(', '),
    );
  }

  /// The next-higher tier for the same workload, or null when [decision] is
  /// already at `deep`, when `ORCH_ROUTER=local-only` pins the run, or when
  /// every higher tier bills the cloud and `ANTHROPIC_API_KEY` is missing.
  RouteDecision? escalate(RouteDecision decision) {
    final idx = tiers.indexOf(decision.tier);
    if (idx < 0 || idx + 1 >= tiers.length) return null;
    if (mode == 'local-only') return null;
    if (!hasApiKey) return null;
    final next = tiers[idx + 1];
    return RouteDecision(
      tier: next,
      model: modelForTier(next),
      provider: next == 'local' ? 'local' : providerForTier(next),
      reason: 'escalated from ${decision.tier}',
    );
  }

  /// The brain that executes [decision]. With no [onUsage] override the
  /// instance is reused (one OllamaBrain for `local`, one cloud brain per
  /// `provider:model`); pass [onUsage] to bind a fresh brain to a per-call
  /// usage callback (the chat path threads the feature id this way).
  AdfBrain brainFor(
    RouteDecision decision, {
    void Function(Map<String, dynamic> event)? onUsage,
  }) {
    if (onUsage == null) return brainForTier(decision.tier);
    return _buildBrain(decision.tier, onUsage);
  }

  /// Tier -> brain without a full decision (used by `ORCH_BRAIN=claude-*`
  /// pins). Unknown tiers fall back to the deterministic brain so callers
  /// always get a working [AdfBrain].
  AdfBrain brainForTier(String tier) {
    switch (tier) {
      case 'local':
        return _ollama;
      case 'fast' || 'balanced' || 'deep':
        return _cloudBrains.putIfAbsent(
            '${providerForTier(tier)}:${modelForTier(tier)}',
            () => _buildBrain(tier, _onUsage));
      default:
        return _deterministic;
    }
  }

  /// Constructs the cloud brain for [tier] bound to [onUsage]: a free
  /// OpenAI-compatible NVIDIA brain or a paid ClaudeApiBrain, per provider.
  AdfBrain _buildBrain(
    String tier,
    void Function(Map<String, dynamic> event)? onUsage,
  ) {
    final model = modelForTier(tier);
    if (providerForTier(tier) == 'nvidia') {
      return OpenAiCompatBrain(
        model: model,
        baseUrl: nvidiaBaseUrl,
        apiKey: _nvidiaKey,
        providerLabel: 'nvidia',
        billsTokens: false,
        env: _env,
        onUsage: onUsage,
      );
    }
    return ClaudeApiBrain(
      model: model,
      baseUrl: _claudeBaseUrl,
      env: _env,
      onUsage: onUsage,
    );
  }

  /// Model id serving [tier], after env overrides. A generic
  /// `ORCH_MODEL_<TIER>` override wins for any provider; otherwise the
  /// provider's default applies (`ORCH_NVIDIA_MODEL_<TIER>` for NVIDIA).
  String modelForTier(String tier) {
    final fallback = defaultModels[tier];
    if (fallback == null) return _ollama.model; // local (and unknown) tiers
    final generic = (_env['ORCH_MODEL_${tier.toUpperCase()}'] ?? '').trim();
    if (generic.isNotEmpty) return generic;
    if (providerForTier(tier) == 'nvidia') {
      return _envOr(
          'ORCH_NVIDIA_MODEL_${tier.toUpperCase()}', nvidiaModels[tier] ?? fallback);
    }
    return fallback;
  }

  (int, List<String>) _complexity(String task, String kind) {
    final signals = <String>['kind=$kind'];
    var score = switch (kind) {
      // Implementation and architecture work leans deep.
      'implement' => 4,
      // Reviews and planning lean balanced.
      'review' || 'plan' => 2,
      // Chat and artifact prose lean local/fast.
      'chat' || 'artifact' => 0,
      _ => 1,
    };
    if (task.length > 2000) {
      score += 2;
      signals.add('long task (${task.length} chars)');
    } else if (task.length > 600) {
      score += 1;
      signals.add('medium task (${task.length} chars)');
    }
    if (task.contains('```')) {
      score += 1;
      signals.add('code block');
    }
    if (_escalationWords.hasMatch(task)) {
      score += 2;
      signals.add('escalation words');
    }
    return (score, signals);
  }

  String _tierForScore(int score) {
    if (score >= 4) return 'deep';
    if (score >= 2) return 'balanced';
    if (score >= 1) return 'fast';
    return 'local';
  }

  String _envOr(String key, String fallback) {
    final raw = _env[key]?.trim();
    return (raw == null || raw.isEmpty) ? fallback : raw;
  }
}
