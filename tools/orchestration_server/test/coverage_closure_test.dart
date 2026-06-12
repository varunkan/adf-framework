import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/autopilot.dart';
import 'package:orchestration_server/conversation_builder.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:orchestration_server/orch_env_loader.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:orchestration_server/run_post_sync.dart';
import 'package:orchestration_server/trace_writer.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  const id = 'coverage-closure-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Coverage closure. Validate every helper.',
        track: 'S',
      );
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
  });

  group('TraceWriter', () {
    test('appends otel spans to global and feature trace files', () {
      final writer = TraceWriter(repoRoot);
      writer.append(
        featureId: id,
        name: 'runner.test',
        event: 'runner',
        phase: 2,
        message: 'unit test span',
        reasoning: 'because coverage',
        extra: {'custom': true},
      );
      final featureFile =
          File(store.paths.featureOtelTracesFile(id));
      expect(featureFile.existsSync(), isTrue);
      final line = featureFile.readAsLinesSync().last;
      expect(line, contains('runner.test'));
      expect(line, contains('unit test span'));
      expect(line, contains('agent.reasoning'));
    });
  });

  group('RunPostSync', () {
    test('verdict file flips state to awaiting approval', () {
      final verdict = File(
          '$repoRoot/${store.paths.featureRel(id, 'judge-verdicts/phase-2.md')}');
      verdict.parent.createSync(recursive: true);
      verdict.writeAsStringSync(
          '# Verdict\n\n**Verdict:** PASS\n\n**Reviewers:** bmad-agent-qa, bmad-agent-dev\n\n## Combined recommendation\n\nShip it.\n');

      final awaiting = RunPostSync(store).syncAfterRun(id, 2);
      expect(awaiting, isTrue);
      final state = store.readState(id);
      expect(state['last_judge_verdict'], 'pass');
      expect(state['pending_approval_phase'], 2);
      expect(store.readLastAgentResponse(id), contains('Ship it'));
    });

    test('intake artifact backfills phase 1 builders', () {
      final intake =
          File('$repoRoot/${store.paths.featureRel(id, '00-intake.md')}');
      intake.parent.createSync(recursive: true);
      intake.writeAsStringSync('# Intake\n\nProblem framing.');

      RunPostSync(store).syncAfterRun(id, 1);
      final state = store.readState(id);
      final builders = state['completed_builders'] as Map<String, dynamic>;
      expect(builders['1'], contains('orch-product-analyst'));
      expect(store.readLastAgentResponse(id), contains('Problem framing'));
    });
  });

  group('orch env loader', () {
    test('parses env files without clobbering existing values', () {
      final temp = Directory.systemTemp.createTempSync('adf-env');
      File('${temp.path}/.env').writeAsStringSync(
        '# comment line\n'
        '\n'
        'NOT_RELEVANT=skipme\n'
        'BROKENLINE\n'
        '=novalue\n'
        'PATH="should-not-clobber"\n',
      );
      expect(() => loadOrchLlmEnvFiles(temp.path), returnsNormally);
      expect(Platform.environment['PATH'], isNot('should-not-clobber'));
      temp.deleteSync(recursive: true);
      expect(orchLlmConfigured(), isA<bool>());
    });
  });

  group('FeatureStore parsing helpers', () {
    test('parseJudgeVerdict extracts pass/revise/fail', () {
      expect(store.parseJudgeVerdict('**Verdict:** PASS'), 'pass');
      expect(store.parseJudgeVerdict('**verdict:** revise — needs work'),
          'revise');
      expect(store.parseReviewerSkills('**Reviewers:** a-skill, b-skill'),
          ['a-skill', 'b-skill']);
      expect(store.parseJudgeVerdict('no verdict here'), isNull);
      expect(store.parseJudgeVerdict(null), isNull);
    });

    test('parseCombinedRecommendation pulls section body', () {
      final md = '# V\n\n## Combined recommendation\n\nDo the thing.\n\n## Next\n\nx';
      expect(store.parseCombinedRecommendation(md), contains('Do the thing'));
      expect(store.parseCombinedRecommendation('plain'), isNull);
    });

    test('featureSummary and featureDetail expose pipeline state', () {
      final summary = store.featureSummary(id);
      expect(summary['id'], id);
      expect(summary['current_phase'], isA<int>());

      final detail = store.featureDetail(id);
      expect(detail['summary'], isNotNull);
      expect(detail['state'], isNotNull);
    });

    test('last agent response round-trips', () {
      store.writeLastAgentResponse(id, 'agent says hi');
      expect(store.readLastAgentResponse(id), 'agent says hi');
    });
  });

  group('ConversationBuilder.build', () {
    test('includes commands and run-log events in full view', () {
      store.appendCommand(id, prompt: 'hello there', execute: false);
      final runLog = File('${store.featurePath(id)}/run-log.jsonl');
      runLog.writeAsStringSync(
        '{"ts":"2026-06-11T00:00:00Z","event":"phase_start","phase":1,'
        '"message":"Phase 1 started"}\n',
        mode: FileMode.append,
      );
      final conv = ConversationBuilder(store).build(id);
      expect(conv, isNotEmpty);
      expect(
        conv.any((m) => (m['text'] as String? ?? '').contains('hello there')),
        isTrue,
      );
    });
  });

  group('PhaseRunner reconcile', () {
    test('clears phantom running status with no live process', () {
      final runner = PhaseRunner(store);
      store.writeRunStatus(id, {
        'status': 'running',
        'agent_active': true,
        'started_at':
            DateTime.now().toUtc().subtract(const Duration(minutes: 5)).toIso8601String(),
      });
      runner.reconcileStaleRunStatus(id);
      final run = store.readRunStatus(id);
      expect(run?['status'], anyOf('idle', 'awaiting_approval'));
      expect(run?['agent_active'], isNot(true));
    });

    test('times out runs older than the max duration', () {
      final runner = PhaseRunner(store);
      store.writeRunStatus(id, {
        'status': 'running',
        'agent_active': true,
        'started_at': DateTime.now()
            .toUtc()
            .subtract(const Duration(hours: 5))
            .toIso8601String(),
      });
      runner.reconcileStaleRunStatus(id);
      final run = store.readRunStatus(id);
      expect(run?['agent_active'], isNot(true));
    });
  });

  group('Autopilot bounds', () {
    test('maxPhase stops the run early', () async {
      final autopilot = Autopilot(
        store,
        DeterministicArtifactEngine(store, brain: DeterministicBrain()),
        ArtifactValidator(repoRoot),
        LearningStore(Directory.systemTemp.createTempSync('adf-l').path),
      );
      final summary = await autopilot.run(id, maxPhase: 2);
      expect(summary['phases_completed'], [1, 2]);
      expect(summary['stop_reason'], 'max_phase_reached');
    });
  });

  group('OllamaBrain offline behavior', () {
    test('unreachable host yields null completion and not-available', () async {
      final brain = OllamaBrain(host: 'http://127.0.0.1:1', model: 'm');
      expect(brain.billsTokens, isFalse);
      expect(brain.name, 'ollama:m');
      expect(await brain.available(), isFalse);
      expect(await brain.complete(system: 's', user: 'u'), isNull);
    });
  });
}
