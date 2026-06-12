import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

void main() {
  test('self-heal poller survives a corrupt feature with no state.json',
      () async {
    var repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      repoRoot = Directory(repoRoot).parent.path;
    }
    final store = FeatureStore(repoRoot);
    const id = 'corrupt-resilience-feat';
    final dir = Directory(store.featurePath(id));
    if (dir.existsSync()) dir.deleteSync(recursive: true);

    // A directory with telemetry but NO state.json — exactly the shape that
    // previously threw out of the background timer and crashed the server.
    dir.createSync(recursive: true);
    File('${dir.path}/requirement.md').writeAsStringSync('orphan requirement');
    File('${dir.path}/run-status.json')
        .writeAsStringSync('{"status":"error","phase":2,"error":"boom"}');

    final runner =
        PhaseRunner(store, pollInterval: const Duration(milliseconds: 50));
    runner.startBackgroundPoller();
    // Let several poll cycles run over the corrupt feature.
    await Future<void>.delayed(const Duration(milliseconds: 300));
    runner.stop();

    // The process is still alive and the store is still usable — the poller
    // skipped the bad feature instead of throwing.
    expect(store.listFeatures(), contains(id));

    dir.deleteSync(recursive: true);
  }, timeout: const Timeout(Duration(seconds: 20)));
}
