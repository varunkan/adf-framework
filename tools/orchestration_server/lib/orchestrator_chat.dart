import 'dart:convert';
import 'dart:io';

import 'agent_chat_runner.dart';
import 'conversation_builder.dart';
import 'feature_store.dart';
import 'pipeline_planner.dart';

/// LLM interprets dashboard chat and produces orchestrator actions + agent prompts.
class OrchestratorChatProcessor {
  OrchestratorChatProcessor(
    this.store, {
    PipelinePlanner? planner,
    AgentChatRunner? agentChat,
  })  : _planner = planner,
        _agentChat = agentChat ?? AgentChatRunner(repoRoot: store.repoRoot);

  final FeatureStore store;
  final PipelinePlanner? _planner;
  final AgentChatRunner _agentChat;

  static const _defaultModel = 'gpt-4o-mini';

  Future<OrchestratorChatResult> process(
    String featureId,
    String userMessage,
  ) async {
    final trimmed = userMessage.trim();
    if (trimmed.isEmpty) {
      throw ArgumentError('empty message');
    }
    if (trimmed.startsWith('@orch-orchestrator')) {
      return OrchestratorChatResult(
        assistantReply:
            'Running orchestrator command: ${trimmed.split('\n').first}',
        orchestratorCommand: trimmed.split('\n').first,
        agentPrompt: trimmed,
        action: OrchestratorAction.execute,
        source: 'direct',
      );
    }

    final ctx = await _buildContext(featureId);
    final contextBlock = _formatContextBlock(ctx);
    final history = ConversationBuilder(store).build(featureId, limit: 12);

    final apiKey = _llmApiKey();
    if (apiKey != null) {
      try {
        return await _callHttpLlm(ctx, trimmed, apiKey);
      } catch (_) {}
    }

    if (await _shouldTryCursorChat()) {
      final agentReply = await _agentChat.converse(
        featureId: featureId,
        contextBlock: contextBlock,
        userMessage: trimmed,
        recentMessages: history,
      );
      if (agentReply != null && agentReply.reply.trim().isNotEmpty) {
        return _fromAgentChat(ctx, trimmed, agentReply);
      }
    }

    final contextual = _tryContextualAnswer(ctx, trimmed);
    if (contextual != null) return contextual;

    return _fallback(
      ctx,
      trimmed,
      note:
          'Could not reach a chat model. Run cursor-agent login or set ORCH_LLM_API_KEY / GROQ_API_KEY on the API server.',
    );
  }

  Future<bool> _shouldTryCursorChat() async {
    if (Platform.environment['ORCH_CHAT_USE_CURSOR'] == '0' ||
        Platform.environment['ORCH_CHAT_USE_CURSOR'] == 'false') {
      return false;
    }
    final health = await _agentChat.health.probe();
    return health['ready'] == true;
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
    return Platform.environment['ORCH_LLM_API_KEY'] ??
        Platform.environment['OPENAI_API_KEY'] ??
        Platform.environment['GROQ_API_KEY'];
  }

  String _llmApiUrl() {
    return Platform.environment['ORCH_LLM_API_URL'] ??
        (Platform.environment['GROQ_API_KEY'] != null
            ? 'https://api.groq.com/openai/v1/chat/completions'
            : 'https://api.openai.com/v1/chat/completions');
  }

  String _llmModel() {
    return Platform.environment['ORCH_LLM_MODEL'] ??
        (Platform.environment['GROQ_API_KEY'] != null
            ? 'llama-3.3-70b-versatile'
            : _defaultModel);
  }

  int get _apiPort =>
      int.tryParse(Platform.environment['ORCH_PORT'] ?? '3847') ?? 3847;

  int get _webPort =>
      int.tryParse(Platform.environment['ORCH_WEB_PORT'] ?? '3848') ?? 3848;

  String get _apiBase => 'http://localhost:$_apiPort';

  String get _dashboardBase => 'http://localhost:$_webPort';

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
        final plan = _planner!.buildPlan(featureId);
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

    return OrchestratorChatResult(
      assistantReply:
          'Here is the current context for **${ctx.featureId}**:\n\n$links',
      orchestratorCommand: '@orch-orchestrator resume ${ctx.featureId}',
      agentPrompt: '',
      action: OrchestratorAction.answerOnly,
      source: 'context',
    );
  }

  bool _isInformationalQuery(String lower) {
    if (_asksForUrl(lower) || _asksPhaseOrStatus(lower) || _asksHelp(lower)) {
      return true;
    }
    final q = RegExp(
      r'^(what|where|which|how|when|who|is|are|can|could|tell me|show me|list)\b',
    );
    return q.hasMatch(lower) &&
        !lower.contains('add ') &&
        !lower.contains('implement') &&
        !lower.contains('build ') &&
        !lower.contains('fix ');
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
  ) async {
    final system = _systemPrompt(ctx);
    final body = jsonEncode({
      'model': _llmModel(),
      'temperature': 0.2,
      'response_format': {'type': 'json_object'},
      'messages': [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': userMessage},
      ],
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
  "assistant_reply": "friendly reply to the user in chat (2-4 sentences). For URL/status questions, include the links above.",
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
    OrchestratorAction action;
    String cmd;
    if (lower.contains('sync') ||
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
    reply.writeln(
      'Got it — I will route this to the orchestrator for phase ${ctx.phase}.',
    );
    if (_llmApiKey() == null) {
      reply.writeln(
        '\n_Tip: set `ORCH_LLM_API_KEY` on the API server for smarter replies. '
        'You can also ask: "what is the URL for this feature?" or "what phase?"_',
      );
    }
    final agentPrompt = _buildAgentPrompt(
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
  });

  final String assistantReply;
  final String orchestratorCommand;
  final String agentPrompt;
  final OrchestratorAction action;
  final String source;

  bool get shouldRunAgent => action != OrchestratorAction.answerOnly;
}
