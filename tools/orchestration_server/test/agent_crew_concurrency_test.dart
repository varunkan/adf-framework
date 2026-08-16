import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/agent_crew.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/integrity_chain.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:test/test.dart';

// CrewGate is the extracted single-flight guard from bin/server.dart's
// runCrewForFeature. Imported via relative path because server.dart is a bin
// entry-point (not a lib library) and the gate has no other importable home.
import '../bin/server.dart';

// SCOPE (honesty): this file tests the CrewGate PRIMITIVE and the shared-ledger
// race it guards, NOT the production wiring. The tests below construct CrewGate
// directly and (for the AC-1/AC-2 cases) drive a LOCAL `guardedRun()` closure
// that mirrors runCrewForFeature's gate usage. Deleting `crewGate.tryAcquire`
// from the real runCrewForFeature in bin/server.dart would NOT fail this file —
// it proves the primitive is correct and that the unguarded race really
// corrupts the ledger, not that the server seam actually calls the gate. The
// PRODUCTION-SEAM teeth (that runCrewForFeature/the autopilot route and the
// create-time auto-kick actually invoke the gate) live in
// server_autopilot_guard_test.dart, whose 409 / no-duplicate-build assertions
// fail when crewGate.tryAcquire is removed from runCrewForFeature
// (mutation-verified). Read the two files together.
void main() {
  group('G05 — concurrent crew runs over a shared ledger', () {
    late String repoRoot;
    late FeatureStore store;
    late Directory tempLearnings;
    const id = 'g05-concurrency-test';

    setUp(() {
      repoRoot = Directory.current.path;
      while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
        final parent = Directory(repoRoot).parent;
        if (parent.path == repoRoot) throw StateError('repo root not found');
        repoRoot = parent.path;
      }
      store = FeatureStore(repoRoot);
      tempLearnings = Directory.systemTemp.createTempSync('adf-g05');
      if (store.featureExists(id)) {
        Directory(store.featurePath(id)).deleteSync(recursive: true);
      }
      store.createFeature(
        id: id,
        requirement: 'Render the checkout screen. Print a receipt. '
            'Email the receipt to the customer.',
        track: 'M',
      );
    });

    tearDown(() {
      if (store.featureExists(id)) {
        Directory(store.featurePath(id)).deleteSync(recursive: true);
      }
      final specDir = Directory('$repoRoot/specs/$id');
      if (specDir.existsSync()) specDir.deleteSync(recursive: true);
      tempLearnings.deleteSync(recursive: true);
    });

    AgentCrew buildCrew(IntegrityChain integrity) => AgentCrew(
          store,
          DeterministicArtifactEngine(store, brain: DeterministicBrain()),
          ArtifactValidator(repoRoot),
          LearningStore(tempLearnings.path),
          integrity: integrity,
          env: const {'ADF_REQUIREMENTS_CREW': '0'}, // CREW-1: deterministic suite
        );

    Map<int, int> phaseSealCounts(IntegrityChain integrity) {
      final ledger = File(integrity.ledgerPath(id));
      if (!ledger.existsSync()) return {};
      final byPhase = <int, int>{};
      for (final line in ledger.readAsLinesSync()) {
        if (line.trim().isEmpty) continue;
        final block = jsonDecode(line) as Map<String, dynamic>;
        final phase = block['phase'];
        if (phase is int) byPhase[phase] = (byPhase[phase] ?? 0) + 1;
      }
      return byPhase;
    }

    // RED reproduction (AC-1): UNGUARDED concurrent crews over the SAME
    // IntegrityChain double-seal phases into the shared on-disk ledger. This
    // documents the bug the gate exists to prevent — at least one phase is sealed
    // more than once.
    test('UNGUARDED concurrent same-id runs double-seal the shared ledger (bug)',
        () async {
      final integrity = IntegrityChain(store);
      await Future.wait([
        buildCrew(integrity).run(id),
        buildCrew(integrity).run(id),
      ]);
      final byPhase = phaseSealCounts(integrity);
      final duplicated =
          byPhase.entries.where((e) => e.value > 1).map((e) => e.key).toList();
      expect(duplicated, isNotEmpty,
          reason: 'unguarded concurrency must produce a duplicate phase seal '
              'to justify the gate');
    });

    // GREEN (AC-1 + AC-2 at the PRIMITIVE level): a CrewGate fronting two same-id
    // runs admits exactly one, so each phase is sealed at most once even under a
    // concurrent double-trigger (AC-1), AND state.json's completed_builders/gates
    // reflect a single coherent run with no last-write-wins interleaving (AC-2,
    // asserted below). NOTE: the guardedRun() closure below is a LOCAL stand-in
    // for runCrewForFeature — it proves the gate primitive serializes correctly,
    // not that the production seam calls the gate. The seam-level teeth for AC-1/
    // AC-2 (and AC-6/AC-7) are in server_autopilot_guard_test.dart.
    test('CrewGate serializes same-id runs so each phase seals at most once',
        () async {
      final integrity = IntegrityChain(store);
      final gate = CrewGate();

      // LOCAL stand-in for runCrewForFeature (see note above): mirrors the gate
      // usage but is NOT the production seam.
      Future<Map<String, dynamic>> guardedRun() async {
        if (!gate.tryAcquire(id)) {
          return {'skipped': true, 'reason': 'crew_already_in_flight'};
        }
        try {
          return await buildCrew(integrity).run(id);
        } finally {
          gate.release(id);
        }
      }

      await Future.wait([guardedRun(), guardedRun()]);

      final byPhase = phaseSealCounts(integrity);
      expect(byPhase, isNotEmpty, reason: 'one run must still seal phases');
      for (final entry in byPhase.entries) {
        expect(entry.value, lessThanOrEqualTo(1),
            reason: 'phase ${entry.key} sealed ${entry.value}x — '
                'concurrent duplicate seal');
      }

      // AC-2: state.json reflects a SINGLE coherent run, not last-write-wins
      // interleaving. completed_builders maps each completed phase to exactly
      // one builder entry — ['adf-crew'] — with no duplicate/garbled list from a
      // second concurrent _advance read-modify-write.
      final state = store.readState(id);
      final completed =
          state['completed_builders'] as Map<String, dynamic>? ?? {};
      expect(completed, isNotEmpty,
          reason: 'the admitted run must record completed_builders');
      completed.forEach((phase, builders) {
        expect(builders, ['adf-crew'],
            reason: 'phase $phase completed_builders must be a single coherent '
                "['adf-crew'] entry, not an interleaved/duplicated list");
      });
      // Gates that the admitted run passed must be `true` (a single coherent
      // run), and the sealed phase count must not exceed the recorded phases.
      final gates = state['gates'] as Map<String, dynamic>? ?? {};
      expect(gates.values.where((v) => v == true), isNotEmpty,
          reason: 'the admitted run must advance at least one gate');
      expect(byPhase.length, lessThanOrEqualTo(completed.length + 1),
          reason: 'sealed phases must track the single run, not a doubled run');
    });

    // AC-3: exactly one run body executes when two same-id triggers race.
    test('CrewGate admits exactly one body for two concurrent same-id triggers',
        () {
      final gate = CrewGate();
      final first = gate.tryAcquire(id);
      final second = gate.tryAcquire(id);
      expect(first, isTrue);
      expect(second, isFalse, reason: 'second concurrent trigger rejected');
    });

    // AC-5: marker is released after a run throws — a follow-up run is permitted.
    test('CrewGate releases the marker after a throwing run', () async {
      final gate = CrewGate();
      try {
        if (!gate.tryAcquire(id)) fail('first acquire must succeed');
        try {
          throw StateError('boom');
        } finally {
          gate.release(id);
        }
      } catch (_) {/* expected */}
      expect(gate.tryAcquire(id), isTrue,
          reason: 'feature must not be permanently locked after a throw');
    });

    // AC-4: the guard is per-id, not global — different ids both proceed.
    test('CrewGate does not over-serialize across different featureIds', () {
      final gate = CrewGate();
      expect(gate.tryAcquire('feat-a'), isTrue);
      expect(gate.tryAcquire('feat-b'), isTrue,
          reason: 'a different featureId must not be blocked');
    });
  });
}
