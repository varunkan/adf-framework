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

void main() {
  late String repoRoot;
  late FeatureStore store;
  late IntegrityChain chain;
  const id = 'integrity-chain-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    chain = IntegrityChain(store);
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Seal artifacts. Detect tampering. Prove integrity.',
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

  Future<Map<String, dynamic>> runCrew() => AgentCrew(
        store,
        DeterministicArtifactEngine(store, brain: DeterministicBrain()),
        ArtifactValidator(repoRoot),
        LearningStore(Directory.systemTemp.createTempSync('adf-ic').path),
        integrity: chain,
        env: const {'ADF_REQUIREMENTS_CREW': '0'}, // CREW-1: deterministic suite
      ).run(id);

  test('crew run produces a valid sealed chain over the full manifest',
      () async {
    final summary = await runCrew();
    final integrity = summary['integrity'] as Map<String, dynamic>;
    expect(integrity['valid'], isTrue);
    expect(integrity['blocks'], 6);
    expect(integrity['sealed_files'], greaterThan(8));
    expect(integrity['breaches'], isEmpty);

    final blocks = chain.blocks(id);
    expect(blocks.first['prev_hash'], 'genesis');
    for (var i = 1; i < blocks.length; i++) {
      expect(blocks[i]['prev_hash'], blocks[i - 1]['block_hash']);
    }
  });

  test('seal takes no scope parameter and still covers every proof file',
      () async {
    await runCrew();
    final manifest =
        (chain.blocks(id).last['manifest'] as Map).cast<String, String>();
    // Spec artifacts and feature state are sealed automatically.
    expect(manifest.keys.any((k) => k.endsWith('spec.md')), isTrue);
    expect(manifest.keys.any((k) => k.endsWith('state.json')), isTrue);
    // Telemetry streams are excluded by policy, not by a caller parameter.
    expect(manifest.keys.any((k) => k.endsWith('.jsonl')), isFalse);
  });

  test('editing a sealed artifact is detected as drift', () async {
    await runCrew();
    final spec = File('$repoRoot/specs/$id/spec.md');
    spec.writeAsStringSync(
        '${spec.readAsStringSync()}\n<!-- malicious edit -->\n');

    final result = chain.verify(id);
    expect(result['valid'], isFalse);
    final drift = (result['breaches'] as List)
        .firstWhere((b) => b['kind'] == 'artifact_drift');
    expect(drift['artifact'], 'specs/$id/spec.md');
  });

  test('injecting a new file cannot bypass the proof', () async {
    await runCrew();
    File('$repoRoot/specs/$id/backdoor.md')
        .writeAsStringSync('extra unsealed file');

    final result = chain.verify(id);
    expect(result['valid'], isFalse);
    final added = (result['breaches'] as List)
        .firstWhere((b) => b['kind'] == 'artifact_added');
    expect(added['artifact'], 'specs/$id/backdoor.md');
  });

  test('deleting a sealed file is detected as removal', () async {
    await runCrew();
    File('$repoRoot/specs/$id/spec.md').deleteSync();

    final result = chain.verify(id);
    expect(result['valid'], isFalse);
    final removed = (result['breaches'] as List)
        .firstWhere((b) => b['kind'] == 'artifact_removed');
    expect(removed['artifact'], 'specs/$id/spec.md');
  });

  test('rewriting ledger history is detected', () async {
    await runCrew();
    final ledger = File(chain.ledgerPath(id));
    final lines = ledger.readAsLinesSync();
    final forged = jsonDecode(lines[2]) as Map<String, dynamic>;
    forged['actor'] = 'attacker';
    lines[2] = jsonEncode(forged);
    ledger.writeAsStringSync('${lines.join('\n')}\n');

    final result = chain.verify(id);
    expect(result['valid'], isFalse);
    final kinds =
        (result['breaches'] as List).map((b) => b['kind']).toSet();
    expect(kinds, contains('ledger_rewrite'));
  });

  test('flipping a gate outside the pipeline is detected as forgery',
      () async {
    await runCrew();
    final state = store.readState(id);
    (state['gates'] as Map<String, dynamic>)['all_quality_gates_pass'] = true;
    store.writeState(id, state, skipRepair: true);

    final result = chain.verify(id);
    expect(result['valid'], isFalse);
    final kinds =
        (result['breaches'] as List).map((b) => b['kind']).toSet();
    expect(kinds, contains('gate_forgery'));
  });

  test('memoized verify invalidates and still catches a later tamper',
      () async {
    await runCrew();
    // Warm the memo with a clean verdict.
    expect(chain.verify(id)['valid'], isTrue);
    expect(chain.verify(id)['valid'], isTrue); // memo hit, same verdict

    // Tamper, then verify again: the stat fingerprint must invalidate the
    // memo so the breach is caught — no stale "valid" is ever returned.
    final spec = File('$repoRoot/specs/$id/spec.md');
    spec.writeAsStringSync('${spec.readAsStringSync()}\n<!-- late tamper -->');
    final after = chain.verify(id);
    expect(after['valid'], isFalse);
    expect((after['breaches'] as List).map((b) => b['kind']),
        contains('artifact_drift'));
  });

  test('strict verify always recomputes from raw bytes', () async {
    await runCrew();
    final result = chain.verify(id, strict: true);
    expect(result['strict'], isTrue);
    expect(result['valid'], isTrue);
  });

  test('canonical hashing is order-independent and stable', () {
    final a = IntegrityChain.canonical({'b': 1, 'a': 2});
    final b = IntegrityChain.canonical({'a': 2, 'b': 1});
    expect(a, b);
    expect(IntegrityChain.hashString(a), IntegrityChain.hashString(b));
    expect(IntegrityChain.hashString('x'), hasLength(64));
  });
}
