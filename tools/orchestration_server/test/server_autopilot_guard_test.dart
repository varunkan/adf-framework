@Timeout(Duration(seconds: 120))
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

/// G05 (AC-6 / AC-7): drives the ACTUAL production seam — the running HTTP server
/// and its `POST /features/<id>/autopilot` route, which funnels through
/// `runCrewForFeature` and its `crewGate.tryAcquire(id)` guard. This is the
/// teeth-bearing companion to agent_crew_concurrency_test.dart: that file
/// exercises the CrewGate primitive directly; THIS file proves the guard is
/// actually wired into the server seam. If `crewGate.tryAcquire(id)` is removed
/// from `runCrewForFeature` in bin/server.dart, the second concurrent POST below
/// no longer returns 409 and this test FAILS (mutation-verified).
///
/// Boots the real server on an EPHEMERAL port (ORCH_PORT=0) — never a hardcoded
/// port — and reads the actual bound port back from the server's stdout banner.
void main() {
  late String repoRoot;
  late FeatureStore store;
  late Process server;
  late int port;
  final createdIds = <String>[];

  // Resolve the real repo root (walk up to .cursor/orchestration).
  String findRepoRoot() {
    var dir = Directory.current.path;
    while (!Directory('$dir/.cursor/orchestration').existsSync()) {
      final parent = Directory(dir).parent;
      if (parent.path == dir) throw StateError('repo root not found');
      dir = parent.path;
    }
    return dir;
  }

  setUpAll(() async {
    repoRoot = findRepoRoot();
    store = FeatureStore(repoRoot);
    server = await Process.start(
      'dart',
      ['run', 'bin/server.dart'],
      environment: {
        'ORCH_PORT': '0', // ephemeral — OS picks a free port
        'ORCH_REPO_ROOT': repoRoot,
        'ORCH_AUTO_RUNNER': 'false', // no headless-runner probes
        'ORCH_AUTO_AUTOPILOT': 'false', // create does NOT auto-kick the crew
      },
      workingDirectory: '$repoRoot/tools/orchestration_server',
    );
    // Parse the bound port from the startup banner: "  http://127.0.0.1:<port>".
    final portCompleter = Completer<int>();
    server.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen(
      (line) {
        final m = RegExp(r'http://127\.0\.0\.1:(\d+)').firstMatch(line);
        if (m != null && !portCompleter.isCompleted) {
          portCompleter.complete(int.parse(m.group(1)!));
        }
      },
    );
    // Surface server stderr if the boot fails (helps diagnose a flaky CI box).
    server.stderr.transform(utf8.decoder).listen((_) {});
    port = await portCompleter.future
        .timeout(const Duration(seconds: 60), onTimeout: () {
      throw StateError('server did not print its port within 60s');
    });
  });

  tearDownAll(() async {
    server.kill(ProcessSignal.sigterm);
    await server.exitCode.timeout(const Duration(seconds: 10),
        onTimeout: () => -1);
    for (final id in createdIds) {
      if (store.featureExists(id)) {
        Directory(store.featurePath(id)).deleteSync(recursive: true);
      }
      final specDir = Directory('$repoRoot/specs/$id');
      if (specDir.existsSync()) specDir.deleteSync(recursive: true);
    }
  });

  Future<HttpClientResponse> postJson(String path, Object body) async {
    final client = HttpClient();
    try {
      final req = await client.postUrl(Uri.parse('http://127.0.0.1:$port$path'));
      req.headers.contentType = ContentType.json;
      req.add(utf8.encode(jsonEncode(body)));
      return await req.close();
    } finally {
      client.close(force: false);
    }
  }

  Future<String> createFeature() async {
    final resp = await postJson('/features', {
      'requirement': 'Render a checkout screen. Print a receipt. '
          'Email the receipt to the customer.',
      'track': 'M',
    });
    expect(resp.statusCode, 201, reason: 'feature create should return 201');
    final payload =
        jsonDecode(await resp.transform(utf8.decoder).join()) as Map;
    final id = payload['id'] as String;
    createdIds.add(id);
    return id;
  }

  // AC-6: a second concurrent POST /features/<id>/autopilot while the first
  // crew run is in flight returns HTTP 409 with the exact contract body.
  test('concurrent POST /autopilot → one runs, the second gets HTTP 409',
      () async {
    final id = await createFeature();

    // Fire both POSTs without awaiting between them so they race on the server's
    // event loop. The first handler synchronously claims the gate (tryAcquire
    // runs BEFORE the first await in runCrewForFeature) and holds it across the
    // crew run; the second sees the marker and returns 409.
    final clientA = HttpClient();
    final clientB = HttpClient();
    Future<HttpClientResponse> kick(HttpClient c) async {
      final r = await c
          .postUrl(Uri.parse('http://127.0.0.1:$port/features/$id/autopilot'));
      r.headers.contentType = ContentType.json;
      r.add(utf8.encode('{}'));
      return r.close();
    }

    try {
      final results = await Future.wait([kick(clientA), kick(clientB)]);
      final bodies = await Future.wait(
          results.map((r) => r.transform(utf8.decoder).join()));
      final statuses = results.map((r) => r.statusCode).toList();

      expect(statuses, contains(409),
          reason: 'one of two concurrent autopilot POSTs must be rejected 409 — '
              'if it is not, the crewGate guard is missing from '
              'runCrewForFeature');
      // Exactly one 409 (the other is the admitted run: 200, or a 500 if the
      // deterministic crew body itself errors — but never a second 409).
      expect(statuses.where((s) => s == 409).length, 1,
          reason: 'exactly one concurrent trigger should be rejected');

      // The 409 body matches the documented contract exactly.
      final conflictIdx = statuses.indexOf(409);
      final conflictBody = jsonDecode(bodies[conflictIdx]) as Map;
      expect(conflictBody['error'], 'crew already in flight');
      expect(conflictBody['feature_id'], id);
    } finally {
      clientA.close(force: true);
      clientB.close(force: true);
    }
  });

  // AC-5 (released after completion) + sanity: once the in-flight run has
  // finished, a fresh sequential POST is admitted again (not permanently locked).
  test('a sequential POST /autopilot after completion is admitted (not locked)',
      () async {
    final id = await createFeature();
    final first = await postJson('/features/$id/autopilot', {});
    await first.transform(utf8.decoder).join();
    expect(first.statusCode, anyOf(200, 500),
        reason: 'the single in-flight run is admitted, not 409');

    // Marker released in the finally of runCrewForFeature → a later run is allowed.
    final second = await postJson('/features/$id/autopilot', {});
    final secondBody = await second.transform(utf8.decoder).join();
    expect(second.statusCode, isNot(409),
        reason: 'sequential re-trigger after completion must NOT be locked out: '
            '$secondBody');
  });

  // AC-6 contract: unknown feature id → 404 (the guard is reached only for real
  // features; an unknown id is rejected before the gate).
  test('POST /autopilot for an unknown feature id returns 404', () async {
    final resp =
        await postJson('/features/nope-not-a-real-feature-id/autopilot', {});
    final body = await resp.transform(utf8.decoder).join();
    expect(resp.statusCode, 404, reason: body);
  });
}
