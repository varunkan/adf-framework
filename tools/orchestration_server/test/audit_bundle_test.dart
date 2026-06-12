import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/audit_bundle.dart';
import 'package:orchestration_server/cost_meter.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/integrity_chain.dart';
import 'package:orchestration_server/runner_backend.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  late IntegrityChain chain;
  late CostMeter costs;
  late AuditBundleBuilder bundles;
  const id = 'audit-bundle-test';

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_audit_test_');
    store = FeatureStore(tmp.path);
    chain = IntegrityChain(store);
    costs = CostMeter(store, env: const {});
    bundles = AuditBundleBuilder(
      store,
      integrity: chain,
      costs: costs,
      backend: CursorBackend(),
    );
    store.createFeature(
      id: id,
      requirement: 'Export a bundle that proves what was built.',
      track: 'S',
    );
    File('${tmp.path}/specs/$id/spec.md')
        .writeAsStringSync('# Spec\n\nSealed proof artifact.\n');
    // Writing spec.md completes bootstrap, which makes the next readState
    // repair-and-rewrite state.json. Trigger that now so the state sealed
    // into the chain is stable (no drift between seal and export).
    store.readState(id);
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  // Recomputes the digest the same way the builder stamps it.
  String digestOf(Map<String, dynamic> bundle) {
    final body = Map<String, dynamic>.from(bundle)..remove('bundle_digest');
    return IntegrityChain.hashString(IntegrityChain.canonical(body));
  }

  Map<String, dynamic> sealedBundle() {
    costs.recordFromResultEvent(
      id,
      {
        'type': 'result',
        'total_cost_usd': 0.042,
        'usage': {'input_tokens': 1200, 'output_tokens': 350},
      },
      phase: 6,
    );
    chain.seal(id, phase: 1);
    return bundles.build(id);
  }

  test('sealed feature exports the full contract payload', () {
    final bundle = sealedBundle();

    expect(bundle['format'], 'adf-audit-bundle/1');
    expect(bundle['feature_id'], id);
    expect(DateTime.tryParse(bundle['created_at'] as String), isNotNull);

    final runner = bundle['runner'] as Map<String, dynamic>;
    expect(runner['runner'], 'cursor');
    expect(runner['runner_label'], 'Cursor CLI (cursor-agent)');

    final blocks = (bundle['chain'] as List).cast<Map<String, dynamic>>();
    expect(blocks, hasLength(1));
    expect(blocks.first['prev_hash'], 'genesis');

    // Artifacts are lifted from the sealed manifest (never re-hashed),
    // sorted by path, with on-disk sizes attached.
    final manifest = (blocks.last['manifest'] as Map).cast<String, String>();
    final artifacts = (bundle['artifacts'] as List).cast<Map<String, dynamic>>();
    expect(
      artifacts.map((a) => a['path']),
      orderedEquals(manifest.keys.toList()..sort()),
    );
    expect(artifacts.map((a) => a['path']), contains('specs/$id/spec.md'));
    for (final artifact in artifacts) {
      expect(artifact['sha256'], manifest[artifact['path']]);
      expect(artifact['bytes'], greaterThan(0));
    }

    final gates = bundle['gates'] as Map<String, dynamic>;
    expect(gates, isNotEmpty);

    final cost = bundle['cost'] as Map<String, dynamic>;
    expect(cost['feature_id'], id);
    expect(cost['total_usd'], closeTo(0.042, 1e-9));

    expect(bundle['bundle_digest'], hasLength(64));
    expect(bundle['bundle_digest'], digestOf(bundle));
  });

  test('never-sealed feature exports chain: null and still gets a digest', () {
    final bundle = bundles.build(id);
    expect(bundle['chain'], isNull);
    expect(bundle['artifacts'], isEmpty);
    expect(bundle['cost'], isNull); // no cost evidence recorded
    expect(bundle['bundle_digest'], hasLength(64));
    expect(bundle['bundle_digest'], digestOf(bundle));
  });

  test('tampering one byte breaks the digest; a clean round-trip keeps it',
      () {
    final bundle = sealedBundle();

    // JSON round-trip (what export to disk does) must preserve the digest.
    final roundTrip = jsonDecode(jsonEncode(bundle)) as Map<String, dynamic>;
    expect(digestOf(roundTrip), bundle['bundle_digest']);

    // One flipped gate bit and the digest no longer matches.
    final tampered = jsonDecode(jsonEncode(bundle)) as Map<String, dynamic>;
    (tampered['gates'] as Map<String, dynamic>)['tests_green'] = true;
    expect(digestOf(tampered), isNot(bundle['bundle_digest']));
  });

  group('python3 verifier interop', () {
    late String script;
    String? python;

    setUpAll(() async {
      var dir = Directory.current.absolute.path;
      while (!File('$dir/scripts/orch/verify_audit_bundle.py').existsSync()) {
        final parent = Directory(dir).parent.path;
        if (parent == dir) {
          throw StateError('verify_audit_bundle.py not found above $dir');
        }
        dir = parent;
      }
      script = '$dir/scripts/orch/verify_audit_bundle.py';
      try {
        final probe = await Process.run('python3', ['--version']);
        if (probe.exitCode == 0) python = 'python3';
      } on ProcessException {
        python = null;
      }
    });

    File writeBundle(Map<String, dynamic> bundle) =>
        File('${tmp.path}/bundle.json')..writeAsStringSync(jsonEncode(bundle));

    test('accepts a genuine bundle, including --repo re-hash (exit 0)',
        () async {
      if (python == null) {
        markTestSkipped('python3 not on PATH — skipping verifier interop');
        return;
      }
      final file = writeBundle(sealedBundle());
      final result = await Process.run(
        python!,
        [script, '--json', '--repo', tmp.path, file.path],
      );
      expect(result.exitCode, 0,
          reason: '${result.stdout}\n${result.stderr}');
      final report =
          jsonDecode(result.stdout as String) as Map<String, dynamic>;
      expect(report['valid'], isTrue);
      expect(report['feature_id'], id);
      expect(
        (report['checks'] as List).map((c) => c['ok']),
        everyElement(isTrue),
      );
    });

    test('rejects a bundle tampered by one byte (exit 1)', () async {
      if (python == null) {
        markTestSkipped('python3 not on PATH — skipping verifier interop');
        return;
      }
      final file = writeBundle(sealedBundle());
      file.writeAsStringSync(file.readAsStringSync().replaceFirst(
            '"feature_id":"$id"',
            '"feature_id":"${id.substring(0, id.length - 1)}x"',
          ));
      final result =
          await Process.run(python!, [script, '--json', file.path]);
      expect(result.exitCode, 1,
          reason: '${result.stdout}\n${result.stderr}');
      final report =
          jsonDecode(result.stdout as String) as Map<String, dynamic>;
      expect(report['valid'], isFalse);
    });

    test('rejects a rewritten chain block even with a fixed-up digest',
        () async {
      if (python == null) {
        markTestSkipped('python3 not on PATH — skipping verifier interop');
        return;
      }
      final bundle =
          jsonDecode(jsonEncode(sealedBundle())) as Map<String, dynamic>;
      ((bundle['chain'] as List).first as Map<String, dynamic>)['actor'] =
          'attacker';
      bundle['bundle_digest'] = digestOf(bundle); // digest passes, links fail
      final result =
          await Process.run(python!, [script, '--json', writeBundle(bundle).path]);
      expect(result.exitCode, 1,
          reason: '${result.stdout}\n${result.stderr}');
      final report =
          jsonDecode(result.stdout as String) as Map<String, dynamic>;
      final failing = (report['checks'] as List)
          .where((c) => c['ok'] != true)
          .map((c) => c['check']);
      expect(failing, ['chain_links']);
    });

    test('flags artifact drift in a checkout via --repo (exit 1)', () async {
      if (python == null) {
        markTestSkipped('python3 not on PATH — skipping verifier interop');
        return;
      }
      final file = writeBundle(sealedBundle());
      File('${tmp.path}/specs/$id/spec.md')
          .writeAsStringSync('drifted after sealing');
      final result = await Process.run(
        python!,
        [script, '--json', '--repo', tmp.path, file.path],
      );
      expect(result.exitCode, 1,
          reason: '${result.stdout}\n${result.stderr}');
      final report =
          jsonDecode(result.stdout as String) as Map<String, dynamic>;
      final failing = (report['checks'] as List)
          .where((c) => c['ok'] != true)
          .map((c) => c['check']);
      expect(failing, ['repo_artifacts']);
    });

    test('self-test guards the canonical-encoding replication (exit 0)',
        () async {
      if (python == null) {
        markTestSkipped('python3 not on PATH — skipping verifier interop');
        return;
      }
      final result = await Process.run(python!, [script, '--self-test']);
      expect(result.exitCode, 0,
          reason: '${result.stdout}\n${result.stderr}');
    });
  });
}
