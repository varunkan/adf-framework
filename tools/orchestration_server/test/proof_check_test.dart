import 'dart:io';

import 'package:orchestration_server/proof_check.dart';
import 'package:test/test.dart';

bool _pythonAvailable() {
  try {
    return Process.runSync('python3', ['--version']).exitCode == 0;
  } catch (_) {
    return false;
  }
}

/// Locate the repo's scripts/orch so the test can seal a real proof with the
/// canonical Python sealer (single source of truth).
String _repoScriptsOrch() {
  var dir = Directory.current;
  for (var i = 0; i < 6; i++) {
    final cand = Directory('${dir.path}/scripts/orch');
    if (File('${cand.path}/proof_of_build.py').existsSync()) return cand.path;
    dir = dir.parent;
  }
  throw StateError('could not find scripts/orch from ${Directory.current.path}');
}

void main() {
  late Directory repo;
  late ProofCheck proof;
  final srcScripts = _repoScriptsOrch();

  setUp(() {
    repo = Directory.systemTemp.createTempSync('adf-proofcheck');
    // Bring the canonical verifier + sealer into the temp repo.
    Directory('${repo.path}/scripts/orch').createSync(recursive: true);
    for (final f in [
      'proof_of_build.py',
      'verify_proof.py',
      'agent_runner.py',
      'policy_gate.py',
    ]) {
      File('$srcScripts/$f').copySync('${repo.path}/scripts/orch/$f');
    }
    proof = ProofCheck(repo.path);
  });

  tearDown(() {
    if (repo.existsSync()) repo.deleteSync(recursive: true);
  });

  void sealDemoApp() {
    final app = Directory('${repo.path}/apps/demo')..createSync(recursive: true);
    File('${app.path}/main.ts').writeAsStringSync('export const x = 1\n');
    final r = Process.runSync('python3', [
      '-c',
      "import sys; sys.path.insert(0, r'${repo.path}/scripts/orch'); "
          "import proof_of_build as p; "
          "p.seal_app(r'${app.path}', 'demo', 'react-vite-sqlite', 'the spec', "
          "{'verified': True, 'verify_summary': 'ok'})",
    ]);
    expect(r.exitCode, 0, reason: '${r.stdout}\n${r.stderr}');
  }

  test('no proof -> has_proof false', () async {
    Directory('${repo.path}/apps/demo').createSync(recursive: true);
    final res = await proof.verify('demo');
    expect(res['has_proof'], isFalse);
  });

  test('sealed app verifies VERIFIED', () async {
    sealDemoApp();
    final res = await proof.verify('demo');
    expect(res['has_proof'], isTrue);
    expect(res['ok'], isTrue, reason: res.toString());
    expect(res['status'], 'VERIFIED');
    expect((res['seal'] as String).startsWith('adf1:'), isTrue);
    // A live governance verdict rides along with the proof.
    final policy = res['policy'] as Map<String, dynamic>?;
    expect(policy, isNotNull, reason: res.toString());
    expect(policy!['ok'], isTrue, reason: policy.toString());
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('a hardcoded secret makes the live policy verdict fail', () async {
    sealDemoApp();
    File('${repo.path}/apps/demo/leak.mjs')
        .writeAsStringSync("const K = 'sk-abcdEFGH1234567890ZXCVbnmQWERtyui'\n");
    final res = await proof.verify('demo');
    final policy = res['policy'] as Map<String, dynamic>?;
    expect(policy?['ok'], isFalse, reason: res.toString());
    expect((policy?['n_violations'] as num) >= 1, isTrue);
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('tampering a sealed file is reported as TAMPERED', () async {
    sealDemoApp();
    File('${repo.path}/apps/demo/main.ts')
        .writeAsStringSync('export const x = 999 // tampered\n');
    final res = await proof.verify('demo');
    expect(res['ok'], isFalse);
    expect(res['status'], 'TAMPERED');
    final files = (res['files'] as List).cast<Map>();
    final bad = files.where((f) => f['status'] != 'ok').toList();
    expect(bad.length, 1);
    expect(bad.first['path'], 'main.ts');
    expect(bad.first['status'], 'modified');
  }, skip: _pythonAvailable() ? false : 'python3 not available');
}
