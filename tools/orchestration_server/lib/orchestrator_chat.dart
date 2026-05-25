import 'dart:convert';
import 'dart:io';

import 'feature_store.dart';
import 'pipeline_planner.dart';

/// LLM interprets dashboard chat and produces orchestrator actions + agent prompts.
class OrchestratorChatProcessor {
  OrchestratorChatProcessor(this.store, {PipelinePlanner? planner})
      : _planner = planner;

  final FeatureStore store;
  final PipelinePlanner? _planner;

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
    final apiKey = _llmApiKey();
    if (apiKey != null) {
      try {
        return await _callHttpLlm(ctx, trimmed, apiKey);
      } catch (e) {
        return _fallback(ctx, trimmed, note: 'LLM error: $e');
      }
    }
    return _fallback(ctx, trimmed, note: null);
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

  Future<OrchestratorChatContext> _buildContext(String featureId) async {
    final state = store.readState(featureId);
    final phase = store.effectivePhase(featureId, state);
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    final awaiting = state['awaiting_user'] == true;
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
    );
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
      return _parseLlmJson(ctx, content.trim());
    } finally {
      client.close(force: true);
    }
  }

  String _systemPrompt(OrchestratorChatContext ctx) {
    return '''You are the ADF v3 orchestrator assistant for feature "${ctx.featureId}".
Current phase: ${ctx.phase}. Status: ${ctx.status}. Awaiting user approval: ${ctx.awaitingUser}.
Gates: ${jsonEncode(ctx.gates)}.
${ctx.currentStepLabel != null ? 'Active pipeline step: ${ctx.currentStepLabel}' : ''}

Requirement excerpt:
${ctx.requirementSnippet.isEmpty ? '(none yet)' : ctx.requirementSnippet}

Respond with ONLY valid JSON:
{
  "assistant_reply": "friendly reply to the user in chat (2-4 sentences)",
  "action": "resume" | "sync" | "clarify" | "answer_only",
  "orchestrator_command": "@orch-orchestrator resume|sync ${ctx.featureId}",
  "agent_instructions": "detailed instructions for the coding agent to execute now"
}

Rules:
- action "sync" when user approves or confirms moving forward after review.
- action "resume" when user wants work continued on current phase builders.
- action "clarify" when user adds requirements — update requirement.md and re-run intake/spec.
- action "answer_only" for pure questions with no agent work.
- orchestrator_command must start with @orch-orchestrator.
- agent_instructions must tell the agent to follow ADF routing and update artifacts under specs/ and orchestration/features/.''';
  }

  OrchestratorChatResult _parseLlmJson(
    OrchestratorChatContext ctx,
    String content,
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
    final agentPrompt = _buildAgentPrompt(ctx, cmd, instructions, '');
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
        lower.contains('proceed')) {
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
    if (note != null) reply.writeln(note);
    reply.writeln(
      'I will route this to the orchestrator (phase ${ctx.phase}). '
      'Set ORCH_LLM_API_KEY for richer interpretation.',
    );
    reply.writeln('\n**You said:** $userMessage');
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
    this.currentStepLabel,
  });

  final String featureId;
  final int phase;
  final String status;
  final bool awaitingUser;
  final Map<String, dynamic> gates;
  final String requirementSnippet;
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
