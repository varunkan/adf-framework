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
      expect(RequirementsCrewRunner.isEnabled({'ADF_REQUIREMENTS_CREW': '0'}), isFalse);
      // CREW-1: the crew is now the DEFAULT (on for M/L/XL) — was opt-in/off.
      // Track-aware defaults are covered in crew_default_test.dart.
      expect(RequirementsCrewRunner.isEnabled({}), isTrue);
    });

    test('scriptPath honors the override seam (P5 server E2E)', () {
      expect(RequirementsCrewRunner.scriptPath({}),
          'scripts/orch/requirements_crew.py');
      expect(
          RequirementsCrewRunner.scriptPath(
              {'ADF_REQUIREMENTS_CREW_SCRIPT': '/tmp/stub.py'}),
          '/tmp/stub.py');
    });

    test('invokes the crew CLI and reports success when a real verdict lands', () async {
      late List<String> gotArgs;
      final runner = RequirementsCrewRunner(store,
          run: (exe, args, cwd, {Map<String, String>? environment}) async {
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
      final runner = RequirementsCrewRunner(store,
          run: (e, a, c, {Map<String, String>? environment}) async {
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
      final runner = RequirementsCrewRunner(store,
          run: (e, a, c, {Map<String, String>? environment}) async {
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
      File(runner_verdict(store, 'feat-s2'))
        ..createSync(recursive: true)
        ..writeAsStringSync('# PO verdict (phase 2): REVISE');
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
          run: (e, a, c, {Map<String, String>? environment}) async =>
              ProcessResult(0, 1, '', 'boom'));
      expect(await r1.run('feat-2'), isFalse);
      // exit 0 but no verdict written
      final r2 = RequirementsCrewRunner(store,
          run: (e, a, c, {Map<String, String>? environment}) async =>
              ProcessResult(0, 0, '{}', ''));
      expect(await r2.run('feat-3'), isFalse);
      // process throws (python missing) → false, not an exception
      final r3 = RequirementsCrewRunner(store,
          run: (e, a, c, {Map<String, String>? environment}) async =>
              throw const ProcessException('python3', []));
      expect(await r3.run('feat-4'), isFalse);
    });

    // ---- G13: content validation (empty/garbage verdict must not fake a pass) ----

    test('NEVER fakes a pass: exit 0 + empty verdict file → false', () async {
      final runner = RequirementsCrewRunner(store,
          run: (e, a, c, {Map<String, String>? environment}) async {
        File(runner_verdict(store, 'feat-empty'))
          ..createSync(recursive: true)
          ..writeAsStringSync('');
        return ProcessResult(0, 0, '{}', '');
      });
      expect(await runner.run('feat-empty'), isFalse);
    });

    test('NEVER fakes a pass: exit 0 + garbage verdict (no token) → false',
        () async {
      final runner = RequirementsCrewRunner(store,
          run: (e, a, c, {Map<String, String>? environment}) async {
        File(runner_verdict(store, 'feat-garbage'))
          ..createSync(recursive: true)
          ..writeAsStringSync('lorem ipsum no verdict here\nsome error output\n');
        return ProcessResult(0, 0, '{}', '');
      });
      expect(await runner.run('feat-garbage'), isFalse);
    });

    // ---- G01: non-.cursor layout — runner forwards resolved orchestration root ----

    test(
        'non-.cursor layout: successful crew run must NOT produce phantom gate '
        'failure (forwards ORCH_ORCHESTRATION_DIR)', () async {
      // Configure a non-.cursor layout via an install manifest pointing at
      // .adf/orchestration, then re-resolve the store's paths.
      Directory('${repo.path}/.adf/orchestration').createSync(recursive: true);
      File('${repo.path}/.adf-install.json')
          .writeAsStringSync('{"orchestration_dir": ".adf/orchestration"}');
      store = FeatureStore(repo.path);
      expect(store.paths.orchestrationRoot, endsWith('.adf/orchestration'));

      Map<String, String>? capturedEnv;
      final runner = RequirementsCrewRunner(store,
          run: (exe, args, cwd, {Map<String, String>? environment}) async {
        capturedEnv = environment;
        // Faithful stub: write the verdict to wherever the env says to.
        final envOrchDir = environment?['ORCH_ORCHESTRATION_DIR'] ??
            '${repo.path}/.adf/orchestration';
        File('$envOrchDir/features/feat-x/judge-verdicts/phase-2.md')
          ..createSync(recursive: true)
          ..writeAsStringSync('# PO verdict (phase 2): PASS');
        return ProcessResult(0, 0, '{}', '');
      });

      expect(await runner.run('feat-x'), isTrue);
      expect(capturedEnv,
          containsPair('ORCH_ORCHESTRATION_DIR', store.paths.orchestrationRoot));
    });
  });
}

String runner_verdict(FeatureStore store, String fid) =>
    '${store.repoRoot}/${store.paths.featureRel(fid, 'judge-verdicts/phase-2.md')}';
