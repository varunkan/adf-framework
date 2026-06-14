import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/agent_crew.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/audit_bundle.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:orchestration_server/conversation_builder.dart';
import 'package:orchestration_server/cost_meter.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/figma_connector.dart';
import 'package:orchestration_server/integrity_chain.dart';
import 'package:orchestration_server/model_router.dart';
import 'package:orchestration_server/orch_env_loader.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:orchestration_server/pipeline_planner.dart';
import 'package:orchestration_server/preview_service.dart';
import 'package:orchestration_server/run_post_sync.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as io;
import 'package:shelf_router/shelf_router.dart';

const _corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, HEAD',
  'Access-Control-Allow-Headers': 'Content-Type, Accept, Origin, Authorization',
  'Access-Control-Max-Age': '86400',
};

Response _json(Object body, {int status = 200}) => Response(
      status,
      body: jsonEncode(body),
      headers: {
        'Content-Type': 'application/json',
        ..._corsHeaders,
      },
    );

Middleware _corsMiddleware() {
  return (Handler inner) {
    return (Request request) async {
      if (request.method == 'OPTIONS') {
        return Response(204, headers: _corsHeaders);
      }
      final response = await inner(request);
      return response.change(headers: _corsHeaders);
    };
  };
}

/// Model-router tier map from env — mirrors the router contract so /health
/// and the boot log report routing without a hard router dependency. Cloud
/// tiers require ANTHROPIC_API_KEY; without it the router degrades to
/// local-only (never an error), so the effective mode is reported.
Map<String, dynamic> _modelRouterInfo(Map<String, String> env) {
  final router = ModelRouter(env: env);
  final cloudReady = router.hasApiKey;
  final configured = (env['ORCH_ROUTER'] ?? 'auto').trim().toLowerCase();
  final mode = const {'auto', 'local-only', 'cloud-only'}.contains(configured)
      ? configured
      : 'auto';
  return {
    'mode': cloudReady ? mode : 'local-only',
    'tiers': {
      'local': env['ORCH_OLLAMA_MODEL'] ?? OllamaBrain.defaultModel,
      'fast': router.modelForTier('fast'),
      'balanced': router.modelForTier('balanced'),
      'deep': router.modelForTier('deep'),
    },
    'providers': {
      'fast': router.providerForTier('fast'),
      'balanced': router.providerForTier('balanced'),
      'deep': router.providerForTier('deep'),
    },
    'cloud_ready': cloudReady,
    'nvidia_ready': router.hasNvidiaKey,
    'anthropic_ready': router.hasAnthropicKey,
  };
}

Future<void> _loadAgentEnv(String repoRoot) async {
  final home = Platform.environment['HOME'] ?? '';
  final envFile = File('$home/.cursor/agent.env');
  if (!envFile.existsSync()) return;
  for (final line in envFile.readAsLinesSync()) {
    final trimmed = line.trim();
    if (trimmed.isEmpty || trimmed.startsWith('#')) continue;
    final eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    final key = trimmed.substring(0, eq).trim();
    var value = trimmed.substring(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.substring(1, value.length - 1);
    }
    if (Platform.environment[key] == null) {
      Platform.environment[key] = value;
    }
  }
}

Future<void> main(List<String> args) async {
  final port = int.tryParse(
        Platform.environment['ORCH_PORT'] ?? '3847',
      ) ??
      3847;
  final repoRoot = resolveRepoRoot();
  await _loadAgentEnv(repoRoot);
  // Platform.environment is unmodifiable, so merge repo-local .env values over
  // it into a plain map the router/chat read from. Exported keys still win.
  final env = <String, String>{
    ...Platform.environment,
    ...readOrchEnv(repoRoot),
  };

  final store = FeatureStore(repoRoot);
  final runner = PhaseRunner(store);
  final artifactValidator = ArtifactValidator(repoRoot);
  final planner = PipelinePlanner(store);
  final conversation = ConversationBuilder(store);
  final costs = CostMeter(store);
  // Complexity router for dashboard chat: simple turns stay on the free local
  // Ollama tier, harder ones lift to free NVIDIA NIM (fast/balanced) or paid
  // Claude (deep), per available keys. Injected so `ORCH_CHAT_LLM=auto`
  // actually routes — without it the chat path falls straight through to
  // local Ollama.
  final chatRouter = ModelRouter(env: env);
  // Router-selected cloud chat calls meter spend through the same CostMeter
  // the cost routes serve; chat is not a pipeline phase, so entries record
  // phase null. NVIDIA's free tier reports tokens with $0 cost.
  final chatProcessor = OrchestratorChatProcessor(
    store,
    planner: planner,
    router: chatRouter,
    env: env,
    onUsage: (featureId, event) =>
        costs.recordFromResultEvent(featureId, event),
  );
  final postSync = RunPostSync(store);
  final brainSelector = BrainSelector();
  final learnings = LearningStore(repoRoot);
  final figma = FigmaConnector();
  final integrity = IntegrityChain(store);
  final auditBundles =
      AuditBundleBuilder(store, integrity: integrity, costs: costs);
  final previewService = PreviewService(
    store,
    repoRoot,
    integrity: integrity,
    validator: artifactValidator,
    apiPort: port,
  );
  final autoAutopilot = Platform.environment['ORCH_AUTO_AUTOPILOT'] != 'false';

  Future<Map<String, dynamic>> runCrewForFeature(String id) async {
    final brain = await brainSelector.select();
    final engine = DeterministicArtifactEngine(store, brain: brain);
    final crew = AgentCrew(store, engine, artifactValidator, learnings,
        integrity: integrity);
    return crew.run(id).timeout(const Duration(seconds: 120));
  }

  /// Pulls a Figma design and folds it into the feature requirement so the
  /// crew generates design-aware specs. Zero model cost.
  Future<Map<String, dynamic>> figmaIntake(String id, String url) async {
    final key = FigmaConnector.fileKeyFromUrl(url);
    if (key == null) {
      throw ArgumentError('not a Figma file URL: $url');
    }
    final file = await figma.fetchFile(key);
    final design = figma.parseFile(file);
    final md = figma.designMarkdown(design, sourceUrl: url);
    final designPath = File('$repoRoot/specs/$id/design.md');
    designPath.parent.createSync(recursive: true);
    designPath.writeAsStringSync(md);

    final fragments = design.requirementFragments();
    if (fragments.isNotEmpty) {
      final reqFile = File('${store.featurePath(id)}/requirement.md');
      final existing = reqFile.existsSync() ? reqFile.readAsStringSync() : '';
      if (!existing.contains('## Design requirements (Figma)')) {
        reqFile.writeAsStringSync(
          '$existing\n\n## Design requirements (Figma)\n\n'
          '${fragments.map((f) => 'The app must $f.').join(' ')}\n',
        );
      }
    }
    return {
      'file': design.fileName,
      'screens': design.screens.length,
      'components': design.components.length,
      'colors': design.colors,
      'design_md': 'specs/$id/design.md',
    };
  }
  final autoRunner = Platform.environment['ORCH_AUTO_RUNNER'] != 'false';

  if (autoRunner) {
    runner.startBackgroundPoller();
  }

  final health = await runner.getHealth();
  print('Orchestration server repo root: $repoRoot');
  print('Auto phase runner: ${autoRunner ? 'on' : 'off'}');
  print('Active runner: ${health['runner'] ?? 'cursor'} '
      '(ADF_RUNNER=${Platform.environment['ADF_RUNNER'] ?? 'auto'})');
  print('Runner ready: ${health['ready']} (${health['agent_path'] ?? 'no agent'})');
  final chatLlm = await chatProcessor.describeChatLlm();
  print('Chat LLM: $chatLlm (ORCH_CHAT_LLM=${chatProcessor.chatLlmMode}, '
      'key ${orchLlmConfigured(env) ? 'set' : 'unset'})');
  final modelRouter = _modelRouterInfo(env);
  final routerTiers = modelRouter['tiers'] as Map<String, dynamic>;
  final routerProviders = modelRouter['providers'] as Map<String, dynamic>;
  final cloudLabel = modelRouter['cloud_ready'] == true
      ? 'ready — nvidia=${modelRouter['nvidia_ready']} anthropic=${modelRouter['anthropic_ready']}'
      : 'off — set NVIDIA_API_KEY (free) or ANTHROPIC_API_KEY';
  print('Model router: mode=${modelRouter['mode']} (cloud $cloudLabel) '
      'tiers local=${routerTiers['local']} '
      'fast=${routerProviders['fast']}:${routerTiers['fast']} '
      'balanced=${routerProviders['balanced']}:${routerTiers['balanced']} '
      'deep=${routerProviders['deep']}:${routerTiers['deep']}');
  if (chatLlm.startsWith('ollama:')) {
    unawaited(chatProcessor.warmOllama().then((_) =>
        print('Local chat model warmed and resident ($chatLlm)')));
  }


  Future<void> runChatInBackground(
    String featureId,
    String commandId,
    String prompt,
  ) async {
    await runner.health.killStalePrintAgents();
    try {
      OrchestratorChatResult chat;
      var lastFlush = DateTime.now();
      var finalized = false;
      void streamPartial(String partial) {
        if (finalized) return;
        final now = DateTime.now();
        if (now.difference(lastFlush).inMilliseconds < 700) return;
        lastFlush = now;
        store.updateCommandMeta(
          featureId,
          commandId,
          assistantReply: partial,
          llmSource: 'streaming',
        );
      }

      try {
        chat = await chatProcessor
            .process(
              featureId,
              prompt,
              mode: ChatProcessMode.full,
              onPartial: streamPartial,
            )
            .timeout(const Duration(seconds: 95));
      } on TimeoutException {
        await runner.health.killStalePrintAgents();
        chat = await chatProcessor.process(
          featureId,
          prompt,
          mode: ChatProcessMode.stateOnly,
        );
      }
      finalized = true;
      store.updateCommandMeta(
        featureId,
        commandId,
        assistantReply: chat.assistantReply,
        orchestratorCommand: chat.orchestratorCommand,
        agentPrompt: chat.agentPrompt,
        llmSource: chat.source,
      );
      if (chat.shouldRunAgent) {
        final state = store.readState(featureId);
        if (state['status'] != 'completed') {
          final healthNow = await runner.getHealth(refresh: false);
          if (healthNow['ready'] == true) {
            await runner.enqueueCommand(
              featureId,
              prompt: prompt,
              commandId: commandId,
              agentPrompt: chat.agentPrompt,
            );
          }
        }
      }
    } catch (e) {
      store.updateCommandMeta(
        featureId,
        commandId,
        assistantReply: 'Chat failed: $e',
        llmSource: 'error',
      );
    }
  }

  // ---- Efficiency layer: fingerprint cache + request metrics ----
  final detailCache = <String, MapEntry<String, Map<String, dynamic>>>{};
  var cacheHits = 0;
  var cacheMisses = 0;
  var notModifiedCount = 0;
  final serverStarted = DateTime.now();
  final routeCounts = <String, int>{};
  final routeMicros = <String, int>{};

  /// Cheap change detector: mtime+size of the files driving the payload.
  String featureFingerprint(String id) {
    final buf = StringBuffer();
    for (final rel in [
      'state.json',
      'commands.jsonl',
      'run-status.json',
      'run-log.jsonl',
      'requirement.md',
    ]) {
      final fl = File('${store.featurePath(id)}/$rel');
      if (fl.existsSync()) {
        final st = fl.statSync();
        buf.write('$rel:${st.modified.microsecondsSinceEpoch}:${st.size};');
      }
    }
    final verdicts = Directory('${store.featurePath(id)}/judge-verdicts');
    if (verdicts.existsSync()) {
      buf.write('jv:${verdicts.statSync().modified.microsecondsSinceEpoch};');
    }
    return buf.toString();
  }

  Map<String, dynamic> buildDetailPayload(String id) {
    store.reconcileFeatureState(id);
    store.repairRunStatus(id);
    runner.reconcileStaleRunStatus(id);
    Map<String, dynamic>? pipeline;
    try {
      pipeline = planner.buildPlan(id);
    } catch (e) {
      pipeline = {'error': e.toString(), 'phases': []};
    }
    final detail = store.featureDetail(id, pipeline: pipeline);
    detail['conversation'] = conversation.buildChatView(id);
    return detail;
  }

  /// Cached payload: when nothing on disk changed, skip reconcile, planner,
  /// and conversation rebuild entirely.
  Map<String, dynamic> featureDetailPayload(String id) {
    final fp = featureFingerprint(id);
    final cached = detailCache[id];
    if (cached != null && cached.key == fp) {
      cacheHits++;
      return cached.value;
    }
    cacheMisses++;
    final detail = buildDetailPayload(id);
    // Reconcile may have rewritten files; fingerprint after build so the
    // cache is keyed to the settled on-disk state.
    detailCache[id] = MapEntry(featureFingerprint(id), detail);
    return detail;
  }

  // After the deterministic crew (phases 1-6) hands off at phase 7, the feature
  // is at current_phase=7 but NOTHING queues the implement run — the background
  // poller is purely reactive to a phase_request/queued marker, and the crew
  // writes neither. So phase 7 sat idle until a manual POST /run {phase:7}.
  // This connects the baton: on a clean handoff, queue phase 7 automatically so
  // one prompt goes all the way to working code. Gated on the handoff reason so
  // a 'blocked' crew (validator/timeout) never auto-pushes code generation.
  Future<void> autoEnqueueImplement(String id, Map<String, dynamic> summary) async {
    if (!autoRunner || summary['stop_reason'] != 'implementation_handoff') return;
    try {
      await runner.enqueue(id, phase: 7);
    } catch (e) {
      stderr.writeln('auto-enqueue phase 7 failed for $id: $e');
    }
  }

  void kickAutopilotBackground(String id) {
    unawaited(() async {
      try {
        detailCache.remove(id);
        final summary = await runCrewForFeature(id);
        detailCache.remove(id);
        await autoEnqueueImplement(id, summary);
      } catch (e) {
        stderr.writeln('autopilot background failed for $id: $e');
      }
    }());
  }

  final router = Router();

  // /health is polled constantly; cache the expensive cursor probe for 60s.
  Map<String, dynamic>? healthCache;
  DateTime healthCachedAt = DateTime.fromMillisecondsSinceEpoch(0);
  router.get('/health', (Request _) async {
    if (healthCache == null ||
        DateTime.now().difference(healthCachedAt) >
            const Duration(seconds: 60)) {
      healthCache = {
        'status': 'ok',
        'repo': repoRoot,
        'chat_llm': await chatProcessor.describeChatLlm(),
        'chat_llm_configured':
            orchLlmConfigured(env) || await chatProcessor.ollamaChatReady(),
        'chat_cursor_ready': await chatProcessor.cursorChatReady(),
        'chat_prefer_cursor': chatProcessor.cursorIsPreferred,
        'chat_static_context':
            Platform.environment['ORCH_CHAT_STATIC_CONTEXT'] == '1',
        'model_router': modelRouter,
      };
      healthCachedAt = DateTime.now();
    }
    return _json(healthCache!);
  });

  router.get('/runner/health', (Request request) async {
    try {
      final refresh =
          request.url.queryParameters['refresh'] == 'true';
      final h = await runner.getHealth(refresh: refresh);
      return _json(h);
    } catch (e) {
      return _json({'error': e.toString(), 'ready': false}, status: 500);
    }
  });

  router.post('/runner/verify-print', (Request _) async {
    try {
      await runner.health.killStalePrintAgents();
      final printOk = await runner.health.livenessProbe();
      final base = await runner.health.probe();
      return _json({
        ...base,
        'headless_ready': printOk,
        'verified_at': DateTime.now().toUtc().toIso8601String(),
      });
    } catch (e) {
      return _json({'error': e.toString(), 'headless_ready': false}, status: 500);
    }
  });

  router.get('/features', (Request _) {
    try {
      final ids = store.listFeatures();
      // Quarantine corrupt features (e.g. missing state.json) instead of
      // letting one bad directory take down the whole listing.
      final list = <Map<String, dynamic>>[];
      final quarantined = <String>[];
      for (final fid in ids) {
        try {
          list.add(store.featureSummary(fid));
        } catch (_) {
          quarantined.add(fid);
        }
      }
      return _json({
        'features': list,
        'count': list.length,
        'api': 'http://localhost:$port',
        if (quarantined.isNotEmpty) 'quarantined': quarantined,
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final detail = featureDetailPayload(id);
      final etag = '"${featureFingerprint(id).hashCode.toRadixString(16)}"';
      if (request.headers['if-none-match'] == etag) {
        notModifiedCount++;
        return Response(304, headers: {'ETag': etag, ..._corsHeaders});
      }
      final res = _json(detail);
      return res.change(headers: {'ETag': etag});
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>/conversation', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final limit =
          int.tryParse(request.url.queryParameters['limit'] ?? '50') ?? 50;
      final messages = conversation.buildChatView(id, limit: limit);
      return _json({
        'feature_id': id,
        'messages': messages,
        'count': messages.length,
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.post('/features/<id>/sync-state', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      Map<String, dynamic> body = {};
      try {
        final raw = await request.readAsString();
        if (raw.isNotEmpty) {
          body = jsonDecode(raw) as Map<String, dynamic>;
        }
      } catch (_) {}
      final run = store.readRunStatus(id);
      final phase = (body['phase'] as num?)?.toInt() ??
          (run?['phase'] as num?)?.toInt() ??
          (store.readState(id)['current_phase'] as num?)?.toInt() ??
          1;
      store.reconcileFeatureState(id);
      final awaiting = postSync.syncAfterRun(id, phase > 0 ? phase : 1);
      return _json({
        'ok': true,
        'awaiting_approval': awaiting,
        'feature': featureDetailPayload(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.get('/features/<id>/artifact-checklist', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final phaseStr = request.url.queryParameters['phase'];
      final state = store.readState(id);
      final phase = phaseStr != null
          ? int.tryParse(phaseStr) ?? 0
          : (state['pending_approval_phase'] as num?)?.toInt() ??
              (state['current_phase'] as num?)?.toInt() ??
              1;
      if (phase < 1) {
        return _json({'error': 'invalid phase'}, status: 400);
      }
      final checklist = await artifactValidator.checklist(id, phase);
      return _json(checklist);
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>/pipeline', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      return _json(planner.buildPlan(id));
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>/run-log', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final limit =
          int.tryParse(request.url.queryParameters['limit'] ?? '50') ?? 50;
      return _json({
        'feature_id': id,
        'entries': store.readRunLog(id, limit: limit),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>/commands', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final limit =
          int.tryParse(request.url.queryParameters['limit'] ?? '20') ?? 20;
      return _json({
        'feature_id': id,
        'commands': store.listCommands(id, limit: limit),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.post('/features/<id>/commands', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final body =
          jsonDecode(await request.readAsString()) as Map<String, dynamic>;
      final prompt = body['prompt'] as String?;
      if (prompt == null || prompt.trim().isEmpty) {
        return _json({'error': 'prompt required'}, status: 400);
      }
      final stepId = body['step_id'] as String?;
      final execute = body['execute'] as bool? ?? false;

      final cmd = store.appendCommand(
        id,
        prompt: prompt.trim(),
        stepId: stepId,
        execute: execute,
      );

      // Instant-first chat: reply in milliseconds at zero token cost.
      // Free-form questions go to a cloud LLM (if configured) or local
      // Ollama (~seconds, $0). cursor-agent refinement is opt-in via
      // ORCH_CHAT_REFINE=1 and upgrades the reply in place.
      OrchestratorChatResult chat;
      final refineEnabled =
          Platform.environment['ORCH_CHAT_REFINE'] == '1' ||
              Platform.environment['ORCH_CHAT_REFINE'] == 'true';

      final hasHttpLlm =
          (chatProcessor.llmApiKey != null && !chatProcessor.preferCursorCli) ||
              await chatProcessor.ollamaChatReady();
      chat = await chatProcessor.process(
        id,
        prompt.trim(),
        mode: hasHttpLlm ? ChatProcessMode.httpOnly : ChatProcessMode.stateOnly,
      );
      store.updateCommandMeta(
        id,
        cmd['id'] as String,
        assistantReply: chat.assistantReply,
        orchestratorCommand: chat.orchestratorCommand,
        agentPrompt: chat.agentPrompt,
        llmSource: chat.source,
        latencyMs: chat.latencyMs,
      );
      // The instant tier already produced a final answer — never replace it
      // with a 'Thinking…'/streaming placeholder pass.
      final instantAnswered = chat.source == 'state' || chat.source == 'direct';
      if (refineEnabled &&
          !instantAnswered &&
          await chatProcessor.cursorChatReady()) {
        unawaited(runChatInBackground(id, cmd['id'] as String, prompt.trim()));
      }

      if (execute) {
        if (chat.source == 'pending') {
          return _json({
            'ok': true,
            'mode': 'chat_pending',
            'command': cmd,
            'assistant_message': chat.assistantReply,
            'orchestrator_command': chat.orchestratorCommand,
            'llm_source': chat.source,
            'latency_ms': chat.latencyMs,
            'feature': featureDetailPayload(id),
          });
        }

        final state = store.readState(id);

        if (!chat.shouldRunAgent) {
          return _json({
            'ok': true,
            'mode': 'llm_answer',
            'command': cmd,
            'assistant_message': chat.assistantReply,
            'orchestrator_command': chat.orchestratorCommand,
            'llm_source': chat.source,
            'latency_ms': chat.latencyMs,
            'feature': featureDetailPayload(id),
          });
        }

        if (state['status'] == 'completed') {
          store.appendClientClarification(id, prompt.trim());
          return _json({
            'ok': true,
            'mode': 'feature_complete',
            'command': cmd,
            'assistant_message': chat.assistantReply,
            'orchestrator_command': chat.orchestratorCommand,
            'llm_source': chat.source,
            'latency_ms': chat.latencyMs,
            'message':
                'Feature is completed — notes saved to requirement.md only.',
            'feature': featureDetailPayload(id),
          });
        }

        final healthNow = await runner.getHealth(refresh: true);
        Map<String, dynamic> result;
        if (healthNow['ready'] != true) {
          store.appendClientClarification(id, prompt.trim());
          result = {
            'success': true,
            'mode': 'llm_ide',
            'message': chat.assistantReply,
            'hint': healthNow['hint'],
          };
        } else {
          result = await runner.enqueueCommand(
            id,
            prompt: prompt.trim(),
            stepId: stepId,
            commandId: cmd['id'] as String,
            agentPrompt: chat.agentPrompt,
          );
        }
        return _json({
          'ok': true,
          'mode': result['mode'] ?? 'llm_agent',
          'command': cmd,
          'assistant_message': chat.assistantReply,
          'orchestrator_command': chat.orchestratorCommand,
          'llm_source': chat.source,
          'latency_ms': chat.latencyMs,
          'result': result,
          'feature': featureDetailPayload(id),
        });
      }

      return _json({
        'ok': true,
        'command': cmd,
        'assistant_message': chat.assistantReply,
        'orchestrator_command': chat.orchestratorCommand,
        'llm_source': chat.source,
        'latency_ms': chat.latencyMs,
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.post('/features', (Request request) async {
    try {
      final body =
          jsonDecode(await request.readAsString()) as Map<String, dynamic>;
      var id = body['id'] as String?;
      final prompt = body['prompt'] as String? ?? '';
      final requirement = (body['requirement'] as String? ?? '').isNotEmpty
          ? body['requirement'] as String
          : prompt;
      final track = body['track'] as String? ?? 'M';
      if ((id == null || id.isEmpty) && requirement.trim().isEmpty) {
        return _json({'error': 'id or prompt required'}, status: 400);
      }
      if (id == null || id.isEmpty) {
        final existing = store.listFeatures().toSet();
        id = FeatureStore.generateFeatureId(requirement, existing: existing);
      }
      store.createFeature(id: id, requirement: requirement, track: track);
      if (FigmaConnector.looksLikeFigmaUrl(requirement) && figma.configured) {
        try {
          final url = RegExp(r'https?://\S*figma\.com/\S+')
              .firstMatch(requirement)!
              .group(0)!;
          await figmaIntake(id, url);
        } catch (_) {/* design intake is best-effort at create time */}
      }
      final payload = featureDetailPayload(id);
      payload['id'] = id;
      final fromPrompt = prompt.trim().isNotEmpty;
      final autopilotOnCreate =
          body['autopilot'] == true || (fromPrompt && autoAutopilot);
      if (autopilotOnCreate) {
        payload['mode'] = 'building';
        payload['message'] =
            'ADF crew is building spec, plan, and tests (zero tokens)…';
        payload['autopilot_started'] = true;
        kickAutopilotBackground(id);
      } else if (autoRunner) {
        // Cached health only — avoid 20s `--print` probe on every new feature.
        final h = await runner.getHealth(refresh: false);
        if (h['ready'] == true) {
          final run = await runner.enqueue(id, phase: 1);
          if (run['headless_unavailable'] == true ||
              run['resume_mode'] == 'cursor_ide') {
            payload['mode'] = 'ide_only';
            payload['message'] =
                'Feature created. Headless agent is unavailable on this host — '
                'run `@orch-orchestrator start $id` in Cursor IDE, then Sync '
                'in the dashboard.';
          } else if (run['status'] == 'queued') {
            payload['mode'] = 'queued';
            payload['message'] = 'Phase 1 queued for headless runner.';
          }
        } else {
          payload['mode'] = 'needs_login';
          payload['message'] = h['hint'] as String? ??
              'Run cursor-agent login, then open the feature in the dashboard.';
        }
      }
      return _json(payload, status: 201);
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.get('/metrics', (Request _) {
    final polls = cacheHits + cacheMisses;
    final byRoute = <String, dynamic>{};
    routeCounts.forEach((route, count) {
      byRoute[route] = {
        'count': count,
        'avg_ms': count == 0
            ? 0
            : ((routeMicros[route] ?? 0) / count / 1000).toStringAsFixed(2),
      };
    });
    return _json({
      'uptime_s': DateTime.now().difference(serverStarted).inSeconds,
      'token_spend': 'zero',
      'detail_cache': {
        'hits': cacheHits,
        'misses': cacheMisses,
        'hit_rate': polls == 0
            ? 1.0
            : double.parse((cacheHits / polls).toStringAsFixed(3)),
        'not_modified_304': notModifiedCount,
      },
      'routes': byRoute,
      'learnings': learnings.stats(),
    });
  });

  router.get('/brain', (Request _) async {
    final desc = await brainSelector.describe();
    desc['learnings'] = learnings.stats();
    desc['figma_configured'] = figma.configured;
    return _json(desc);
  });

  router.get('/features/<id>/preview', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final phaseStr = request.url.queryParameters['phase'];
      final phase = phaseStr != null ? int.tryParse(phaseStr) : null;
      final payload = await previewService.studioPreview(id, phase: phase);
      final etag =
          '"preview-${featureFingerprint(id).hashCode.toRadixString(16)}"';
      if (request.headers['if-none-match'] == etag) {
        return Response(304, headers: {'ETag': etag, ..._corsHeaders});
      }
      final res = _json(payload);
      return res.change(headers: {'ETag': etag});
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>/studio-preview', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final phaseStr = request.url.queryParameters['phase'];
      final phase = phaseStr != null ? int.tryParse(phaseStr) : null;
      final data = await previewService.studioPreview(id, phase: phase);
      return _json(data);
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.post('/features/<id>/preview/build', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final result = await previewService.kickoffBuild(id);
      return _json(result);
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>/integrity', (Request request, String id) {
    if (!store.featureExists(id)) {
      return _json({'error': 'unknown feature: $id'}, status: 404);
    }
    // Routine polling uses the reliable fast path; ?strict=true forces a full
    // raw-byte re-hash for adversarial audits.
    final strict = request.url.queryParameters['strict'] == 'true';
    return _json(integrity.verify(id, strict: strict));
  });

  router.get('/features/<id>/audit-bundle', (Request request, String id) {
    if (!store.featureExists(id)) {
      return _json({'error': 'unknown feature: $id'}, status: 404);
    }
    // Self-verifying proof document — check it offline (no server, no Dart)
    // with scripts/orch/verify_audit_bundle.py.
    return _json(auditBundles.build(id));
  });

  router.post('/features/<id>/figma', (Request request, String id) async {
    if (!store.featureExists(id)) {
      return _json({'error': 'unknown feature: $id'}, status: 404);
    }
    try {
      final body =
          jsonDecode(await request.readAsString()) as Map<String, dynamic>;
      final url = body['url'] as String? ?? '';
      final result = await figmaIntake(id, url);
      return _json({'ok': true, ...result});
    } on StateError catch (e) {
      return _json({'error': e.message, 'figma_configured': false},
          status: 422);
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });


  router.get('/features/<id>/crew-log', (Request request, String id) {
    final file = File('${store.featurePath(id)}/crew-log.jsonl');
    if (!file.existsSync()) return _json({'agents': []});
    final agents = file
        .readAsLinesSync()
        .where((l) => l.trim().isNotEmpty)
        .map((l) => jsonDecode(l))
        .toList();
    return _json({'agents': agents});
  });

  router.post('/features/<id>/autopilot', (Request request, String id) async {
    if (!store.featureExists(id)) {
      return _json({'error': 'unknown feature: $id'}, status: 404);
    }
    try {
      final summary = await runCrewForFeature(id);
      detailCache.remove(id);
      await autoEnqueueImplement(id, summary);
      summary['detail'] = featureDetailPayload(id);
      return _json(summary);
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.post('/features/<id>/approve', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final body =
          jsonDecode(await request.readAsString()) as Map<String, dynamic>;
      final phase = body['phase'] as int?;
      final decision = body['decision'] as String? ?? 'approved';
      final notes = body['notes'] as String? ?? '';
      final source = body['source'] as String? ?? 'dashboard';
      final judgeWaiver = body['judge_waiver'] as bool? ?? false;
      final artifactWaiver = body['artifact_waiver'] as bool? ?? false;
      final clientConfirmed = body['client_confirmed'] as bool? ?? false;
      if (phase == null) {
        return _json({'error': 'phase required'}, status: 400);
      }
      if (!FeatureStore.isPipelinePhase(phase)) {
        return _json(
          {
            'error':
                'Invalid phase $phase — ADF pipeline is phases '
                '${FeatureStore.firstPipelinePhase}–${FeatureStore.lastPipelinePhase} only.',
          },
          status: 400,
        );
      }

      final state = store.readState(id);
      final verdict = state['last_judge_verdict'] as String?;

      if (decision == 'approved') {
        if (phase >= 2 && phase <= 4 && !artifactWaiver) {
          final checklist = await artifactValidator.checklist(id, phase);
          if (checklist['pass'] != true) {
            return _json(
              {
                'error':
                    'Cannot approve: ADF artifact validator failed. Use artifact_waiver: true to override.',
                'artifact_checklist': checklist,
              },
              status: 409,
            );
          }
        }
        if (verdict != 'pass' && !judgeWaiver) {
          return _json(
            {
              'error':
                  'Cannot approve: BMAD verdict is not pass (current: $verdict). Use judge_waiver: true to override.',
            },
            status: 409,
          );
        }
      }

      if (decision == 'revise' && !clientConfirmed) {
        return _json(
          {
            'error':
                'Client confirmation required before revise. Set client_confirmed: true after reviewing combined recommendation.',
          },
          status: 400,
        );
      }

      var sealApproval = false;
      store.appendApproval(id, {
        'phase': phase,
        'decision': decision,
        'at': DateTime.now().toUtc().toIso8601String(),
        'notes': notes,
        'source': source,
        'judge_waiver': judgeWaiver,
        if (clientConfirmed) 'client_confirmed': true,
        if (decision == 'revise')
          'combined_recommendation':
              store.readCombinedRecommendation(id, phase: phase),
      });

      if (decision == 'approved') {
        store.setGateForPhase(state, phase, true);
        state['awaiting_user'] = false;
        state['pending_approval_phase'] = null;
        sealApproval = true;
        if (phase >= FeatureStore.lastPipelinePhase) {
          state['current_phase'] = FeatureStore.lastPipelinePhase;
          state['status'] = 'completed';
        } else {
          final current = (state['current_phase'] as num?)?.toInt() ?? 0;
          if (current <= phase) {
            state['current_phase'] = phase + 1;
          }
        }
      } else if (decision == 'revise') {
        state['pending_approval_phase'] = phase;
        final rev = (state['phase_revision_count'] as num?)?.toInt() ?? 0;
        state['phase_revision_count'] = rev + 1;
        // Keep awaiting_user true so the approval bar stays if the follow-up command fails.
        state['awaiting_user'] = true;
      } else if (decision == 'rejected') {
        state['status'] = 'rejected';
        state['awaiting_user'] = false;
      }

      store.writeState(id, state);
      if (sealApproval) {
        integrity.seal(
          id,
          phase: phase,
          actor: 'human:$source',
          note: 'phase $phase approved',
        );
      }

      if (decision == 'approved' &&
          autoRunner &&
          phase < FeatureStore.lastPipelinePhase) {
        final h = await runner.getHealth(refresh: true);
        if (h['ready'] == true) {
          await runner.enqueue(id);
        }
      }

      return _json(featureDetailPayload(id));
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.get('/features/<id>/traces', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final limit =
          int.tryParse(request.url.queryParameters['limit'] ?? '100') ?? 100;
      final event = request.url.queryParameters['event'];
      final phaseStr = request.url.queryParameters['phase'];
      final phase = phaseStr != null ? int.tryParse(phaseStr) : null;
      final reasoningOnly =
          request.url.queryParameters['reasoning_only'] == 'true';
      final since = request.url.queryParameters['since'];
      final traces = store.readTraces(
        id,
        limit: limit,
        event: event,
        phase: phase,
        reasoningOnly: reasoningOnly,
        since: since,
      );
      final lastTs = traces.isEmpty
          ? since
          : traces.last['timestamp'] as String?;
      return _json({
        'feature_id': id,
        'traces': traces,
        'count': traces.length,
        'last_timestamp': lastTs,
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.post('/features/<id>/request-phase', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final body =
          jsonDecode(await request.readAsString()) as Map<String, dynamic>;
      final phase = body['phase'] as int?;
      final autoRun = body['auto_run'] as bool? ?? true;
      if (autoRun && autoRunner) {
        final status = await runner.enqueue(id, phase: phase);
        return _json({
          'ok': true,
          'cursor_prompt': '@orch-orchestrator resume $id',
          'phase_request': store.readPhaseRequest(id),
          'run_status': status,
        });
      }
      final state = store.readState(id);
      final current = (state['current_phase'] as num?)?.toInt() ?? 0;
      final runPhase = phase ?? (current > 0 ? current : 1);
      store.writePhaseRequest(id, runPhase);
      return _json({
        'ok': true,
        'cursor_prompt': '@orch-orchestrator resume $id',
        'phase_request': store.readPhaseRequest(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.post('/features/<id>/run', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final bodyStr = await request.readAsString();
      int? phase;
      if (bodyStr.isNotEmpty) {
        final parsed = jsonDecode(bodyStr) as Map<String, dynamic>;
        phase = parsed['phase'] as int?;
      }
      final status = await runner.enqueue(id, phase: phase);
      return _json({
        'ok': true,
        'run_status': status,
        'feature': featureDetailPayload(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.post('/features/<id>/heal', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final run = store.readRunStatus(id);
      final phase = (run?['phase'] as num?)?.toInt();
      final error = run?['error'] as String? ?? 'manual heal requested';
      final result = await runner.triggerSelfHeal(
        id,
        phase: phase,
        error: error,
      );
      return _json({
        'ok': result['success'] == true,
        'result': result,
        'feature': featureDetailPayload(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.post('/features/<id>/cancel', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final cancelled = await runner.cancelRun(id);
      runner.reconcileStaleRunStatus(id);
      return _json({
        'ok': cancelled,
        'feature': featureDetailPayload(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.post('/features/<id>/unstick', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final runStatus = await runner.unstickFeature(id);
      return _json({
        'ok': true,
        'run_status': runStatus,
        'feature': featureDetailPayload(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.post('/features/<id>/retry', (Request request, String id) async {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      final run = store.readRunStatus(id);
      final phase = (run?['phase'] as num?)?.toInt();
      // Genuinely un-block: clear the heal-exhaustion counter and lift a
      // 'blocked' status, otherwise the re-enqueued run hits the heal cap again
      // immediately and Retry looks like it did nothing.
      final state = store.readState(id);
      state['heal_attempts'] = 0;
      if (state['status'] == 'blocked') state['status'] = 'active';
      store.writeState(id, state);
      store.writeRunStatus(id, {
        'status': 'queued',
        'phase': phase,
        'queued_at': DateTime.now().toUtc().toIso8601String(),
        'error': null,
        'error_code': null,
      });
      final status = await runner.enqueue(id, phase: phase);
      return _json({
        'ok': true,
        'run_status': status,
        'feature': featureDetailPayload(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.get('/features/<id>/run-status', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      runner.reconcileStaleRunStatus(id);
      return _json({
        'feature_id': id,
        'run_status': store.readRunStatus(id),
        'phase_request': store.readPhaseRequest(id),
      });
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/features/<id>/cost', (Request request, String id) {
    try {
      if (!store.featureExists(id)) {
        return _json({'error': 'not found'}, status: 404);
      }
      return _json(costs.featureCost(id));
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  router.get('/cost/summary', (Request _) {
    try {
      return _json(costs.summary());
    } catch (e) {
      return _json({'error': e.toString()}, status: 500);
    }
  });

  Middleware timingMiddleware() => (Handler inner) => (Request req) async {
        final sw = Stopwatch()..start();
        final res = await inner(req);
        sw.stop();
        // Normalize ids out of the path so metrics group by route shape.
        final route = req.method +
            ' /' +
            req.url.pathSegments
                .map((s) => s == 'features' ||
                        s == 'runner' ||
                        s == 'commands' ||
                        s == 'autopilot' ||
                        s == 'health' ||
                        s == 'brain' ||
                        s == 'metrics' ||
                        s == 'approve' ||
                        s == 'sync-state' ||
                        s == 'conversation' ||
                        s == 'pipeline' ||
                        s == 'run-status' ||
                        s == 'studio-preview' ||
                        s == 'preview' ||
                        s == 'cost' ||
                        s == 'summary' ||
                        s == 'audit-bundle'
                    ? s
                    : '{id}')
                .join('/');
        routeCounts[route] = (routeCounts[route] ?? 0) + 1;
        routeMicros[route] =
            (routeMicros[route] ?? 0) + sw.elapsedMicroseconds;
        return res;
      };

  final handler = Pipeline()
      .addMiddleware(_corsMiddleware())
      .addMiddleware(timingMiddleware())
      .addHandler((Request request) {
        final staticRes = previewService.serveStatic(request);
        if (staticRes != null) return staticRes;
        return router.call(request);
      });

  final server = await io.serve(handler, InternetAddress.loopbackIPv4, port);
  print('Orchestration API listening on:');
  print('  http://127.0.0.1:${server.port}');
  print('  http://localhost:${server.port}  (use this for web dashboard)');
}
