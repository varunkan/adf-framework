import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/conversation_builder.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:orchestration_server/pipeline_planner.dart';
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

  final store = FeatureStore(repoRoot);
  final runner = PhaseRunner(store);
  final artifactValidator = ArtifactValidator(repoRoot);
  final planner = PipelinePlanner(store);
  final conversation = ConversationBuilder(store);
  final postSync = RunPostSync(store);
  final autoRunner = Platform.environment['ORCH_AUTO_RUNNER'] != 'false';

  if (autoRunner) {
    runner.startBackgroundPoller();
  }

  final health = await runner.getHealth();
  print('Orchestration server repo root: $repoRoot');
  print('Auto phase runner: ${autoRunner ? 'on' : 'off'}');
  print('Runner ready: ${health['ready']} (${health['agent_path'] ?? 'no agent'})');

  Map<String, dynamic> featureDetailPayload(String id) {
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
    detail['conversation'] = conversation.build(id);
    return detail;
  }

  final router = Router();

  router.get('/health', (Request _) => _json({'status': 'ok', 'repo': repoRoot}));

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
      final list = ids.map(store.featureSummary).toList();
      return _json({
        'features': list,
        'count': list.length,
        'api': 'http://localhost:$port',
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
      return _json(detail);
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
      final messages = conversation.build(id, limit: limit);
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

      if (execute) {
        final state = store.readState(id);
        if (state['status'] == 'completed') {
          store.appendClientClarification(id, prompt.trim());
          return _json({
            'ok': true,
            'mode': 'feature_complete',
            'command': cmd,
            'message':
                'Feature is completed — notes saved to requirement.md only.',
            'feature': featureDetailPayload(id),
          });
        }

        final healthNow = await runner.getHealth(refresh: true);
        if (healthNow['ready'] != true) {
          return _json({
            'ok': false,
            'command': cmd,
            'run_status': store.readRunStatus(id),
            'runner_health': healthNow,
            'error': healthNow['hint'],
          }, status: 409);
        }
        if (healthNow['headless_ready'] != true) {
          final result = await runner.enqueueCommand(
            id,
            prompt: prompt.trim(),
            stepId: stepId,
            commandId: cmd['id'] as String,
          );
          return _json({
            'ok': true,
            'mode': result['mode'] ?? 'ide_only',
            'command': cmd,
            'result': result,
            'feature': featureDetailPayload(id),
          });
        }
        final result = await runner.enqueueCommand(
          id,
          prompt: prompt.trim(),
          stepId: stepId,
          commandId: cmd['id'] as String,
        );
        final fd = featureDetailPayload(id);
        return _json({
          'ok': result['success'] == true,
          'command': cmd,
          'result': result,
          'feature': fd,
        });
      }

      return _json({'ok': true, 'command': cmd});
    } catch (e) {
      return _json({'error': e.toString()}, status: 400);
    }
  });

  router.post('/features', (Request request) async {
    try {
      final body =
          jsonDecode(await request.readAsString()) as Map<String, dynamic>;
      final id = body['id'] as String?;
      final requirement = body['requirement'] as String? ?? '';
      final track = body['track'] as String? ?? 'M';
      if (id == null || id.isEmpty) {
        return _json({'error': 'id required'}, status: 400);
      }
      store.createFeature(id: id, requirement: requirement, track: track);
      final payload = featureDetailPayload(id);
      if (autoRunner) {
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

  final handler = Pipeline()
      .addMiddleware(_corsMiddleware())
      .addMiddleware(logRequests())
      .addHandler(router.call);

  final server = await io.serve(handler, InternetAddress.loopbackIPv4, port);
  print('Orchestration API listening on:');
  print('  http://127.0.0.1:${server.port}');
  print('  http://localhost:${server.port}  (use this for web dashboard)');
}
