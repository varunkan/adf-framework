import 'dart:convert';
import 'dart:io';

import 'adf_brain.dart';
import 'agent_chat_runner.dart';
import 'conversation_builder.dart';
import 'feature_store.dart';
import 'pipeline_planner.dart';

/// How much of the chat pipeline [process] runs.
enum ChatProcessMode {
  /// HTTP LLM → optional static context → fallback (no cursor-agent wait).
  httpOnly,
  /// Full pipeline including cursor-agent (can take minutes).
  full,
  /// Skip cursor/LLM — state-based answers only (fast fallback).
  stateOnly,
}

/// LLM interprets dashboard chat and produces orchestrator actions + agent prompts.
class OrchestratorChatProcessor {
  OrchestratorChatProcessor(
    this.store, {
    PipelinePlanner? planner,
    AgentChatRunner? agentChat,
    OllamaBrain? ollama,
    Object? router,
    void Function(String featureId, Map<String, dynamic> event)? onUsage,
    Map<String, String>? env,
    bool forceStaticContext = false,
  })  : _planner = planner,
        _agentChat = agentChat ?? AgentChatRunner(repoRoot: store.repoRoot),
        _ollama = ollama ?? OllamaBrain(env: env),
        _router = router,
        _onUsage = onUsage,
        _env = env ?? Platform.environment,
        _forceStaticContext = forceStaticContext;

  final FeatureStore store;
  final PipelinePlanner? _planner;
  final AgentChatRunner _agentChat;
  final OllamaBrain _ollama;

  /// Loose-coupled model router (concrete type lives in model_router.dart and
  /// is injected to avoid a hard dependency). Consulted in auto mode after
  /// the instant tier misses. Expected shape:
  /// `route(String task, {String kind, int? phase})` returning a
  /// `{tier, model, reason}` decision (map or RouteDecision-shaped object),
  /// and `brainFor(decision, {void Function(Map<String, dynamic>)? onUsage})`
  /// returning a Claude brain exposing `complete({system, user})`.
  final Object? _router;

  /// Receives CostMeter-compatible `{"type":"result",...}` usage events from
  /// router-selected Claude calls, keyed by feature id; the server wires this
  /// to its CostMeter instance.
  final void Function(String featureId, Map<String, dynamic> event)? _onUsage;
  final Map<String, String> _env;
  final bool _forceStaticContext;

  static const _defaultModel = 'gpt-4o-mini';

  String? get llmApiKey => _llmApiKey();

  /// `ORCH_CHAT_LLM`: `auto` (default — Ollama when reachable, else the
  /// cursor-agent path) | `ollama` | `cursor` (never touch Ollama).
  String get chatLlmMode {
    final v = (_env['ORCH_CHAT_LLM'] ?? 'auto').trim().toLowerCase();
    return (v == 'ollama' || v == 'cursor') ? v : 'auto';
  }

  /// Cached <=500ms reachability probe — safe to call once per message.
  Future<bool> ollamaChatReady() async {
    if (chatLlmMode == 'cursor') return false;
    return _ollama.availableCached();
  }

  /// Loads the local model into memory so the first user question doesn't
  /// pay the ~3s cold start. Fire-and-forget at server boot.
  Future<void> warmOllama() async {
    if (!await ollamaChatReady()) return;
    await _ollama.chat(
      [
        {'role': 'user', 'content': 'ok'},
      ],
      maxTokens: 1,
      timeout: const Duration(seconds: 90),
    );
  }

  /// Which LLM free-form chat will use right now: `llm` (cloud API),
  /// `ollama:<model>`, `cursor_agent`, or `none`.
  Future<String> describeChatLlm() async {
    final apiKey = _llmApiKey();
    if (apiKey != null && !preferCursorCli) return 'llm';
    if (await ollamaChatReady()) return _ollama.name;
    if (await cursorChatReady()) return 'cursor_agent';
    if (apiKey != null) return 'llm';
    return 'none';
  }

  /// When true, dashboard chat uses cursor-agent before HTTP LLM (Groq/OpenAI).
  bool get preferCursorCli {
    final v = _env['ORCH_CHAT_PREFER_CURSOR'];
    if (v == '0' || v == 'false') return false;
    if (v == '1' || v == 'true') return true;
    // Default: prefer Cursor CLI when no cloud LLM key is configured.
    return _llmApiKey() == null;
  }

  Future<bool> cursorChatReady() => _shouldTryCursorChat();

  /// True only when chat genuinely routes to cursor-agent BEFORE the local /
  /// HTTP models — mirrors the `cursorFirst` decision in [process]. Unlike
  /// [preferCursorCli] (which defaults true whenever no cloud key is set, for
  /// the API-key fallback ordering), this reflects what actually happens, so
  /// `/health` does not report a cursor preference when chat is pinned to
  /// Ollama or cursor chat is disabled.
  bool get cursorIsPreferred =>
      chatLlmMode == 'cursor' ||
      _env['ORCH_CHAT_PREFER_CURSOR'] == '1' ||
      _env['ORCH_CHAT_PREFER_CURSOR'] == 'true';

  bool get staticContextEnabled =>
      _forceStaticContext ||
      _env['ORCH_CHAT_STATIC_CONTEXT'] == '1' ||
      _env['ORCH_CHAT_STATIC_CONTEXT'] == 'true';

  Future<OrchestratorChatResult> process(
    String featureId,
    String userMessage, {
    ChatProcessMode mode = ChatProcessMode.full,
    void Function(String partialText)? onPartial,
  }) async {
    final sw = Stopwatch()..start();
    final trimmed = userMessage.trim();
    if (trimmed.isEmpty) {
      throw ArgumentError('empty message');
    }
    if (trimmed.startsWith('@orch-orchestrator')) {
      return _stamped(
        OrchestratorChatResult(
          assistantReply:
              'Running orchestrator command: ${trimmed.split('\n').first}',
          orchestratorCommand: trimmed.split('\n').first,
          agentPrompt: trimmed,
          action: OrchestratorAction.execute,
          source: 'direct',
        ),
        sw,
      );
    }

    final ctx = await _buildContext(featureId);

    // Forced static context keeps its richer link answers ahead of the
    // instant tier; both are zero-model millisecond paths.
    if (mode != ChatProcessMode.stateOnly && staticContextEnabled) {
      final contextual = _tryContextualAnswer(ctx, trimmed);
      if (contextual != null) return _stamped(contextual, sw);
    }

    // Instant zero-model tier runs first in every mode: state and
    // describe-intent questions answer in milliseconds from disk and never
    // hit the 'Thinking…' placeholder path.
    final instant = _answerFromFeatureState(ctx, trimmed);
    if (instant != null) return _stamped(instant, sw);

    if (mode == ChatProcessMode.stateOnly) {
      return _stamped(_fallback(ctx, trimmed), sw);
    }

    final contextBlock = _formatContextBlock(ctx);
    final history = _filterChatHistory(
      ConversationBuilder(store).buildChatView(featureId, limit: 12),
    );

    final useCursor =
        mode == ChatProcessMode.full && await _shouldTryCursorChat();
    final cursorFirst = chatLlmMode == 'cursor' ||
        _env['ORCH_CHAT_PREFER_CURSOR'] == '1' ||
        _env['ORCH_CHAT_PREFER_CURSOR'] == 'true';

    // ORCH_CHAT_LLM=cursor (or explicit prefer-cursor) keeps the legacy
    // cursor-first ordering; auto order is API LLM -> Ollama -> cursor.
    if (cursorFirst && useCursor) {
      final agentReply = await _agentChat.converse(
        featureId: featureId,
        contextBlock: contextBlock,
        userMessage: trimmed,
        recentMessages: history,
        onPartial: onPartial,
      );
      if (agentReply != null && agentReply.reply.trim().isNotEmpty) {
        return _stamped(_fromAgentChat(ctx, trimmed, agentReply), sw);
      }
    }

    // Model router (auto mode only): after the instant tier misses, the
    // router scores complexity — simple stays on the free local tier, hard
    // goes to the right Claude tier. ORCH_CHAT_LLM=ollama|cursor bypasses the
    // router entirely, and any router/brain failure returns null so the
    // existing ollama -> cursor-agent -> fallback chain below takes over.
    if (chatLlmMode == 'auto' && _router != null) {
      final routed = await _callRoutedModel(ctx, trimmed, history);
      if (routed != null) return _stamped(routed, sw);
    }

    final apiKey = _llmApiKey();
    if (apiKey != null && (!preferCursorCli || cursorFirst)) {
      try {
        return _stamped(await _callHttpLlm(ctx, trimmed, apiKey, history), sw);
      } catch (_) {}
    }

    // Local Ollama answers free-form chat at $0 before any cursor-agent
    // fallback. ollamaChatReady() is false when ORCH_CHAT_LLM=cursor.
    if (await ollamaChatReady()) {
      final viaOllama = await _callOllama(ctx, trimmed, history);
      if (viaOllama != null) return _stamped(viaOllama, sw);
    }

    if (!cursorFirst && useCursor) {
      final agentReply = await _agentChat.converse(
        featureId: featureId,
        contextBlock: contextBlock,
        userMessage: trimmed,
        recentMessages: history,
        onPartial: onPartial,
      );
      if (agentReply != null && agentReply.reply.trim().isNotEmpty) {
        return _stamped(_fromAgentChat(ctx, trimmed, agentReply), sw);
      }
    }

    return _stamped(
      _fallback(
        ctx,
        trimmed,
        note:
            'Could not reach a chat model. Start Ollama (ORCH_OLLAMA_HOST), run cursor-agent login, or set ORCH_LLM_API_KEY / GROQ_API_KEY on the API server.',
      ),
      sw,
    );
  }

  /// Records wall-clock time from question received to answer ready.
  OrchestratorChatResult _stamped(OrchestratorChatResult r, Stopwatch sw) {
    sw.stop();
    r.latencyMs ??= sw.elapsedMilliseconds;
    return r;
  }

  Future<bool> _shouldTryCursorChat() async {
    if (_env['ORCH_CHAT_USE_CURSOR'] == '0' ||
        _env['ORCH_CHAT_USE_CURSOR'] == 'false') {
      return false;
    }
    final health = await _agentChat.health.probe();
    return health['ready'] == true;
  }

  /// Free-form chat through the local Ollama model. The reply carries an
  /// `[ACTION:...]` tag (small models follow it more reliably than JSON);
  /// missing tags degrade to answer-only / resume heuristics.
  Future<OrchestratorChatResult?> _callOllama(
    OrchestratorChatContext ctx,
    String userMessage,
    List<Map<String, dynamic>> history,
  ) async {
    // Prefill time on a local 4B model is linear in prompt size: keep the
    // last 6 turns, each capped, so answers start in well under a second.
    final messages = <Map<String, String>>[
      {'role': 'system', 'content': _chatSystemPrompt(ctx)},
    ];
    final recent = history.length > 6
        ? history.sublist(history.length - 6)
        : history;
    for (final m in recent) {
      final role = m['role'] as String?;
      var text = (m['text'] as String? ?? '').trim();
      if (text.isEmpty || (role != 'user' && role != 'assistant')) continue;
      if (text.length > 700) text = '${text.substring(0, 700)}…';
      messages.add({'role': role!, 'content': text});
    }
    messages.add({'role': 'user', 'content': userMessage});

    final raw = await _ollama.chat(messages, maxTokens: 256, think: false);
    if (raw == null || raw.trim().isEmpty) return null;
    return _resultFromActionTaggedReply(ctx, userMessage, raw, _ollama.name);
  }

  /// Parses a model reply carrying the trailing `[ACTION:...]` tag — shared
  /// by the local Ollama path and the router-selected Claude path. Models
  /// drift on tag formatting ("[ ACTION:resume ]"), so whitespace anywhere
  /// inside the brackets is tolerated; missing tags degrade to answer-only /
  /// resume heuristics.
  OrchestratorChatResult? _resultFromActionTaggedReply(
    OrchestratorChatContext ctx,
    String userMessage,
    String raw,
    String source,
  ) {
    var text = raw.trim();
    var action = _looksLikeWorkRequest(userMessage.toLowerCase())
        ? OrchestratorAction.resume
        : OrchestratorAction.answerOnly;
    final tag = RegExp(r'\[\s*ACTION:\s*(\w+)\s*\]', caseSensitive: false)
        .firstMatch(text);
    if (tag != null) {
      action = switch (tag.group(1)!.toLowerCase()) {
        'sync' => OrchestratorAction.sync,
        'resume' => OrchestratorAction.resume,
        'clarify' => OrchestratorAction.clarify,
        _ => OrchestratorAction.answerOnly,
      };
      text = text.replaceRange(tag.start, tag.end, '').trim();
    }
    if (text.isEmpty) return null;
    final cmd = action == OrchestratorAction.sync
        ? '@orch-orchestrator sync ${ctx.featureId}'
        : '@orch-orchestrator resume ${ctx.featureId}';
    final agentPrompt = action == OrchestratorAction.answerOnly
        ? ''
        : _buildAgentPrompt(
            ctx,
            cmd,
            'Execute per user chat request and ADF routing.',
            userMessage,
          );
    return OrchestratorChatResult(
      assistantReply: text,
      orchestratorCommand: cmd,
      agentPrompt: agentPrompt,
      action: action,
      source: source,
    );
  }

  /// Whether router cloud tiers may be attempted at all. Without
  /// ANTHROPIC_API_KEY the router degrades to local-only — never an error.
  bool get _anthropicConfigured =>
      (_env['ANTHROPIC_API_KEY'] ?? '').trim().isNotEmpty;

  /// ORCH_AGENT_TIMEOUT_SEC caps every brain LLM task (default 30s). On
  /// timeout the routed path returns null and the local chain takes over.
  Duration get _agentTimeout => Duration(
      seconds: int.tryParse(_env['ORCH_AGENT_TIMEOUT_SEC'] ?? '') ?? 30);

  /// Consults the injected model router and answers through the tier it
  /// picks: 'local' reuses the existing $0 [_callOllama] path unchanged;
  /// 'fast'/'balanced'/'deep' call the Claude brain the router supplies
  /// (only when ANTHROPIC_API_KEY is set). Returns null whenever the routed
  /// path cannot answer so the caller falls through to the legacy chain.
  Future<OrchestratorChatResult?> _callRoutedModel(
    OrchestratorChatContext ctx,
    String userMessage,
    List<Map<String, dynamic>> history,
  ) async {
    Object? decision;
    try {
      final raw = (_router as dynamic)
          .route(userMessage, kind: 'chat', phase: ctx.phase);
      decision = (raw is Future ? await raw : raw) as Object?;
    } catch (_) {
      return null;
    }
    final tier = _decisionField(decision, 'tier');
    if (tier == 'local') {
      if (!await ollamaChatReady()) return null;
      return _callOllama(ctx, userMessage, history);
    }
    if (tier != 'fast' && tier != 'balanced' && tier != 'deep') return null;
    if (!_anthropicConfigured) return null;
    final model = _decisionField(decision, 'model');
    if (model == null || model.isEmpty) return null;
    return _callClaude(ctx, userMessage, history, decision, model);
  }

  /// Reads `tier` / `model` / `reason` off a router decision regardless of
  /// whether it arrives as a map or a RouteDecision-shaped object.
  String? _decisionField(Object? decision, String key) {
    if (decision is Map) return decision[key]?.toString();
    try {
      final d = decision as dynamic;
      final Object? v = switch (key) {
        'tier' => d.tier,
        'model' => d.model,
        'reason' => d.reason,
        _ => null,
      };
      return v?.toString();
    } catch (_) {
      return null;
    }
  }

  /// Free-form chat through the Claude brain the router supplies. Reuses the
  /// `[ACTION:...]` reply protocol so action parsing matches the local path,
  /// stamps the source as `claude:<model>`, and threads [_onUsage] into the
  /// brain so the server meters spend per feature.
  Future<OrchestratorChatResult?> _callClaude(
    OrchestratorChatContext ctx,
    String userMessage,
    List<Map<String, dynamic>> history,
    Object? decision,
    String model,
  ) async {
    final onUsage = _onUsage;
    final usageCb = onUsage == null
        ? null
        : (Map<String, dynamic> event) => onUsage(ctx.featureId, event);
    dynamic brain;
    try {
      brain = (_router as dynamic).brainFor(decision, onUsage: usageCb);
    } catch (_) {
      // Routers that attach usage reporting on the brain instead of the
      // factory call still work — set it best-effort after construction.
      try {
        brain = (_router as dynamic).brainFor(decision);
        if (usageCb != null) {
          try {
            (brain as dynamic).onUsage = usageCb;
          } catch (_) {}
        }
      } catch (_) {
        return null;
      }
    }
    if (brain == null) return null;
    String? raw;
    try {
      final out = (brain as dynamic).complete(
        system: _chatSystemPrompt(ctx),
        user: _foldHistory(history, userMessage),
      );
      raw = (out is Future ? await out.timeout(_agentTimeout) : out) as String?;
    } catch (_) {
      return null;
    }
    if (raw == null || raw.trim().isEmpty) return null;
    return _resultFromActionTaggedReply(ctx, userMessage, raw, 'claude:$model');
  }

  /// Folds recent turns into one user block for single-shot
  /// `complete({system, user})` brains (the Claude brain takes a system
  /// prompt plus one user message, not a message list). Mirrors the Ollama
  /// path's caps: last 6 turns, each trimmed to 700 chars.
  String _foldHistory(
    List<Map<String, dynamic>> history,
    String userMessage,
  ) {
    final recent =
        history.length > 6 ? history.sublist(history.length - 6) : history;
    final buf = StringBuffer();
    for (final m in recent) {
      final role = m['role'] as String?;
      var text = (m['text'] as String? ?? '').trim();
      if (text.isEmpty || (role != 'user' && role != 'assistant')) continue;
      if (text.length > 700) text = '${text.substring(0, 700)}…';
      buf.writeln('${role == 'user' ? 'User' : 'Assistant'}: $text');
    }
    if (buf.isEmpty) return userMessage;
    return 'Recent conversation:\n$buf\nUser: $userMessage';
  }

  /// System prompt for the `[ACTION:...]` tagged-reply protocol, shared by
  /// the local Ollama path and the router-selected Claude path.
  String _chatSystemPrompt(OrchestratorChatContext ctx) {
    return 'You are the ADF v3 orchestrator assistant for feature '
        '"${ctx.featureId}".\n'
        '${_formatContextBlock(ctx)}\n\n'
        'Answer the user naturally in 2-5 sentences using the context above. '
        'Use markdown if helpful.\n'
        'End with exactly one line: [ACTION:answer_only] for questions, '
        '[ACTION:sync] when the user approves moving forward, '
        '[ACTION:resume] when they want work continued, or '
        '[ACTION:clarify] when they add requirements.';
  }

  String _formatContextBlock(OrchestratorChatContext ctx) {
    final step = ctx.currentStepLabel != null
        ? 'Pipeline step: ${ctx.currentStepLabel}\n'
        : '';
    return 'Phase: ${ctx.phase} | Status: ${ctx.status} | Awaiting: ${ctx.awaitingUser}\n'
        'Spec: ${ctx.specDir}/\n'
        'API: ${ctx.apiFeatureUrl}\n'
        'Dashboard: ${ctx.dashboardUrl}\n'
        'Orchestration: ${ctx.orchestrationRel}\n'
        '$step\n'
        'Requirement:\n'
        '${ctx.requirementSnippet.isEmpty ? "(see requirement.md)" : ctx.requirementSnippet}';
  }

  OrchestratorChatResult _fromAgentChat(
    OrchestratorChatContext ctx,
    String userMessage,
    AgentChatResponse agentReply,
  ) {
    final action = switch (agentReply.actionTag) {
      'sync' => OrchestratorAction.sync,
      'clarify' => OrchestratorAction.clarify,
      'answer_only' => OrchestratorAction.answerOnly,
      _ => OrchestratorAction.resume,
    };
    final cmd = action == OrchestratorAction.sync
        ? '@orch-orchestrator sync ${ctx.featureId}'
        : '@orch-orchestrator resume ${ctx.featureId}';
    final agentPrompt = action == OrchestratorAction.answerOnly
        ? ''
        : _buildAgentPrompt(
            ctx,
            cmd,
            'Execute per user chat request and ADF routing.',
            userMessage,
          );
    return OrchestratorChatResult(
      assistantReply: agentReply.reply,
      orchestratorCommand: cmd,
      agentPrompt: agentPrompt,
      action: action,
      source: 'cursor_agent',
    );
  }

  String? _llmApiKey() {
    return _env['ORCH_LLM_API_KEY'] ??
        _env['OPENAI_API_KEY'] ??
        _env['GROQ_API_KEY'] ??
        _readDotEnvKey('ORCH_LLM_API_KEY') ??
        _readDotEnvKey('OPENAI_API_KEY') ??
        _readDotEnvKey('GROQ_API_KEY');
  }

  String? _readDotEnvKey(String key) {
    for (final path in [
      '${store.repoRoot}/.env.groq.local',
      '${store.repoRoot}/.env',
      '${store.repoRoot}/adf-framework/.env',
    ]) {
      final f = File(path);
      if (!f.existsSync()) continue;
      for (final line in f.readAsLinesSync()) {
        final trimmed = line.trim();
        if (trimmed.isEmpty || trimmed.startsWith('#')) continue;
        final eq = trimmed.indexOf('=');
        if (eq <= 0) continue;
        if (trimmed.substring(0, eq).trim() != key) continue;
        var value = trimmed.substring(eq + 1).trim();
        if ((value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))) {
          value = value.substring(1, value.length - 1);
        }
        if (value.isNotEmpty) return value;
      }
    }
    return null;
  }

  /// Gate-by-gate progress with a concrete next action — instant, zero tokens.
  OrchestratorChatResult _progressAnswer(
    OrchestratorChatContext ctx,
    String resolvedId,
  ) {

      final st = store.readState(resolvedId);
      final gates = st['gates'] as Map<String, dynamic>? ?? {};
      final work = store.inferWorkPhase(gates);
      final done = <String>[];
      final remaining = <String>[];
      FeatureStore.phaseGateMap.forEach((p, g) {
        final label = PipelinePlanner.phaseNames[p] ?? 'phase $p';
        (gates[g] == true ? done : remaining).add('$p · $label');
      });
      final hint = work <= 6
          ? 'Hit **Autopilot** (or `POST /features/$resolvedId/autopilot`) to '
              'complete phases ${work}–6 instantly at zero token cost.'
          : work == 7
              ? 'Next: **phase 7 implement** — write code against the red '
                  'tests, then phases 8–9 verify and review.'
              : 'Next: finish verification/review gates.';
      return OrchestratorChatResult(
        assistantReply: '**$resolvedId** progress\n\n'
            '- Done: ${done.isEmpty ? 'none yet' : done.join(', ')}\n'
            '- Remaining: ${remaining.isEmpty ? 'all gates passed' : remaining.join(', ')}\n\n'
            '$hint',
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'state',
      );
      }

  /// "What does this feature do?" answered purely from disk state —
  /// requirement text, spec.md EARS excerpt, phase/status, gates passed.
  /// No model call, no process spawn: milliseconds, zero tokens.
  OrchestratorChatResult _describeAnswer(
    OrchestratorChatContext ctx,
    String resolvedId,
  ) {
    final reqFile = File('${store.featurePath(resolvedId)}/requirement.md');
    var requirement =
        reqFile.existsSync() ? reqFile.readAsStringSync().trim() : '';
    if (requirement.length > 600) {
      requirement = '${requirement.substring(0, 600)}…';
    }

    final st = store.readState(resolvedId);
    final phase = store.effectivePhase(resolvedId, st);
    final status = st['status'] as String? ?? 'unknown';
    final gates = st['gates'] as Map<String, dynamic>? ?? {};
    final passed = gates.values.where((v) => v == true).length;
    final ears = _specEarsLines(resolvedId);

    final buf = StringBuffer('**$resolvedId** — what it does\n\n');
    buf.writeln(requirement.isEmpty
        ? '_No requirement recorded yet — describe the feature in chat or '
            'edit `requirement.md` to fill it in._'
        : requirement);
    if (ears.isNotEmpty) {
      buf
        ..writeln('\nSpec requirements (EARS, `specs/$resolvedId/spec.md`):')
        ..writeln(ears.map((l) => '- $l').join('\n'));
    }
    buf.writeln('\nCurrently on **phase $phase** (status: **$status**), '
        '$passed/${FeatureStore.phaseGateMap.length} gates passed.');
    return OrchestratorChatResult(
      assistantReply: buf.toString().trim(),
      orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
      agentPrompt: '',
      action: OrchestratorAction.answerOnly,
      source: 'state',
    );
  }

  /// First EARS `The system SHALL …` lines from spec.md, if generated.
  List<String> _specEarsLines(String id, {int max = 3}) {
    final spec = File('${store.repoRoot}/specs/$id/spec.md');
    if (!spec.existsSync()) return const [];
    final lines = <String>[];
    for (final line in spec.readAsLinesSync()) {
      final t = line.trim();
      if (t.toLowerCase().startsWith('the system shall')) {
        lines.add(t);
        if (lines.length >= max) break;
      }
    }
    return lines;
  }

  String _llmApiUrl() {
    return _env['ORCH_LLM_API_URL'] ??
        (_env['GROQ_API_KEY'] != null
            ? 'https://api.groq.com/openai/v1/chat/completions'
            : 'https://api.openai.com/v1/chat/completions');
  }

  String _llmModel() {
    return _env['ORCH_LLM_MODEL'] ??
        (_env['GROQ_API_KEY'] != null
            ? 'llama-3.3-70b-versatile'
            : _defaultModel);
  }

  int get _apiPort => int.tryParse(_env['ORCH_PORT'] ?? '3847') ?? 3847;

  int get _webPort => int.tryParse(_env['ORCH_WEB_PORT'] ?? '3848') ?? 3848;

  String get _apiBase => 'http://localhost:$_apiPort';

  String get _dashboardBase => 'http://localhost:$_webPort';

  List<Map<String, dynamic>> _filterChatHistory(
    List<Map<String, dynamic>> messages,
  ) {
    return messages.where((m) {
      final text = (m['text'] as String? ?? '').trim();
      if (text.isEmpty) return false;
      if (text.startsWith('Thinking')) return false;
      if (m['llm_source'] == 'pending') return false;
      return true;
    }).toList();
  }

  OrchestratorChatResult? _answerFromFeatureState(
    OrchestratorChatContext ctx,
    String userMessage,
  ) {
    final lower = userMessage.toLowerCase();
    if (_looksLikeWorkRequest(lower)) return null;
    if (!_isInformationalQuery(lower)) return null;
    final resolvedId = _resolveFeatureIdFromMessage(ctx.featureId, lower);

    // Describe-intent first: "what does this feature do" must answer from
    // disk before next-steps/status keywords get a chance to misroute it.
    if (_asksDescribe(lower)) {
      return _describeAnswer(ctx, resolvedId);
    }

    if (_asksNextSteps(lower) || _asksAutopilot(lower) || lower.contains('progress')) {
      return _progressAnswer(ctx, resolvedId);
    }

    if (_asksPhaseOrStatus(lower)) {
      final st = store.readState(resolvedId);
      final phase = store.effectivePhase(resolvedId, st);
      final status = st['status'] as String? ?? 'unknown';
      final awaiting = st['awaiting_user'] == true;
      final step = ctx.currentStepLabel;
      return OrchestratorChatResult(
        assistantReply:
            '**$resolvedId** is on **phase $phase** (status: **$status**)'
            '${awaiting ? ', waiting for your approval' : ''}.'
            '${step != null ? ' Current step: $step.' : ''}',
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'state',
      );
    }

    if (_asksForUrl(lower)) {
      return OrchestratorChatResult(
        assistantReply:
            'Open **$resolvedId** from the dashboard at ${ctx.dashboardUrl}. '
            'API JSON: $_apiBase/features/$resolvedId',
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'state',
      );
    }

    if (_asksArtifacts(lower)) {
      final specDir = '${store.repoRoot}/specs/$resolvedId';
      final existing = <String>[];
      for (final name in [
        'problem-statement.md',
        'spec.md',
        'plan.md',
        'tasks.md',
        'task-graph.yaml',
        'test-plan.md',
        'test-cases.md',
        'traceability-matrix.md',
      ]) {
        if (File('$specDir/$name').existsSync()) existing.add('`specs/$resolvedId/$name`');
      }
      return OrchestratorChatResult(
        assistantReply: existing.isEmpty
            ? 'No artifacts generated yet for **$resolvedId**. Hit **Autopilot** '
                'to generate spec, plan, tasks, and test cases instantly.'
            : 'Artifacts for **$resolvedId**:\n- ${existing.join('\n- ')}',
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'state',
      );
    }

    if (_asksHelp(lower)) {
      return OrchestratorChatResult(
        assistantReply:
            'I answer instantly about **status**, **progress**, **next steps**, '
            '**artifacts**, and **URLs** — zero tokens. Say **autopilot** to run '
            'phases 1–6 automatically, **sync** to approve, or describe a change '
            'to route it into the pipeline.',
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'state',
      );
    }
    return null;
  }

  Future<OrchestratorChatContext> _buildContext(String featureId) async {
    final state = store.readState(featureId);
    final phase = store.effectivePhase(featureId, state);
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    final awaiting = state['awaiting_user'] == true;
    final specDir =
        state['spec_feature_dir'] as String? ?? 'specs/$featureId';
    final reqFile = File('${store.featurePath(featureId)}/requirement.md');
    var reqSnippet = '';
    if (reqFile.existsSync()) {
      reqSnippet = reqFile.readAsStringSync();
      if (reqSnippet.length > 2000) {
        reqSnippet = '${reqSnippet.substring(0, 2000)}…';
      }
    }
    String? currentStep;
    if (_planner != null) {
      try {
        final plan = _planner.buildPlan(featureId);
        final stepId = plan['current_step_id'] as String?;
        final steps = (plan['phases'] as List<dynamic>?) ?? [];
        for (final ph in steps) {
          if (ph is! Map) continue;
          for (final s in (ph['steps'] as List<dynamic>?) ?? []) {
            if (s is Map && s['id'] == stepId) {
              currentStep = s['label'] as String? ?? stepId;
              break;
            }
          }
        }
      } catch (_) {}
    }
    return OrchestratorChatContext(
      featureId: featureId,
      phase: phase,
      status: state['status'] as String? ?? 'active',
      awaitingUser: awaiting,
      gates: gates,
      requirementSnippet: reqSnippet,
      currentStepLabel: currentStep,
      specDir: specDir,
      apiFeatureUrl: '$_apiBase/features/$featureId',
      dashboardUrl: _dashboardBase,
      orchestrationRel:
          store.paths.featureRel(featureId, ''),
    );
  }

  /// Answers URL / status / phase questions without LLM or agent run.
  OrchestratorChatResult? _tryContextualAnswer(
    OrchestratorChatContext ctx,
    String userMessage,
  ) {
    final lower = userMessage.toLowerCase();
    if (!_isInformationalQuery(lower)) return null;

    final resolvedId = _resolveFeatureIdFromMessage(ctx.featureId, lower);
    final links = _formatFeatureLinks(resolvedId, ctx);

    if (_asksForUrl(lower)) {
      return OrchestratorChatResult(
        assistantReply: links,
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'context',
      );
    }

    if (_asksNextSteps(lower) || _asksAutopilot(lower) || lower.contains('progress')) {
      return _progressAnswer(ctx, resolvedId);
    }

    if (_asksPhaseOrStatus(lower)) {
      final st = store.readState(resolvedId);
      final phase = store.effectivePhase(resolvedId, st);
      final status = st['status'] as String? ?? 'unknown';
      final awaiting = st['awaiting_user'] == true;
      return OrchestratorChatResult(
        assistantReply:
            '**$resolvedId** — phase **$phase**, status **$status**'
            '${awaiting ? ', awaiting your approval' : ''}.\n\n$links',
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'context',
      );
    }

    if (_asksHelp(lower)) {
      return OrchestratorChatResult(
        assistantReply: '''**ADF orchestrator help**

You are chatting about feature **${ctx.featureId}** (phase ${ctx.phase}).

- Ask **URLs**: "what is the URL for this feature?"
- Ask **status**: "what phase are we on?"
- **Approve**: "sync" or "approve" → runs `@orch-orchestrator sync`
- **Continue work**: describe changes → orchestrator updates requirement and runs agents
- **IDE**: `@orch-orchestrator resume ${ctx.featureId}` in Cursor

$links''',
        orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
        agentPrompt: '',
        action: OrchestratorAction.answerOnly,
        source: 'context',
      );
    }

    return null;
  }

  /// Work requests ("add OAuth login…") must reach the pipeline even when
  /// they mention spec/plan/task keywords.
  bool _looksLikeWorkRequest(String lower) {
    if (lower.contains('?')) return false;
    const verbs = [
      'add ', 'implement', 'create ', 'build ', 'fix ', 'change ',
      'update ', 'remove ', 'delete ', 'refactor', 'write ', 'make ',
      'rename ', 'integrate ',
    ];
    return verbs.any(lower.contains);
  }

  bool _isInformationalQuery(String lower) {
    return _asksDescribe(lower) ||
        _asksForUrl(lower) ||
        _asksPhaseOrStatus(lower) ||
        _asksHelp(lower) ||
        _asksNextSteps(lower) ||
        _asksArtifacts(lower) ||
        _asksAutopilot(lower);
  }

  /// Describe-intent: "what does this feature do", "what is this feature",
  /// "describe/explain/summarize this/the feature", "what am I building".
  bool _asksDescribe(String lower) {
    if (lower.contains('what does this feature do') ||
        lower.contains('what does the feature do') ||
        lower.contains('what does it do') ||
        lower.contains('what am i building')) {
      return true;
    }
    return RegExp(r"\bwhat('s| is)\s+(this|the)\s+feature\b").hasMatch(lower) ||
        RegExp(r'\b(describe|explain|summari[sz]e)\b.{0,40}\b(this|the)\s+feature\b')
            .hasMatch(lower);
  }

  bool _asksNextSteps(String lower) {
    return lower.contains('next') ||
        lower.contains("what's left") ||
        lower.contains('what is left') ||
        lower.contains('remaining') ||
        lower.contains('to do') ||
        lower.contains('todo');
  }

  bool _asksArtifacts(String lower) {
    return lower.contains('artifact') ||
        lower.contains('spec') ||
        lower.contains('plan') ||
        lower.contains('task') ||
        lower.contains('test case') ||
        lower.contains('files');
  }

  bool _asksAutopilot(String lower) {
    return lower.contains('autopilot') ||
        lower.contains('automatic') ||
        lower.contains('run all') ||
        lower.contains('do everything');
  }

  bool _asksForUrl(String lower) {
    return lower.contains('url') ||
        lower.contains('link') ||
        lower.contains('endpoint') ||
        lower.contains('address');
  }

  bool _asksPhaseOrStatus(String lower) {
    return lower.contains('phase') ||
        lower.contains('status') ||
        lower.contains('gate') ||
        lower.contains('progress') ||
        lower.contains('which step');
  }

  bool _asksHelp(String lower) {
    return lower.contains('help') || lower.contains('how do i');
  }

  String _resolveFeatureIdFromMessage(String currentId, String lower) {
    if (lower.contains('feature2') ||
        lower.contains('feature 2') ||
        lower.contains('feature-2')) {
      return store.featureExists('feature2') ? 'feature2' : currentId;
    }
    if (lower.contains('feature1') || lower.contains('feature 1')) {
      return store.featureExists('feature1') ? 'test1' : currentId;
    }
    final m = RegExp(r'feature\s*([a-z0-9][-a-z0-9]*)').firstMatch(lower);
    if (m != null) {
      final id = m.group(1)!;
      if (store.featureExists(id)) return id;
      if (id == '2' && store.featureExists('feature2')) return 'feature2';
    }
    return currentId;
  }

  String _formatFeatureLinks(String featureId, OrchestratorChatContext ctx) {
    final specDir = store.readState(featureId)['spec_feature_dir'] as String? ??
        'specs/$featureId';
    final orch =
        store.paths.featureRel(featureId, '').replaceAll(RegExp(r'/$'), '');
    return '''**$featureId** links:
- **API (JSON):** $_apiBase/features/$featureId
- **API conversation:** $_apiBase/features/$featureId/conversation
- **API pipeline:** $_apiBase/features/$featureId/pipeline
- **Dashboard:** $_dashboardBase — open this feature from the list (no deep-link route yet)
- **Spec folder:** `$specDir/`
- **Orchestration:** `$orch/`
- **Current chat context:** `${ctx.featureId}` phase ${ctx.phase}, status ${ctx.status}''';
  }

  Future<OrchestratorChatResult> _callHttpLlm(
    OrchestratorChatContext ctx,
    String userMessage,
    String apiKey,
    List<Map<String, dynamic>> history,
  ) async {
    final system = _systemPrompt(ctx);
    final messages = <Map<String, String>>[
      {'role': 'system', 'content': system},
    ];
    for (final m in history) {
      final role = m['role'] as String?;
      final text = (m['text'] as String? ?? '').trim();
      if (text.isEmpty || role == null) continue;
      if (role != 'user' && role != 'assistant') continue;
      messages.add({'role': role, 'content': text});
    }
    messages.add({'role': 'user', 'content': userMessage});

    final body = jsonEncode({
      'model': _llmModel(),
      'temperature': 0.55,
      'response_format': {'type': 'json_object'},
      'messages': messages,
    });

    final client = HttpClient();
    try {
      final uri = Uri.parse(_llmApiUrl());
      final req = await client.postUrl(uri);
      req.headers.set('Content-Type', 'application/json');
      req.headers.set('Authorization', 'Bearer $apiKey');
      req.write(body);
      final res = await req.close();
      final text = await res.transform(utf8.decoder).join();
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw StateError('LLM HTTP ${res.statusCode}: $text');
      }
      final decoded = jsonDecode(text) as Map<String, dynamic>;
      final choices = decoded['choices'] as List<dynamic>?;
      if (choices == null || choices.isEmpty) {
        throw StateError('LLM returned no choices');
      }
      final content = (choices.first as Map)['message']?['content'] as String?;
      if (content == null || content.trim().isEmpty) {
        throw StateError('LLM empty content');
      }
      return _parseLlmJson(ctx, content.trim(), userMessage);
    } finally {
      client.close(force: true);
    }
  }

  String _systemPrompt(OrchestratorChatContext ctx) {
    return '''You are the ADF v3 orchestrator assistant for feature "${ctx.featureId}".
Current phase: ${ctx.phase}. Status: ${ctx.status}. Awaiting user approval: ${ctx.awaitingUser}.
Gates: ${jsonEncode(ctx.gates)}.
${ctx.currentStepLabel != null ? 'Active pipeline step: ${ctx.currentStepLabel}' : ''}

Links for this feature:
${ctx.apiFeatureUrl}
Dashboard: ${ctx.dashboardUrl}
Spec: ${ctx.specDir}/

Requirement excerpt:
${ctx.requirementSnippet.isEmpty ? '(none yet)' : ctx.requirementSnippet}

Respond with ONLY valid JSON:
{
  "assistant_reply": "natural, varied reply like ChatGPT/Cursor chat (2-5 sentences). Answer the specific question; use links above only when relevant.",
  "action": "resume" | "sync" | "clarify" | "answer_only",
  "orchestrator_command": "@orch-orchestrator resume|sync ${ctx.featureId}",
  "agent_instructions": "detailed instructions for the coding agent (empty string if answer_only)"
}

Rules:
- action "answer_only" for questions (URL, phase, status, what is X) — do NOT start agent work.
- action "sync" when user approves or confirms moving forward after review.
- action "resume" when user wants work continued on current phase builders.
- action "clarify" when user adds requirements.
- orchestrator_command must start with @orch-orchestrator.''';
  }

  OrchestratorChatResult _parseLlmJson(
    OrchestratorChatContext ctx,
    String content,
    String userMessage,
  ) {
    Map<String, dynamic> obj;
    try {
      obj = jsonDecode(content) as Map<String, dynamic>;
    } catch (_) {
      final start = content.indexOf('{');
      final end = content.lastIndexOf('}');
      if (start < 0 || end <= start) rethrow;
      obj = jsonDecode(content.substring(start, end + 1)) as Map<String, dynamic>;
    }
    final actionStr = (obj['action'] as String? ?? 'resume').toLowerCase();
    final action = switch (actionStr) {
      'sync' => OrchestratorAction.sync,
      'clarify' => OrchestratorAction.clarify,
      'answer_only' => OrchestratorAction.answerOnly,
      _ => OrchestratorAction.resume,
    };
    var cmd = obj['orchestrator_command'] as String? ??
        '@orch-orchestrator resume ${ctx.featureId}';
    if (!cmd.contains('@orch-orchestrator')) {
      cmd = '@orch-orchestrator resume ${ctx.featureId}';
    }
    final instructions = obj['agent_instructions'] as String? ?? '';
    final agentPrompt = action == OrchestratorAction.answerOnly
        ? ''
        : _buildAgentPrompt(ctx, cmd, instructions, userMessage);
    return OrchestratorChatResult(
      assistantReply: obj['assistant_reply'] as String? ??
          'Understood — applying your request via the orchestrator.',
      orchestratorCommand: cmd,
      agentPrompt: agentPrompt,
      action: action,
      source: 'llm',
    );
  }

  OrchestratorChatResult _fallback(
    OrchestratorChatContext ctx,
    String userMessage, {
    String? note,
  }) {
    final lower = userMessage.toLowerCase();
    final looksLikeQuestion = lower.contains('?') ||
        lower.startsWith('what ') ||
        lower.startsWith('where ') ||
        lower.startsWith('how ') ||
        lower.startsWith('why ') ||
        lower.contains('what is') ||
        lower.contains('what are');
    OrchestratorAction action;
    String cmd;
    if (looksLikeQuestion &&
        !lower.contains('sync') &&
        !lower.contains('approve')) {
      action = OrchestratorAction.answerOnly;
      cmd = '@orch-orchestrator resume ${ctx.featureId}';
    } else if (lower.contains('sync') ||
        lower.contains('approve') ||
        lower.contains('looks good') ||
        (lower.contains('proceed') && !lower.contains('?'))) {
      action = OrchestratorAction.sync;
      cmd = '@orch-orchestrator sync ${ctx.featureId}';
    } else if (ctx.awaitingUser) {
      action = OrchestratorAction.clarify;
      cmd = '@orch-orchestrator resume ${ctx.featureId}';
    } else {
      action = OrchestratorAction.resume;
      cmd = '@orch-orchestrator resume ${ctx.featureId}';
    }

    final reply = StringBuffer();
    if (note != null) reply.writeln('$note\n');
    if (action == OrchestratorAction.answerOnly) {
      reply.writeln(
        'Quick answer from feature state: **${ctx.featureId}** is on phase '
        '${ctx.phase} (${ctx.status}). Ask about **progress**, **next steps**, '
        'or **artifacts** for instant detail — or set `GROQ_API_KEY` for '
        'free-form answers.',
      );
      if (_asksForUrl(lower)) {
        reply.writeln('\n${_formatFeatureLinks(ctx.featureId, ctx)}');
      }
    } else {
      reply.writeln(
        'Got it — I will route this to the orchestrator for phase ${ctx.phase}.',
      );
      if (_llmApiKey() == null) {
        reply.writeln(
          '\n_Tip: set `GROQ_API_KEY` on the API server for smarter replies._',
        );
      }
    }
    final agentPrompt = action == OrchestratorAction.answerOnly
        ? ''
        : _buildAgentPrompt(
            ctx,
            cmd,
            'Apply the client input below to requirement.md and current phase artifacts.',
            userMessage,
          );
    return OrchestratorChatResult(
      assistantReply: reply.toString().trim(),
      orchestratorCommand: cmd,
      agentPrompt: agentPrompt,
      action: action,
      source: 'fallback',
    );
  }

  String _buildAgentPrompt(
    OrchestratorChatContext ctx,
    String orchestratorCommand,
    String instructions,
    String userMessage,
  ) {
    final rel = store.paths.featureRel(ctx.featureId, 'requirement.md');
    return '''$orchestratorCommand

## Orchestrator — client message (phase ${ctx.phase})

$instructions

### Client input
$userMessage

### Required
1. Update `$rel` with clarifications.
2. Follow framework-routing.yaml for phase ${ctx.phase}.
3. Stop when awaiting user approval if gate requires it.''';
  }
}

class OrchestratorChatContext {
  OrchestratorChatContext({
    required this.featureId,
    required this.phase,
    required this.status,
    required this.awaitingUser,
    required this.gates,
    required this.requirementSnippet,
    required this.specDir,
    required this.apiFeatureUrl,
    required this.dashboardUrl,
    required this.orchestrationRel,
    this.currentStepLabel,
  });

  final String featureId;
  final int phase;
  final String status;
  final bool awaitingUser;
  final Map<String, dynamic> gates;
  final String requirementSnippet;
  final String specDir;
  final String apiFeatureUrl;
  final String dashboardUrl;
  final String orchestrationRel;
  final String? currentStepLabel;
}

enum OrchestratorAction { resume, sync, clarify, answerOnly, execute }

class OrchestratorChatResult {
  OrchestratorChatResult({
    required this.assistantReply,
    required this.orchestratorCommand,
    required this.agentPrompt,
    required this.action,
    required this.source,
    this.latencyMs,
  });

  final String assistantReply;
  final String orchestratorCommand;
  final String agentPrompt;
  final OrchestratorAction action;
  final String source;

  /// Wall-clock ms from question received to answer ready (stamped by
  /// [OrchestratorChatProcessor.process]).
  int? latencyMs;

  bool get shouldRunAgent => action != OrchestratorAction.answerOnly;
}
