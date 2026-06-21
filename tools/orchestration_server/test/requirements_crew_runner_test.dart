import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/requirements_crew_runner.dart';
import 'package:test/test.dart';

void main() {
  group('RequirementsCrewRunner (P2)', () {
    late Directory repo;
    late FeatureStore store;
    setUp(() {
      repo = Directory.systemTemp.createTempSync('crew-runner');
      store = FeatureStore(repo.path);
    });
    tearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);

    test('isEnabled reads the ADF_REQUIREMENTS_CREW flag', () {
      expect(RequirementsCrewRunner.isEnabled({'ADF_REQUIREMENTS_CREW': '1'}), isTrue);
      expect(RequirementsCrewRunner.isEnabled({}), isFalse);
    });

    test('invokes the crew CLI and reports success when a real verdict lands', () async {
      late List<String> gotArgs;
      final runner = RequirementsCrewRunner(store, run: (exe, args, cwd) async {
        gotArgs = args;
        expect(exe, 'python3');
        expect(cwd, repo.path);
        // simulate the crew writing the real phase-2 verdict
        File(runner_verdict(store, 'feat-1'))
          ..createSync(recursive: true)
          ..writeAsStringSync('Verdict: REVISE\nReviewer skills: bmad-po');
        return ProcessResult(0, 0, '{"po_pass": false}', '');
      });
      expect(await runner.run('feat-1'), isTrue);
      expect(gotArgs, containsAll(['scripts/orch/requirements_crew.py', 'feat-1']));
    });

    test('lifts the crew open-questions into state for the user (P3)', () async {
      store.writeState('feat-q', {'current_phase': 2}, skipRepair: true);
      final runner = RequirementsCrewRunner(store, run: (e, a, c) async {
        File(runner_verdict(store, 'feat-q'))
          ..createSync(recursive: true)
          ..writeAsStringSync('# PO verdict (phase 2): REVISE');
        return ProcessResult(0, 0,
            '{"po_pass": false, "questions": '
            '["Which eCTD modules: 1 or 1-5?", "Single tenant?"]}',
            '');
      });
      expect(await runner.run('feat-q'), isTrue);
      final state = store.readState('feat-q');
      expect(state['requirements_open_questions'],
          ['Which eCTD modules: 1 or 1-5?', 'Single tenant?']);
      // …and the feature-detail payload surfaces them to the dashboard.
      expect(store.featureSummary('feat-q')['requirements_open_questions'],
          ['Which eCTD modules: 1 or 1-5?', 'Single tenant?']);
    });

    test('passes --sources to the crew when a sources file exists (P4)', () async {
      late List<String> gotArgs;
      final runner = RequirementsCrewRunner(store, run: (e, a, c) async {
        gotArgs = a;
        File(runner_verdict(store, 'feat-s'))
          ..createSync(recursive: true)
          ..writeAsStringSync('# PO verdict (phase 2): REVISE');
        return ProcessResult(0, 0, '{}', '');
      });
      // no sources file → no --sources
      await runner.run('feat-s');
      expect(gotArgs.contains('--sources'), isFalse);
      // write a sources file → --sources <path> is passed
      File(runner.sourcesPath('feat-s2'))
        ..createSync(recursive: true)
        ..writeAsStringSync('[{"url":"https://x/ref"}]');
      File(runner_verdict(store, 'feat-s2')).createSync(recursive: true);
      await runner.run('feat-s2');
      expect(gotArgs, containsAllInOrder(['--sources', runner.sourcesPath('feat-s2')]));
    });

    test('store.writeSources writes exactly where the runner reads (P4)', () {
      store.writeSources('feat-w', [
        {'url': 'https://x/ref'},
        {'path': '/docs/spec.pdf'}
      ]);
      final f = File(RequirementsCrewRunner(store).sourcesPath('feat-w'));
      expect(f.existsSync(), isTrue);
      expect(jsonDecode(f.readAsStringSync()), [
        {'url': 'https://x/ref'},
        {'path': '/docs/spec.pdf'}
      ]);
    });

    test('NEVER fakes a pass: exit!=0 or no verdict file → false', () async {
      // non-zero exit
      final r1 = RequirementsCrewRunner(store,
          run: (e, a, c) async => ProcessResult(0, 1, '', 'boom'));
      expect(await r1.run('feat-2'), isFalse);
      // exit 0 but no verdict written
      final r2 = RequirementsCrewRunner(store,
          run: (e, a, c) async => ProcessResult(0, 0, '{}', ''));
      expect(await r2.run('feat-3'), isFalse);
      // process throws (python missing) → false, not an exception
      final r3 = RequirementsCrewRunner(store,
          run: (e, a, c) async => throw const ProcessException('python3', []));
      expect(await r3.run('feat-4'), isFalse);
    });
  });
}

String runner_verdict(FeatureStore store, String fid) =>
    '${store.repoRoot}/${store.paths.featureRel(fid, 'judge-verdicts/phase-2.md')}';
