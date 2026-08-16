import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/agent_crew.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:orchestration_server/orchestration_paths.dart';
import 'package:orchestration_server/requirements_crew_runner.dart';
import 'package:orchestration_server/trace_writer.dart';
import 'package:test/test.dart';

/// The crew must NARRATE itself live (no ~14s dead-air): it should emit trace
/// spans as each wave starts and each subagent completes, so the dashboard's
/// live-trace stream has something to show during the run.
void main() {
  late String repoRoot;
  late FeatureStore store;
  late Directory tempLearnings;
  late Directory traceDir;
  const id = 'agent-crew-trace-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    tempLearnings = Directory.systemTemp.createTempSync('adf-crew-trace');
    // Isolate trace output to a temp tree so we never touch the real repo log.
    traceDir = Directory.systemTemp.createTempSync('adf-trace');
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Render the checkout screen. Print a receipt. '
            'Email the receipt to the customer.',
        track: 'M',
      );
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
    tempLearnings.deleteSync(recursive: true);
    traceDir.deleteSync(recursive: true);
  });

  test('crew emits wave_start and one agent_done span per subagent', () async {
    final traces = TraceWriter(traceDir.path);
    final crew = AgentCrew(
      store,
      DeterministicArtifactEngine(store, brain: DeterministicBrain()),
      ArtifactValidator(repoRoot),
      LearningStore(tempLearnings.path),
      traces: traces,
      env: const {'ADF_REQUIREMENTS_CREW': '0'}, // CREW-1: deterministic narration suite
    );
    await crew.run(id);

    final file = File(OrchestrationPaths(traceDir.path).otelTracesFile);
    expect(file.existsSync(), isTrue, reason: 'crew must write live trace spans');
    final names = file
        .readAsLinesSync()
        .where((l) => l.trim().isNotEmpty)
        .map((l) => (jsonDecode(l) as Map<String, dynamic>)['name'])
        .toList();

    expect(names, contains('crew.wave_start'));
    expect(
      names.where((n) => n == 'crew.agent_done').length,
      6,
      reason: 'one agent_done span per subagent (phases 1-6)',
    );
  });

  // ── G06: phase-2 spec provenance (crew vs deterministic_fallback vs deterministic) ──
  //
  // When the requirements crew is enabled but RequirementsCrewRunner.run()
  // returns false on a NON-timeout failure, the old _specPhase silently fell
  // back to the deterministic engine with zero trace — a sealed template spec
  // was indistinguishable from a research-grounded one. These tests assert the
  // additive provenance fix: a `spec_source` state flag on every path and a
  // crew-log `deterministic_fallback` entry on the silent-failure path.

  // Crew is enabled via an INJECTED env so we never mutate the process env;
  // _specPhase keys its enabled-decision off the same map.
  AgentCrew crewWith({
    Map<String, String>? env,
    RequirementsCrewRunner Function(FeatureStore)? runnerFactory,
  }) =>
      AgentCrew(
        store,
        DeterministicArtifactEngine(store, brain: DeterministicBrain()),
        ArtifactValidator(repoRoot),
        LearningStore(tempLearnings.path),
        env: env,
        requirementsRunnerFactory: runnerFactory,
      );

  List<Map<String, dynamic>> crewLog(String id) =>
      File('${store.featurePath(id)}/crew-log.jsonl')
          .readAsLinesSync()
          .where((l) => l.trim().isNotEmpty)
          .map((l) => jsonDecode(l) as Map<String, dynamic>)
          .toList();

  String verdictFor(String fid) =>
      '${store.repoRoot}/${store.paths.featureRel(fid, 'judge-verdicts/phase-2.md')}';

  test('crew-disabled run records spec_source=deterministic (no fallback)',
      () async {
    await crewWith(env: const {'ADF_REQUIREMENTS_CREW': '0'}).run(id);

    expect(store.readState(id)['spec_source'], 'deterministic');
    expect(
      crewLog(id).where((e) => e['status'] == 'deterministic_fallback'),
      isEmpty,
      reason: 'the disabled path must not write a fallback log entry',
    );
    // Provenance is additive; the disabled path still logs exactly 6 agents.
    expect(crewLog(id).length, 6);
  });

  test(
      'crew-enabled failing run records spec_source=deterministic_fallback and logs it',
      () async {
    // Runner exits 1 and writes no verdict → run() == false on the NON-timeout
    // path (the silent gap G06 fixes).
    final summary = await crewWith(
      env: const {'ADF_REQUIREMENTS_CREW': '1'},
      runnerFactory: (s) => RequirementsCrewRunner(
        s,
        run: (String exe, List<String> args, String cwd,
                {Map<String, String>? environment}) async =>
            ProcessResult(0, 1, '', ''),
      ),
    ).run(id);

    expect(store.readState(id)['spec_source'], 'deterministic_fallback');
    final fallbacks =
        crewLog(id).where((e) => e['status'] == 'deterministic_fallback').toList();
    expect(fallbacks.length, 1,
        reason: 'exactly one fallback audit line on the silent-failure path');
    expect(fallbacks.first['phase'], 2);
    // The audit trail names the spec-writer agent and a reason.
    expect(fallbacks.first['agent'], 'spec-writer');
    expect(fallbacks.first['reason'], isNotNull);
    // 6 agent 'ok' lines + 1 'deterministic_fallback' line.
    expect(crewLog(id).length, 7);
    // Never-block is preserved: all six phases still complete.
    expect(summary['phases_completed'], [1, 2, 3, 4, 5, 6]);
    // G1: this is a track-M feature, so the crew HOLDS for spec approval rather
    // than handing off to implementation (was 'implementation_handoff').
    expect(summary['stop_reason'], 'awaiting_approval');
  });

  test('crew-enabled successful run records spec_source=crew', () async {
    final summary = await crewWith(
      env: const {'ADF_REQUIREMENTS_CREW': '1'},
      runnerFactory: (s) => RequirementsCrewRunner(
        s,
        run: (String exe, List<String> args, String cwd,
            {Map<String, String>? environment}) async {
          // Write a real verdict (with a recognizable PASS token) where the gate
          // reads it so run() == true (RequirementsCrewRunner validates content).
          final f = File(verdictFor(id));
          f.parent.createSync(recursive: true);
          f.writeAsStringSync('# PO verdict (phase 2): PASS\n');
          return ProcessResult(0, 0, '', '');
        },
      ),
    ).run(id);

    expect(store.readState(id)['spec_source'], 'crew');
    expect(
      crewLog(id).where((e) => e['status'] == 'deterministic_fallback'),
      isEmpty,
      reason: 'a real crew success is NOT a fallback',
    );
    // NOTE: phases_completed is intentionally NOT asserted here. The stubbed
    // runner writes only a verdict token (not the full research-grounded spec
    // artifacts the real Python crew produces), so the phase-2 validator gate
    // legitimately stops the run. spec_source=='crew' is the provenance claim
    // under test; gate behaviour is exercised by the deterministic-path tests.
    expect(summary['feature_id'], id);
  });
}
