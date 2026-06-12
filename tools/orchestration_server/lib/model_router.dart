import 'dart:io';

import 'adf_brain.dart';
import 'claude_api_brain.dart';

/// Outcome of routing one task: which tier and model should handle it plus
/// a one-line human-readable justification, so every decision is loggable.
class RouteDecision {
  const RouteDecision({
    required this.tier,
    required this.model,
    required this.reason,
  });

  /// One of [ModelRouter.tiers].
  final String tier;
  final String model;
  final String reason;

  Map<String, dynamic> toJson() =>
      {'tier': tier, 'model': model, 'reason': reason};

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
/// to `fast`. Cloud tiers require `ANTHROPIC_API_KEY`; without it the
/// router silently degrades to local-only — never an error.
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

  /// Current cloud model IDs per tier (2026-06); override with
  /// `ORCH_MODEL_FAST` / `ORCH_MODEL_BALANCED` / `ORCH_MODEL_DEEP`.
  static const defaultModels = {
    'fast': 'claude-haiku-4-5',
    'balanced': 'claude-sonnet-4-6',
    'deep': 'claude-opus-4-8',
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

  /// One ClaudeApiBrain per model id, shared across decisions and tiers.
  final _claudeBrains = <String, ClaudeApiBrain>{};

  String get mode => _envOr('ORCH_ROUTER', 'auto');

  bool get hasApiKey => (_env['ANTHROPIC_API_KEY'] ?? '').trim().isNotEmpty;

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
      reason: 'escalated from ${decision.tier}',
    );
  }

  /// The brain that executes [decision]. Instances are reused — one
  /// OllamaBrain for `local`, one ClaudeApiBrain per cloud model.
  AdfBrain brainFor(RouteDecision decision) => brainForTier(decision.tier);

  /// Tier -> brain without a full decision (used by `ORCH_BRAIN=claude-*`
  /// pins). Unknown tiers fall back to the deterministic brain so callers
  /// always get a working [AdfBrain].
  AdfBrain brainForTier(String tier) {
    switch (tier) {
      case 'local':
        return _ollama;
      case 'fast' || 'balanced' || 'deep':
        final model = modelForTier(tier);
        return _claudeBrains.putIfAbsent(
          model,
          () => ClaudeApiBrain(
            model: model,
            baseUrl: _claudeBaseUrl,
            env: _env,
            onUsage: _onUsage,
          ),
        );
      default:
        return _deterministic;
    }
  }

  /// Model id serving [tier], after env overrides.
  String modelForTier(String tier) {
    final fallback = defaultModels[tier];
    if (fallback == null) return _ollama.model; // local (and unknown) tiers
    return _envOr('ORCH_MODEL_${tier.toUpperCase()}', fallback);
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
